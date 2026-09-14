from sentence_transformers import SentenceTransformer, util
from app.config import config

class FollowupDetector:
    """
    Stage 2: Follow-up Detection
    Determines if the normalized current query is a follow-up turn to a previous session question
    by analyzing trigger words and embedding cosine similarity.
    """
    def __init__(self, embedder: SentenceTransformer = None):
        self.embedder = embedder

    def is_followup(self, current_query: str, previous_query: str = None) -> tuple[bool, float]:
        """
        Returns (is_followup_boolean, similarity_score).
        """
        if not previous_query or not previous_query.strip():
            return False, 0.0

        current_lower = current_query.strip().lower()
        
        # Check anaphora / trigger words
        has_trigger = any(trigger in current_lower for trigger in config.FOLLOWUP_TRIGGER_WORDS)
        
        # Check if query is short / elliptical (e.g. "what about Mumbai?", "in Noida?")
        words = current_lower.split()
        is_short = len(words) <= 5

        similarity = 0.0
        if self.embedder and previous_query:
            try:
                emb_curr = self.embedder.encode(current_query, convert_to_tensor=True)
                emb_prev = self.embedder.encode(previous_query, convert_to_tensor=True)
                similarity = float(util.cos_sim(emb_curr, emb_prev)[0][0])
            except Exception as e:
                print(f"[FOLLOWUP DETECTOR WARNING] Embedding similarity calculation failed: {e}")
                similarity = 0.0

        # Decision rule: trigger present OR (high similarity AND short/incomplete)
        if has_trigger or (similarity >= config.FOLLOWUP_EMBEDDING_SIMILARITY_THRESHOLD and is_short):
            return True, similarity

        return False, similarity
