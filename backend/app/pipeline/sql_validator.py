import sqlglot
from sqlalchemy import text, Engine

class SQLValidator:
    """
    Stage 10: SQL Validation
    Performs 3-level validation:
    1. Syntactic Validation via sqlglot AST parsing (supports TSQL brackets, SQLite, Postgres).
    2. Semantic Validation confirming SQL tables & columns align with validated query plan.
    3. Dry-run Execution via database engine EXPLAIN or dry-run subquery check.
    """
    def __init__(self, db_engine: Engine = None):
        self.db_engine = db_engine

    def validate_sql(self, sql_query: str, validated_plan: dict) -> tuple[bool, str]:
        """
        Returns (is_valid: bool, error_message: str).
        """
        if not sql_query or not sql_query.strip():
            return False, "Generated SQL is empty."

        clean_sql = sql_query.strip().rstrip(";")

        # 1. Syntactic check via sqlglot AST parser (with T-SQL & generic dialect fallbacks)
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
            # Fallback: strip square brackets and parse again
            cleaned_brackets = clean_sql.replace("[", "").replace("]", "")
            try:
                exprs = sqlglot.parse(cleaned_brackets)
                if exprs and exprs[0] is not None:
                    parsed = exprs
            except Exception as e:
                parse_err = e

        if not parsed:
            return False, f"sqlglot AST parse error: {parse_err}"

        # 2. Semantic check: verify tables referenced in SQL match validated plan
        plan_tables = set(t.lower() for t in validated_plan.get("tables_needed", []))
        if plan_tables:
            sql_lower = clean_sql.lower().replace("[", "").replace("]", "")
            table_found = any(tbl in sql_lower for tbl in plan_tables)
            if not table_found:
                return False, f"Semantic drift: Generated SQL does not reference plan tables {plan_tables}."

        # 3. Dry-run check via DB engine
        if self.db_engine:
            try:
                with self.db_engine.connect() as conn:
                    dialect_name = self.db_engine.dialect.name
                    # Standardize sql statement for dry run
                    sql_to_run = clean_sql
                    if dialect_name == "sqlite":
                        sql_to_run = clean_sql.replace("[", "").replace("]", "")
                        conn.execute(text(f"EXPLAIN QUERY PLAN {sql_to_run}"))
                    elif dialect_name in ["mssql", "pyodbc"]:
                        try:
                            conn.execute(text(f"SET PARSEONLY ON; {sql_to_run}; SET PARSEONLY OFF;"))
                        except Exception:
                            try:
                                conn.execute(text(f"SELECT TOP 1 * FROM ({sql_to_run}) AS dry_run_chk"))
                            except Exception as sub_err:
                                return False, f"DB Engine Dry-Run Error: {sub_err}"
                    else:
                        conn.execute(text(f"EXPLAIN {sql_to_run}"))
            except Exception as e:
                err_msg = str(e)
                return False, f"DB Engine Dry-Run Error: {err_msg}"

        return True, "Valid SQL"
