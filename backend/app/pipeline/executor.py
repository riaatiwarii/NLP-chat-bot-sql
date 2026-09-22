import re
from sqlalchemy import text, Engine

class SQLExecutor:
    """
    Stage 13: Execution
    Runs validated parameterized SQL against the database engine.
    """
    def __init__(self, db_engine: Engine = None):
        self.db_engine = db_engine

    def execute(self, sql_query: str, params: dict = None) -> tuple[list[dict], list[str], int, str]:
        if not self.db_engine:
            return [], [], 0, "No database engine configured."

        bind = params or {}
        # Convert numeric string IDs to integers for proper parameter binding
        for key, value in bind.items():
            if isinstance(value, str) and value.isdigit():
                bind[key] = int(value)
        
        print(f"[EXECUTOR] SQL: {sql_query}")
        print(f"[EXECUTOR] Params: {bind}")
        
        try:
            with self.db_engine.connect() as conn:
                result = conn.execute(text(sql_query), bind)
                if result.returns_rows:
                    keys = list(result.keys())
                    raw_rows = result.fetchall()
                    rows = []
                    for row in raw_rows:
                        row_dict = {}
                        for k, v in zip(keys, row):
                            if hasattr(v, '__float__') and not isinstance(v, (int, float, str, bool)):
                                v = float(v)
                            elif hasattr(v, 'isoformat'):
                                v = v.isoformat()
                            elif v is not None and not isinstance(v, (int, float, str, bool, list, dict)):
                                v = str(v)
                            row_dict[k] = v
                        rows.append(row_dict)

                    total_count = len(rows)
                    # For TOP listing queries, run separate COUNT(*) to get actual matching count in DB
                    if "TOP " in sql_query.upper() and "GROUP BY" not in sql_query.upper() and "DISTINCT" not in sql_query.upper():
                        try:
                            match = re.search(r'\bFROM\b\s+(.*)', sql_query, re.IGNORECASE | re.DOTALL)
                            if match:
                                from_part = match.group(1)
                                order_idx = from_part.upper().rfind("ORDER BY")
                                if order_idx != -1:
                                    from_part = from_part[:order_idx]
                                count_sql = f"SELECT COUNT(*) FROM {from_part.strip()}"
                                cnt_res = conn.execute(text(count_sql), bind).scalar()
                                if cnt_res is not None:
                                    total_count = int(cnt_res)
                        except Exception as count_err:
                            print(f"[EXECUTOR WARNING] Could not fetch total count: {count_err}", flush=True)

                    return rows, keys, total_count, ""
                else:
                    return [], [], 0, ""
        except Exception as e:
            return [], [], 0, f"Database Execution Error: {e}"
