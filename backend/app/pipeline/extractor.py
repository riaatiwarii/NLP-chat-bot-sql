import re
from app.config import config

class Extractor:
    """
    Stage 3: Intent + Entity Extraction
    Identifies candidate entity spans (places, dates, alert statuses, IDs) and intent action words.
    Does NOT resolve values to database schema canonical forms yet.
    """
    def __init__(self, known_locations: list[str] = None):
        self.known_locations = set(loc.lower() for loc in (known_locations or [
            "bhopal", "noida", "agra", "delhi", "new delhi", "nariman point", "pune", "ahmedabad", "chennai",
            "ao_noida", "ao_agra", "ao_north and west delhi", "north and west delhi", "lucknow", "kanpur"
        ]))

    def extract(self, query: str) -> dict:
        """
        Returns {
            "entity_spans": list of {"span": str, "type": str},
            "intent_spans": list of {"span": str, "type": "intent_word"}
        }
        """
        text = query.strip()
        words = text.split()

        entity_spans = []
        intent_spans = []

        # 1. Identify intent candidate words
        for word in words:
            clean_w = word.strip(".,?!;:()\"'").lower()
            if clean_w in config.INTENT_VOCAB_MAP or any(clean_w.startswith(k) for k in ["count", "avg", "sum"]):
                intent_spans.append({"span": word.strip(".,?!;:()\"'"), "type": "intent_word"})

        # 2. Identify candidate entity spans via regex & known dict matching
        # Status / Severity patterns
        severity_matches = re.findall(r'\b(offline|online|active|open|closed|unresolved|pending|resolved|critical|high|medium|low|tampering|breach|panic)\b', text, re.IGNORECASE)
        for match in severity_matches:
            entity_spans.append({"span": match, "type": "status_severity"})

        # Location / Place name patterns (multi-word and single word)
        lowered_text = text.lower()
        for loc in self.known_locations:
            if loc in lowered_text:
                # Find exact casing span in original text
                start_idx = lowered_text.find(loc)
                end_idx = start_idx + len(loc)
                actual_span = text[start_idx:end_idx]
                entity_spans.append({"span": actual_span, "type": "location"})

        # Date expression patterns (relative and explicit dates)
        date_relative_matches = re.findall(r'\b(today|yesterday|this week|last week|this month|last 7 days)\b', text, re.IGNORECASE)
        for dmatch in date_relative_matches:
            entity_spans.append({"span": dmatch, "type": "date_relative"})

        # Explicit date format patterns (YYYY-MM-DD or DD/MM/YYYY)
        date_explicit_matches = re.findall(r'\b\d{4}-\d{2}-\d{2}\b|\b\d{2}/\d{2}/\d{4}\b', text)
        for edmatch in date_explicit_matches:
            entity_spans.append({"span": edmatch, "type": "date_explicit"})

        # Numeric ID patterns (explicit AlertID or standalone digits, excluding explicit date parts)
        explicit_id_matches = re.findall(r'\b(?:alert\s*id|alertid|alert|ticket|case|id|ref|record)\s*#?\s*:?\s*(\d+)\b', text, re.IGNORECASE)
        for num_id in explicit_id_matches:
            entity_spans.append({"span": num_id, "type": "numeric_id"})

        number_matches = re.findall(r'\b\d+\b', text)
        for num in number_matches:
            if not any(num in ed for ed in date_explicit_matches) and len(num) >= 3:
                entity_spans.append({"span": num, "type": "numeric_id"})

        # Time-ordering patterns (recent, latest, newest)
        time_ordering_matches = re.findall(r'\b(recent|latest|newest)\b', text, re.IGNORECASE)
        for tmatch in time_ordering_matches:
            intent_spans.append({"span": tmatch, "type": "time_ordering"})

        # Distinct listing patterns (lho, lhos, branches, zones, jurisdictions)
        distinct_matches = re.findall(r'\b(lho|lhos|branch|branches|zone|zones|jurisdiction|jurisdictions)\b', text, re.IGNORECASE)
        for dmatch in distinct_matches:
            intent_spans.append({"span": dmatch, "type": "distinct_target"})
            if dmatch.lower() in ["lho", "lhos"]:
                entity_spans.append({"span": dmatch, "type": "candidate_entity"})

        # Fallback: if no location span was picked up, check capitalized proper nouns (len > 1)
        skip_words = {
            "show", "list", "count", "how", "what", "which", "tell", "me", "about",
            "recent", "latest", "newest", "highest", "top", "max", "min", "all",
            "alert", "alerts", "details", "data", "log", "logs", "record", "records",
            "more", "some", "any", "branch", "branches", "zone", "zones",
            "area", "areas", "location", "locations", "has", "the", "in", "for", "with", "of", "is", "are"
        }
        if not any(e["type"] == "location" for e in entity_spans):
            for word in words:
                clean_w = word.strip(".,?!;:()\"'")
                if clean_w and len(clean_w) > 1 and clean_w[0].isupper() and clean_w.lower() not in skip_words:
                    entity_spans.append({"span": clean_w, "type": "candidate_entity"})

        # Deduplicate entity spans by span string
        unique_entities = []
        seen = set()
        for e in entity_spans:
            key = (e["span"].lower(), e["type"])
            if key not in seen:
                seen.add(key)
                unique_entities.append(e)

        return {
            "entity_spans": unique_entities,
            "intent_spans": intent_spans
        }
