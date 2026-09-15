import rapidfuzz.fuzz as fuzz
import jellyfish
from app.config import config

class IntentResolver:
    """
    Stage 5: Intent-Keyword Resolution
    Maps extracted intent candidate words to canonical SQL operations (COUNT, AVG, SUM, MAX, MIN, SELECT)
    using exact dictionary lookup, rapidfuzz fuzzy matching, and jellyfish phonetic matching.
    """
    def __init__(self):
        self.vocab_map = config.INTENT_VOCAB_MAP

    def resolve_intent(self, intent_spans: list[dict], raw_query: str) -> str:
        """
        Resolves the overall primary SQL intent (e.g., 'COUNT', 'AVG', 'SUM', 'MAX', 'MIN', 'SELECT').
        Defaults to 'SELECT' if no aggregation keyword is matched.
        """
        query_lower = raw_query.lower()

        import re

        # 0. Check summary / aggregate count phrase synonyms
        if any(p in query_lower for p in [
            "total alert summary", "count of total alerts", "count of alerts",
            "total alerts", "summary of alerts", "alert summary", "total alert count"
        ]):
            return "SUMMARY"

        # Check distinct listing intent
        if re.search(r'\b(?:list\s+the\s+|list\s+)?(?:lho|lhos|branch|branches|zone|zones|jurisdiction|jurisdictions)\b', query_lower):
            if not any(k in query_lower for k in ["alert", "alerts", "count", "how many"]):
                return "SELECT_DISTINCT"

        # 1. Exact phrase match with word boundaries
        for phrase, canonical in self.vocab_map.items():
            if re.search(r'\b' + re.escape(phrase) + r'\b', query_lower):
                return canonical

        # 2. Fuzzy + Phonetic matching over extracted intent spans
        for item in intent_spans:
            span = item.get("span", "").lower()
            if not span:
                continue

            # Exact key match
            if span in self.vocab_map:
                return self.vocab_map[span]

            # Fuzzy match via rapidfuzz
            best_score = 0
            best_canonical = None
            for kw, canonical in self.vocab_map.items():
                score = fuzz.WRatio(span, kw)
                if score > best_score:
                    best_score = score
                    best_canonical = canonical

            if best_score >= config.INTENT_RESOLVER_FUZZY_THRESHOLD:
                return best_canonical

            # Phonetic match via jellyfish
            span_metaphone = jellyfish.metaphone(span)
            for kw, canonical in self.vocab_map.items():
                if jellyfish.metaphone(kw) == span_metaphone:
                    return canonical

        # Default fallback intent
        return "SELECT"
