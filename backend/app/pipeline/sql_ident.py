import re
from app.config import config

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED_OPS = {"=", "!=", "<>", ">", "<", ">=", "<=", "LIKE"}
_AGG_SELECT = {"totalalerts", "count(*)", "count"}


def resolve_allowed_table(name: str) -> str:
    if not name or not isinstance(name, str):
        raise ValueError("SQL table name is empty.")
    raw = name.strip().strip("[]").split(".")[-1]
    for allowed in config.ALLOWED_TABLES:
        if allowed.lower() == raw.lower():
            return allowed
    raise ValueError(f"Table '{name}' is outside the approved CMS alert schema.")


def resolve_allowed_column(name: str, table_cols: list[str]) -> str:
    if not name or not isinstance(name, str):
        raise ValueError("SQL column name is empty.")
    raw = name.strip().strip("[]").split(".")[-1]
    if raw.lower() in _AGG_SELECT:
        raise ValueError(f"Column '{name}' is an aggregate alias, not a physical column.")
    cols = table_cols or []
    for c in cols:
        if c.lower() == raw.lower():
            if not _IDENT.match(c):
                raise ValueError(f"Column '{c}' is not a valid identifier.")
            return c
    raise ValueError(f"Column '{name}' is not on the approved table schema.")


def bracket(ident: str) -> str:
    if not _IDENT.match(ident):
        raise ValueError(f"Refusing to interpolate identifier '{ident}'.")
    return f"[{ident}]"


def qualify(table: str, column: str) -> str:
    return f"{table}.{bracket(column)}"


def resolve_operator(op: str) -> str:
    token = (op or "=").strip().upper()
    if token not in _ALLOWED_OPS:
        raise ValueError(f"SQL operator '{op}' is not allowed.")
    return token


def resolve_limit(limit) -> int | None:
    if limit is None or limit == "":
        return None
    n = int(limit)
    if n < 1 or n > 500:
        raise ValueError("SQL TOP/LIMIT must be an integer between 1 and 500.")
    return n


def resolve_order_dir(token: str) -> str:
    d = (token or "DESC").strip().upper()
    if d not in {"ASC", "DESC"}:
        raise ValueError(f"ORDER BY direction '{token}' is not allowed.")
    return d
