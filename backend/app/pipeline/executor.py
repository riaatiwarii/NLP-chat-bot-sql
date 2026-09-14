from sqlalchemy import text, Engine

class SQLExecutor:
    """
    Stage 13: Execution
    Runs validated SQL queries safely against the database engine.
    """
    def __init__(self, db_engine: Engine = None):
        self.db_engine = db_engine

    def execute(self, sql_query: str) -> tuple[list[dict], list[str], int, str]:
        """
        Executes query and returns (rows_dict_list, column_names, total_count, error_msg).
        """
        if not self.db_engine:
            return [], [], 0, "No database engine configured."

        try:
            with self.db_engine.connect() as conn:
                result = conn.execute(text(sql_query))
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
                    # If query was capped with TOP / LIMIT, get un-capped total matching row count
                    if " TOP " in sql_query.upper() or " LIMIT " in sql_query.upper():
                        try:
                            import re
                            count_sql = re.sub(r'SELECT\s+(?:TOP\s+\d+\s+)?.*?\s+FROM\s+', 'SELECT COUNT(*) FROM ', sql_query, flags=re.IGNORECASE)
                            c_res = conn.execute(text(count_sql)).scalar()
                            if c_res is not None:
                                total_count = int(c_res)
                        except Exception:
                            pass

                    return rows, keys, total_count, ""
                else:
                    return [], [], 0, ""
        except Exception as e:
            return [], [], 0, f"Database Execution Error: {e}"
