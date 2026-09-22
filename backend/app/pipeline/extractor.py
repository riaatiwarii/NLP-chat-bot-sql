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
        # AlertType patterns (e.g. VMS, CCTV, Motion, Smoke, Fire, Burglary, Tamper, ATM, Intrusion, Two Way, Panic, Shutter)
        alert_type_matches = re.findall(r'\b(vms|cctv|motion|smoke|fire|burglary|tamper|tampering|atm|intrusion|two[\s-]way|two\s+way|panic|shutter|glass[\s-]break|pir|vibration|dvr|nvr)\b', text, re.IGNORECASE)
        for match in alert_type_matches:
            entity_spans.append({"span": match, "type": "alert_type"})

        # Status / Severity patterns (exclude 'high' when part of 'highest' and 'low' when part of 'lowest')
        severity_matches = re.findall(r'\b(offline|online|active|open|closed|unresolved|pending|resolved|critical|high\s+severe|high\s+severity|high|medium|low|tampering|breach|panic)\b', text, re.IGNORECASE)
        for match in severity_matches:
            m_low = match.lower()
            if m_low == "high" and "highest" in text.lower():
                continue
            if m_low == "low" and "lowest" in text.lower():
                continue
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

        # Date expression patterns (relative, day of week, and explicit/text dates)
        date_relative_matches = re.findall(r'\b(today|yesterday|this week|last week|this month|last 7 days|past 7 days|past week|last month|past month|last 30 days|past 30 days|last monday|last tuesday|last wednesday|last thursday|last friday|last saturday|last sunday|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', text, re.IGNORECASE)
        for dmatch in date_relative_matches:
            entity_spans.append({"span": dmatch, "type": "date_relative"})

        # Explicit and text date format patterns (YYYY-MM-DD, DD/MM/YYYY, 16 September, 16 Sep, 16th September, between ... and ...)
        date_explicit_matches = re.findall(
            r'\b(?:between|from)\s+[a-z0-9\s/]+?\s+(?:and|to|-)\s+[a-z0-9\s/]+(?:\s+\d{4})?\b|'
            r'\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b|'
            r'\b\d{1,2}(?:st|nd|rd|th)?\s+(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)(?:\s+\d{4})?\b|'
            r'\b(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+\d{1,2}(?:st|nd|rd|th)?(?:\s+\d{4})?\b',
            text, re.IGNORECASE
        )
        for edmatch in date_explicit_matches:
            entity_spans.append({"span": edmatch, "type": "date_explicit"})

        # Numeric ID patterns (explicit AlertID or standalone digits, excluding explicit date parts)
        explicit_id_matches = re.findall(r'\b(?:alert\s*id|alertid|alert|ticket|case|id|ref|record)\s*#?\s*:?\s*(\d+)\b', text, re.IGNORECASE)
        for num_id in explicit_id_matches:
            entity_spans.append({"span": num_id, "type": "numeric_id"})

        number_matches = re.findall(r'\b\d+\b', text)
        for num in number_matches:
            is_year = len(num) == 4 and 1900 <= int(num) <= 2100
            if not any(num in ed for ed in date_explicit_matches) and len(num) >= 3 and not is_year:
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
        months_set = {
            "january", "february", "march", "april", "may", "june", "july", "august",
            "september", "october", "november", "december", "jan", "feb", "mar", "apr",
            "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"
        }
        skip_words = {
            "show", "list", "count", "how", "what", "which", "tell", "me", "about",
            "recent", "latest", "newest", "highest", "lowest", "least", "most", "top", "max", "min", "all",
            "alert", "alerts", "details", "data", "log", "logs", "record", "records",
            "more", "some", "any", "branch", "branches", "zone", "zones", "type", "types", "subtype", "subtypes", "alerttype",
            "summary", "dashboard", "breakdown", "distribution",
            "area", "areas", "location", "locations", "has", "the", "in", "for", "with", "of", "is", "are",
            "by", "their", "wise", "and", "or", "between", "from", "to", "during", "on", "at",
            "unresolved", "resolved", "pending", "closed", "open", "high", "low", "medium", "critical",
            "vms", "cctv", "motion", "smoke", "fire", "atm", "dvr", "nvr"
        } | months_set

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
