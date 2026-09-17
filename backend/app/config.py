import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from backend directory if present
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

class Config:
    # Service & Network Configurations
    PORT: int = int(os.getenv("PORT", "8001"))
    
    # Sanitize OLLAMA_HOST to guarantee valid http:// URL and client-reachable IP
    _raw_host: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
    if not _raw_host.startswith("http://") and not _raw_host.startswith("https://"):
        _raw_host = "http://" + _raw_host
    OLLAMA_HOST: str = _raw_host.replace("0.0.0.0", "127.0.0.1")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
    OLLAMA_RESPONSE_MODEL: str = os.getenv("OLLAMA_RESPONSE_MODEL", "qwen2.5-coder:7b")
    OLLAMA_TIMEOUT: tuple = (10.0, 300.0)

    # Database Configuration (SQLAlchemy Connection String)
    DB_CONNECTION_STRING: str = os.getenv(
        "DB_CONNECTION_STRING",
        os.getenv("DATABASE_URL", "sqlite:///backend/app/db.json")
    )
    
    # Target Database Table Filtering (Scoped strictly to 6 confirmed allowed tables)
    ALLOWED_TABLES: list = [
        "AlertAttachment", "AlertsDetails", "Jurisdiction_mstr",
        "RawAttachments", "Sensor_Master", "Junction_mstr"
    ]

    # Redis Configuration (Optional read/write cache for Alias Table and Session Memory)
    REDIS_HOST: str = os.getenv("REDIS_HOST", "127.0.0.1")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")
    REDIS_ENABLED: bool = os.getenv("REDIS_ENABLED", "true").lower() in ("true", "1", "yes")

    # Data Directory Paths
    BASE_DIR: Path = Path(__file__).resolve().parent
    DATA_DIR: Path = BASE_DIR / "data"
    ALIAS_TABLE_PATH: Path = DATA_DIR / "alias_table.json"
    FEEDBACK_DATASET_PATH: Path = DATA_DIR / "feedback_dataset.jsonl"
    DICTIONARY_PATH: Path = DATA_DIR / "symspell_dictionary.txt"

    # Stage 1: Input Normalization Thresholds
    SYMSPELL_MAX_EDIT_DISTANCE: int = int(os.getenv("SYMSPELL_MAX_EDIT_DISTANCE", "2"))
    SYMSPELL_PREFIX_LENGTH: int = int(os.getenv("SYMSPELL_PREFIX_LENGTH", "7"))

    # Stage 2: Follow-up Detection Thresholds
    FOLLOWUP_EMBEDDING_SIMILARITY_THRESHOLD: float = float(
        os.getenv("FOLLOWUP_EMBEDDING_SIMILARITY_THRESHOLD", "0.72")
    )
    FOLLOWUP_TRIGGER_WORDS = [
        "same", "that", "also", "instead", "what about", "and", "them", "these", "it", "more", "previous"
    ]

    # Stage 4: Value Resolution Cascade Thresholds
    VALUE_RESOLVER_FUZZY_THRESHOLD: float = float(os.getenv("VALUE_RESOLVER_FUZZY_THRESHOLD", "82.0"))
    VALUE_RESOLVER_PHONETIC_THRESHOLD: float = float(os.getenv("VALUE_RESOLVER_PHONETIC_THRESHOLD", "80.0"))
    VALUE_RESOLVER_EMBEDDING_THRESHOLD: float = float(os.getenv("VALUE_RESOLVER_EMBEDDING_THRESHOLD", "0.75"))

    # Response & Environment Display Flags
    SHOW_GENERATED_SQL: bool = os.getenv("SHOW_GENERATED_SQL", "false").lower() in ("true", "1", "yes")
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Kolkata")
    LIST_QUERY_ROW_LIMIT: int = int(os.getenv("LIST_QUERY_ROW_LIMIT", "50"))

    # Column Classification (Display Columns vs Excluded Internal Columns)
    DEFAULT_DISPLAY_COLUMNS: list = [
        "AlertID", "AlertType", "AlertSubtype", "Status", "Zone", "Area", "Severity", "Datetime", "Remarks", "CameraName", "NearestCamera"
    ]
    INTERNAL_COLUMNS: list = [
        "Location", "SensorId", "Id", "CreatedBy", "UpdatedBy", "CreatedTime", "UpdatedTime",
        "SystemName", "EsclationEnable", "AlertExternalValue", "AlertExternalId",
        "ResponderStatus", "attachment", "Imageattachment", "Videoattachment"
    ]

    # Stage 5: Intent Keyword Vocab Map
    INTENT_VOCAB_MAP = {
        "count of total alerts": "SUMMARY",
        "total alert summary": "SUMMARY",
        "count of alerts": "SUMMARY",
        "total alerts": "SUMMARY",
        "summary of alerts": "SUMMARY",
        "alert summary": "SUMMARY",
        "count": "COUNT",
        "cnt": "COUNT",
        "kount": "COUNT",
        "number of": "COUNT",
        "total number": "COUNT",
        "how many": "COUNT",
        "avg": "AVG",
        "average": "AVG",
        "mean": "AVG",
        "total": "SUM",
        "sum": "SUM",
        "list": "SELECT",
        "show": "SELECT",
        "get": "SELECT",
        "find": "SELECT",
        "display": "SELECT",
        "summary": "SUMMARY",
        "dashboard": "SUMMARY",
        "overview": "SUMMARY",
        "breakdown": "SUMMARY",
        "report": "SUMMARY",
        "max": "MAX",
        "maximum": "MAX",
        "highest": "MAX",
        "peak": "MAX",
        "min": "MIN",
        "minimum": "MIN",
        "lowest": "MIN"
    }
    INTENT_RESOLVER_FUZZY_THRESHOLD: float = float(os.getenv("INTENT_RESOLVER_FUZZY_THRESHOLD", "80.0"))

    # Stage 6: Schema Linking Thresholds
    SCHEMA_LINKER_SIMILARITY_THRESHOLD: float = float(os.getenv("SCHEMA_LINKER_SIMILARITY_THRESHOLD", "0.35"))
    SCHEMA_LINKER_TOP_K: int = int(os.getenv("SCHEMA_LINKER_TOP_K", "6"))

    # Stage 11: Self-Correction Loop Limits
    MAX_SELF_CORRECTION_ATTEMPTS: int = int(os.getenv("MAX_SELF_CORRECTION_ATTEMPTS", "2"))

    # Stage 12: Confidence Scoring & Abstention Threshold
    CONFIDENCE_ABSTENTION_THRESHOLD: float = float(os.getenv("CONFIDENCE_ABSTENTION_THRESHOLD", "0.65"))

    # Data Collection & Fine-tuning Dataset Safeguards
    MIN_FINETUNING_EXAMPLES: int = int(os.getenv("MIN_FINETUNING_EXAMPLES", "300"))

config = Config()
