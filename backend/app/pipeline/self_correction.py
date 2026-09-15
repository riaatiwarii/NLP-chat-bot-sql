from app.config import config
from app.pipeline.sql_generator import SQLGenerator
from app.pipeline.sql_validator import SQLValidator

class SelfCorrectionLoop:
    """
    Stage 11: Self-Correction Retry Loop
    Reinjects AST/DB execution errors back into SQL generation prompt.
    Caps retry attempts at config.MAX_SELF_CORRECTION_ATTEMPTS (default 2).
    """
    def __init__(self, sql_generator: SQLGenerator, sql_validator: SQLValidator):
        self.sql_generator = sql_generator
        self.sql_validator = sql_validator
        self.max_attempts = config.MAX_SELF_CORRECTION_ATTEMPTS

    def execute_with_retry(self, validated_plan: dict, schema_subset: dict) -> tuple[str, bool, str, int, bool]:
        """
        Attempts to generate and validate SQL, retrying up to max_attempts on failure.
        Returns (sql_query, is_valid, error_msg, attempts_count, used_fallback).
        """
        last_error = None
        current_sql = ""
        used_fallback = False

        for attempt in range(1, self.max_attempts + 1):
            gen_res = self.sql_generator.generate_sql(
                validated_plan, schema_subset, retry_error=last_error
            )
            if isinstance(gen_res, tuple):
                current_sql, fb = gen_res
            else:
                current_sql, fb = gen_res, False

            used_fallback = used_fallback or fb
            is_valid, err_msg = self.sql_validator.validate_sql(current_sql, validated_plan)

            if is_valid:
                return current_sql, True, "Valid SQL", attempt, used_fallback

            last_error = err_msg
            print(f"[SELF-CORRECT WARNING] Attempt {attempt}/{self.max_attempts} failed: {err_msg}")

        return current_sql, False, last_error or "Exceeded max self-correction retry attempts.", self.max_attempts, used_fallback
