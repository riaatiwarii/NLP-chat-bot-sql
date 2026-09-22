import os
import symspellpy
from symspellpy import SymSpell, Verbosity
from app.config import config

class InputNormalizer:
    """
    Stage 1: Input Normalization
    Uses SymSpell with a general 82k-word English frequency dictionary (bundled with
    symspellpy) as the base vocabulary, plus a domain dictionary of table/column names
    and operational business terms layered on top, to correct typos in raw query input.

    CRITICAL: without a real English base dictionary, SymSpell only knows domain jargon
    and will "correct" ordinary words it doesn't recognize (e.g. "new") into the nearest
    domain term by edit distance (e.g. "low") - silently corrupting the query before any
    other pipeline stage sees it. The bundled dictionary's real word frequencies (billions
    for common words like "new") ensure genuinely valid English words are recognized as
    already correct and never overridden by a domain term's synthetic frequency boost.
    """
    def __init__(self, schema_terms: list[str] = None):
        self.sym_spell = SymSpell(
            max_dictionary_edit_distance=config.SYMSPELL_MAX_EDIT_DISTANCE,
            prefix_length=config.SYMSPELL_PREFIX_LENGTH
        )
        self._load_dictionary(schema_terms or [])

    def _load_dictionary(self, schema_terms: list[str]):
        # Base vocabulary: bundled general English frequency dictionary (82,765 words).
        # Must be loaded FIRST so common English words are recognized as valid and are
        # never "corrected" into unrelated domain jargon by the layers added below.
        try:
            base_dict_path = os.path.join(os.path.dirname(symspellpy.__file__), "frequency_dictionary_en_82_765.txt")
            self.sym_spell.load_dictionary(base_dict_path, term_index=0, count_index=1)
        except Exception as e:
            print(f"[INPUT NORMALIZER WARNING] Could not load base English dictionary: {e}")

        # Domain-specific supplement (table/column names, operational terms)
        dict_path = str(config.DICTIONARY_PATH)
        if os.path.exists(dict_path):
            try:
                self.sym_spell.load_dictionary(dict_path, term_index=0, count_index=1)
            except Exception as e:
                print(f"[INPUT NORMALIZER WARNING] Could not load domain dictionary file: {e}")

        # Seed in-memory with any dynamically provided database schema terms
        for term in schema_terms:
            clean_term = term.strip().lower()
            if clean_term and len(clean_term) > 2:
                self.sym_spell.create_dictionary_entry(clean_term, 10000)

        # Seed common domain verb typos and vernacular location aliases
        custom_aliases = {
            "kount": "count", "cunt": "count", "lisst": "list", "shw": "show",
            "dilli": "delhi", "delhy": "delhi", "noida": "noida", "agra": "agra",
            "alerttype": "alert type", "alerttypes": "alert types"
        }
        # Add critical domain terms to preserve them from false auto-correction (e.g. low -> show, aug -> avg, type -> the)
        domain_terms = [
            "high", "low", "medium", "critical", "pending", "closed", "acknowledged", "unresolved", "open",
            "vms", "camera", "cctv", "motion", "smoke", "fire", "atm", "dvr", "nvr", "lho", "lhos", "branch", "branches", "area", "zone", "status", "severity",
            "alert", "alerts", "details", "dashboard", "summary", "breakdown", "distribution", "noida", "agra", "delhi", "bhopal", "kanpur", "lucknow",
            "highest", "lowest", "most", "least", "top", "max", "min", "maximum", "minimum", "count", "sum", "avg",
            "type", "types", "subtype", "subtypes", "alerttype", "alerttypes", "sensor", "sensors",
            "which", "what", "where", "who", "when", "how", "show", "list", "tell", "give", "select", "find", "get", "display",
            "many", "much", "number", "total", "for", "in", "at", "to", "from", "by", "of", "on", "with", "about", "the", "a", "an", "is", "are", "and", "or", "all", "any", "has", "have", "had", "per",
            "there", "here", "between", "during", "since", "until", "after", "before", "today", "yesterday", "tomorrow", "week", "month", "year", "days", "past", "last",
            "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
            "january", "february", "march", "april", "june", "july", "august", "september", "october", "november", "december"
        ]
        for term in domain_terms:
            custom_aliases[term] = term
            self.sym_spell.create_dictionary_entry(term, 100000)

        for alias, target in custom_aliases.items():
            self.sym_spell.create_dictionary_entry(alias, 1)
            self.sym_spell.create_dictionary_entry(target, 100000)
        self.custom_alias_map = custom_aliases

    def normalize(self, query: str) -> str:
        """
        Normalizes input text by correcting obvious typos while preserving numbers and SQL terms.
        """
        if not query or not query.strip():
            return ""

        words = query.strip().split()
        normalized_words = []

        for word in words:
            clean_word = word.strip(".,?!;:()\"'").lower()
            if clean_word in self.custom_alias_map:
                normalized_words.append(self.custom_alias_map[clean_word])
                continue

            import re
            # Preserve numbers, ordinals (1st, 2nd, 3rd, 18th), punctuation-heavy strings, and short words intact
            if not clean_word or clean_word.isdigit() or len(clean_word) <= 2 or re.match(r'^\d+(?:st|nd|rd|th)?$', clean_word):
                normalized_words.append(word)
                continue

            suggestions = self.sym_spell.lookup(
                clean_word, Verbosity.CLOSEST, max_edit_distance=config.SYMSPELL_MAX_EDIT_DISTANCE
            )

            if suggestions:
                best_suggestion = suggestions[0].term
                # Preserve original capitalization pattern if needed
                if word[0].isupper():
                    best_suggestion = best_suggestion.capitalize()
                normalized_words.append(best_suggestion)
            else:
                normalized_words.append(word)

        return " ".join(normalized_words)
