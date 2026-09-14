import json
import os
from datetime import datetime
from app.config import config
from app.pipeline.value_resolver import ValueResolver

class FeedbackStore:
    """
    Stage 15: Logging & Feedback Capture
    Logs query execution records, captures user/analyst 👍/👎 feedback,
    updates canonical JSON alias table immediately on value errors, and stores triples
    (question, wrong_SQL, correct_SQL) in feedback_dataset.jsonl for periodic manual fine-tuning.
    """
    def __init__(self, value_resolver: ValueResolver = None):
        self.value_resolver = value_resolver
        self.dataset_path = config.FEEDBACK_DATASET_PATH
        os.makedirs(config.DATA_DIR, exist_ok=True)

    def log_query(self, session_id: str, question: str, plan: dict, sql: str, confidence: float, result_count: int) -> dict:
        """
        Logs query execution trace.
        """
        record = {
            "type": "query_log",
            "session_id": session_id,
            "question": question,
            "plan": plan,
            "sql": sql,
            "confidence_score": confidence,
            "result_count": result_count,
            "timestamp": datetime.now().isoformat()
        }
        self._append_to_file(record)
        return record

    def record_feedback(
        self,
        session_id: str,
        question: str,
        rating: str, # "thumbs_up" or "thumbs_down"
        generated_sql: str = None,
        corrected_sql: str = None,
        correction_type: str = "logic", # "value" or "logic"
        alias_key: str = None,
        alias_canonical: str = None
    ) -> dict:
        """
        Records user/analyst feedback.
        - Value error: immediately writes to canonical JSON alias table.
        - Logic error: saves (question, wrong_SQL, correct_SQL) to JSONL dataset.
        """
        timestamp = datetime.now().isoformat()

        # Handle value-level correction
        if rating == "thumbs_down" and correction_type == "value" and alias_key and alias_canonical:
            if self.value_resolver:
                self.value_resolver.add_alias(alias_key, alias_canonical)
            feedback_entry = {
                "type": "value_correction",
                "session_id": session_id,
                "question": question,
                "alias_key": alias_key,
                "alias_canonical": alias_canonical,
                "rating": rating,
                "timestamp": timestamp
            }
            self._append_to_file(feedback_entry)
            return feedback_entry

        # Handle logic-level correction (wrong SQL -> correct SQL triple)
        feedback_entry = {
            "type": "logic_correction" if rating == "thumbs_down" else "positive_feedback",
            "session_id": session_id,
            "question": question,
            "wrong_SQL": generated_sql if rating == "thumbs_down" else None,
            "correct_SQL": corrected_sql if rating == "thumbs_down" else generated_sql,
            "rating": rating,
            "timestamp": timestamp
        }
        self._append_to_file(feedback_entry)
        return feedback_entry

    def get_dataset_count(self) -> int:
        """
        Returns number of feedback examples collected in feedback_dataset.jsonl.
        """
        if not os.path.exists(self.dataset_path):
            return 0

        count = 0
        try:
            with open(self.dataset_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        if data.get("type") in ["logic_correction", "positive_feedback"]:
                            count += 1
        except Exception:
            pass
        return count

    def _append_to_file(self, record: dict):
        try:
            with open(self.dataset_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            print(f"[FEEDBACK STORE ERROR] Could not append to feedback_dataset.jsonl: {e}")
