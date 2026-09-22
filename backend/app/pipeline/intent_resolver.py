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

        # 0. Check DISTINCT intent ("type of alerts", "what alert types exist", "list branches", etc.)
        if any(p in query_lower for p in ["type of alert", "types of alert", "type of alerts", "types of alerts", "alert type", "alert types", "what alert type", "which alert type", "list alert type", "show alert type"]) or \
           re.search(r'\b(?:list|show|get|view)\s+(?:me\s+)?(?:the\s+)?(?:lhos?|branch(?:es)?|zone[s]?|jurisdiction[s]?)\b', query_lower):
            if not any(k in query_lower for k in ["summary", "breakdown", "how many", "count of", "total", "distribution", "highest", "lowest", "least", "most", "by"]):
                return "SELECT_DISTINCT"

        # 0.1 Check Ranking queries ("which branch has lowest alerts", "which alert type occurs least", "most alerts", etc.)
        if any(k in query_lower for k in ["highest", "lowest", "least", "most", "fewest", "smallest", "maximum", "minimum", "top "]):
            return "SUMMARY"

        # 0.2 Check "by [dimension]" queries ("alerts by their status", "alerts by branch", "by severity", "branch wise")
        if re.search(r'\b(?:by\s+(?:their\s+)?(?:status|severity|branch|area|type|alert\s*type|lho|zone)|(?:status|severity|branch|area|type|alert\s*type|lho|zone)\s*(?:wise|breakdown|summary))\b', query_lower):
            return "SUMMARY"

        # 0.3 Check count / quantity phrases (exclude rankings and summaries)
        if any(k in query_lower for k in ["how many", "count of", "total number of", "total number", "how much", "count"]):
            if not any(k in query_lower for k in ["summary", "breakdown", "distribution", "highest", "most", "top", "lowest", "least", "fewest", "min", "max", "which", "by"]):
                return "COUNT"

        # Check summary / aggregate count phrase synonyms
        if any(p in query_lower for p in [
            "total alert summary", "count of total alerts", "count of alerts",
            "total alerts", "summary of alerts", "alert summary", "total alert count",
            "breakdown", "distribution"
        ]):
            return "SUMMARY"

        # 1. Exact phrase match with word boundaries (sorted by length descending to match multi-word phrases first)
        sorted_vocab = sorted(self.vocab_map.items(), key=lambda x: len(x[0]), reverse=True)
        for phrase, canonical in sorted_vocab:
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
