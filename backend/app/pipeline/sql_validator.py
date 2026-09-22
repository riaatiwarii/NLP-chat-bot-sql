import re
import sqlglot
from sqlalchemy import text, Engine
from app.config import config

class SQLValidator:
    """
    Stage 10: SQL Validation
    1. SELECT-only check
    2. Allowlisted tables
    3. sqlglot parse
    4. Dry-run with bound parameters
    """
    def __init__(self, db_engine: Engine = None):
        self.db_engine = db_engine

    def validate_sql(self, sql_query: str, validated_plan: dict, params: dict = None) -> tuple[bool, str, str]:
        if not sql_query or not sql_query.strip():
            return False, "Generated SQL is empty.", ""

        clean_sql = sql_query.strip().rstrip(";")
        bind = params or {}
        stripped = re.sub(r"\s+", " ", clean_sql).strip()
        if not re.match(r"^SELECT\b", stripped, re.IGNORECASE):
            return False, "Only SELECT statements are permitted.", clean_sql
        if re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|TRUNCATE|EXEC|EXECUTE|INTO)\b", stripped, re.IGNORECASE):
            return False, "Non-SELECT SQL is not permitted.", clean_sql

        allowed_lower = {t.lower() for t in config.ALLOWED_TABLES}
        for tbl in re.findall(r"\b(?:FROM|JOIN)\s+\[?([A-Za-z_][A-Za-z0-9_]*)\]?", clean_sql, re.IGNORECASE):
            if tbl.lower() not in allowed_lower:
                return False, f"SQL references table '{tbl}' which is outside the approved schema.", clean_sql

        parsed = None
        parse_err = None
        for dialect in ["tsql", "sqlite", "postgres", None]:
            try:
                exprs = sqlglot.parse(clean_sql, read=dialect)
                if exprs and exprs[0] is not None:
                    parsed = exprs
                    break
            except Exception as e:
                parse_err = e

        if not parsed:
            return False, f"sqlglot AST parse error: {parse_err}", clean_sql

        plan_tables = set(t.lower() for t in validated_plan.get("tables_needed", []))
        if plan_tables:
            sql_lower = clean_sql.lower().replace("[", "").replace("]", "")
            if not any(tbl in sql_lower for tbl in plan_tables):
                return False, f"Semantic drift: Generated SQL does not reference plan tables {plan_tables}.", clean_sql

        if self.db_engine:
            try:
                with self.db_engine.connect() as conn:
                    dialect_name = self.db_engine.dialect.name
                    sql_to_run = clean_sql
                    if dialect_name == "sqlite":
                        sql_to_run = clean_sql.replace("[", "").replace("]", "")
                        conn.execute(text(f"EXPLAIN QUERY PLAN {sql_to_run}"), bind)
                    elif dialect_name in ["mssql", "pyodbc"]:
                        sub_sql = re.sub(r"\s+ORDER\s+BY\s+.*$", "", sql_to_run, flags=re.IGNORECASE)
                        try:
                            conn.execute(text(f"SELECT TOP 1 * FROM ({sub_sql}) AS dry_run_chk"), bind)
                        except Exception:
                            try:
                                conn.execute(text(f"SET PARSEONLY ON; {sql_to_run}; SET PARSEONLY OFF;"))
                            except Exception as sub_err:
                                return False, f"DB Engine Dry-Run Error: {sub_err}", clean_sql
                    else:
                        conn.execute(text(f"EXPLAIN {sql_to_run}"), bind)
            except Exception as e:
                return False, f"DB Engine Dry-Run Error: {e}", clean_sql

        return True, "Valid SQL", clean_sql
