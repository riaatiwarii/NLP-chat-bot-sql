import os
from symspellpy import SymSpell, Verbosity
from app.config import config

class InputNormalizer:
    """
    Stage 1: Input Normalization
    Uses SymSpell with a custom domain dictionary seeded with database table names,
    column names, and operational business terms to correct typos in raw query input.
    """
    def __init__(self, schema_terms: list[str] = None):
        self.sym_spell = SymSpell(
            max_dictionary_edit_distance=config.SYMSPELL_MAX_EDIT_DISTANCE,
            prefix_length=config.SYMSPELL_PREFIX_LENGTH
        )
        self._load_dictionary(schema_terms or [])

    def _load_dictionary(self, schema_terms: list[str]):
        dict_path = str(config.DICTIONARY_PATH)
        if os.path.exists(dict_path):
            try:
                self.sym_spell.load_dictionary(dict_path, term_index=0, count_index=1)
            except Exception as e:
                print(f"[INPUT NORMALIZER WARNING] Could not load dictionary file: {e}")

        # Seed in-memory with any dynamically provided database schema terms
        for term in schema_terms:
            clean_term = term.strip().lower()
            if clean_term and len(clean_term) > 2:
                self.sym_spell.create_dictionary_entry(clean_term, 10000)

    def normalize(self, query: str) -> str:
        """
        Normalizes input text by correcting obvious typos while preserving numbers and SQL terms.
        """
        if not query or not query.strip():
            return ""

        words = query.strip().split()
        normalized_words = []

        for word in words:
            # Preserve numbers, punctuation-heavy strings, and short words intact
            clean_word = word.strip(".,?!;:()\"'").lower()
            if not clean_word or clean_word.isdigit() or len(clean_word) <= 2:
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
