from app.config import config
from app.pipeline.sql_generator import SQLGenerator
from app.pipeline.sql_validator import SQLValidator

class SelfCorrectionLoop:
    """
    Stage 11: Self-Correction Retry Loop
    Rebuilds parameterized SQL from the plan and re-validates.
    """
    def __init__(self, sql_generator: SQLGenerator, sql_validator: SQLValidator):
        self.sql_generator = sql_generator
        self.sql_validator = sql_validator
        self.max_attempts = config.MAX_SELF_CORRECTION_ATTEMPTS

    def execute_with_retry(self, validated_plan: dict, schema_subset: dict) -> tuple[str, dict, bool, str, int, bool]:
        last_error = None
        current_sql = ""
        current_params = {}
        used_fallback = False

        for attempt in range(1, self.max_attempts + 1):
            gen_res = self.sql_generator.generate_sql(
                validated_plan, schema_subset, retry_error=last_error
            )
            current_sql, current_params, fb = self._unpack_gen(gen_res)
            used_fallback = used_fallback or fb
            is_valid, err_msg, healed_sql = self.sql_validator.validate_sql(
                current_sql, validated_plan, params=current_params
            )
            current_sql = healed_sql or current_sql

            if is_valid:
                return current_sql, current_params, True, "Valid SQL", attempt, used_fallback

            last_error = err_msg
            print(f"[SELF-CORRECT WARNING] Attempt {attempt}/{self.max_attempts} failed: {err_msg}")

        return current_sql, current_params, False, last_error or "Exceeded max self-correction retry attempts.", self.max_attempts, used_fallback

    def _unpack_gen(self, gen_res):
        if isinstance(gen_res, tuple) and len(gen_res) == 3:
            print(f"[SELF-CORRECT] Unpacking 3-tuple: {gen_res[0]}, params: {gen_res[1]}, fallback: {gen_res[2]}", flush=True)
            return gen_res[0], gen_res[1], gen_res[2]
        if isinstance(gen_res, tuple) and len(gen_res) == 2:
            sql, fb = gen_res
            print(f"[SELF-CORRECT] Unpacking 2-tuple (no params): {sql}, fallback: {fb}", flush=True)
            return sql, {}, fb
        print(f"[SELF-CORRECT] Unpacking non-tuple: {gen_res}", flush=True)
        return gen_res, {}, False
