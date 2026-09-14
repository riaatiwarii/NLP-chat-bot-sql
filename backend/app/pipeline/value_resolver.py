import json
import os
import rapidfuzz.fuzz as fuzz
import jellyfish
from sentence_transformers import SentenceTransformer, util
from app.config import config

class ValueResolver:
    """
    Stage 4: Value Resolution Cascade
    Runs 5-step resolution cascade for extracted entity spans:
    1. Exact Match against distinct DB column values.
    2. Alias Table Lookup (Canonical JSON on disk, cached in Redis).
    3. Fuzzy Match via rapidfuzz.
    4. Phonetic Match via jellyfish (Soundex & Metaphone).
    5. Embedding Similarity Fallback (sentence-transformers).

    If no step exceeds confidence threshold, marks entity as unresolved.
    """
    def __init__(self, distinct_db_values: dict = None, embedder: SentenceTransformer = None, redis_client = None):
        self.distinct_db_values = distinct_db_values or {} # e.g. {"Location": ["SBI Nariman Point", ...], ...}
        self.embedder = embedder
        self.redis_client = redis_client
        self.alias_table = self._load_alias_table()

    def _load_alias_table(self) -> dict:
        """
        Canonical Source of Truth Resolution:
        - Disk file `backend/app/data/alias_table.json` is the canonical source of truth.
        - If Redis is available, syncs canonical JSON into Redis cache.
        """
        alias_data = {}
        if os.path.exists(config.ALIAS_TABLE_PATH):
            try:
                with open(config.ALIAS_TABLE_PATH, "r", encoding="utf-8") as f:
                    alias_data = json.load(f)
            except Exception as e:
                print(f"[VALUE RESOLVER WARNING] Failed to read canonical alias_table.json: {e}")

        # Write-through to Redis cache if enabled and connected
        if self.redis_client:
            try:
                for alias_k, canonical_v in alias_data.items():
                    self.redis_client.set(f"alias:{alias_k.lower()}", canonical_v)
            except Exception as e:
                print(f"[VALUE RESOLVER WARNING] Redis sync failed, falling back to local dict: {e}")

        return alias_data

    def add_alias(self, alias_key: str, canonical_value: str):
        """
        Updates the canonical JSON file on disk immediately, and writes through to Redis.
        """
        alias_key_clean = alias_key.strip().lower()
        canonical_clean = canonical_value.strip()

        self.alias_table[alias_key_clean] = canonical_clean
        
        # Persist to disk
        try:
            os.makedirs(config.DATA_DIR, exist_ok=True)
            with open(config.ALIAS_TABLE_PATH, "w", encoding="utf-8") as f:
                json.dump(self.alias_table, f, indent=2)
        except Exception as e:
            print(f"[VALUE RESOLVER ERROR] Failed to save updated alias to JSON disk: {e}")

        # Update Redis cache
        if self.redis_client:
            try:
                self.redis_client.set(f"alias:{alias_key_clean}", canonical_clean)
            except Exception as e:
                print(f"[VALUE RESOLVER WARNING] Redis set failed: {e}")

    def resolve_entity(self, span_text: str, column_hint: str = None, entity_type: str = None) -> dict:
        """
        Executes the 5-step cascade for a single entity span text.
        For numeric_id entity spans, performs direct exact ID resolution.
        """
        text_raw = span_text.strip()
        text_lower = text_raw.lower()

        # STEP 0: Numeric ID direct exact-match resolution (bypass fuzzy/phonetic/embedding cascade)
        if entity_type == "numeric_id" or (text_raw.isdigit() and len(text_raw) >= 2):
            matched_col = column_hint if column_hint and column_hint in ["AlertID", "Id"] else "AlertID"
            return {
                "original_span": text_raw,
                "resolved_value": text_raw,
                "matched_column": matched_col,
                "resolution_step": "exact_numeric_id",
                "confidence": 1.0,
                "is_resolved": True
            }

        # Gather candidate values to match against
        all_candidates = []
        col_map = {}
        for col_name, val_list in self.distinct_db_values.items():
            for val in val_list:
                str_val = str(val)
                all_candidates.append(str_val)
                col_map[str_val] = col_name

        # STEP 1: Exact match against known distinct column values
        for candidate in all_candidates:
            if candidate.lower() == text_lower:
                return {
                    "original_span": text_raw,
                    "resolved_value": candidate,
                    "matched_column": col_map[candidate],
                    "resolution_step": "1_exact_db_match",
                    "confidence": 1.0,
                    "is_resolved": True
                }
            elif text_lower in candidate.lower() and len(text_lower) >= 4:
                return {
                    "original_span": text_raw,
                    "resolved_value": candidate,
                    "matched_column": col_map[candidate],
                    "resolution_step": "1_substring_db_match",
                    "confidence": 0.95,
                    "is_resolved": True
                }

        # STEP 2: Alias table lookup (Redis check first, fallback to canonical JSON)
        alias_match = None
        if self.redis_client:
            try:
                alias_bytes = self.redis_client.get(f"alias:{text_lower}")
                if alias_bytes:
                    alias_match = alias_bytes.decode("utf-8") if isinstance(alias_bytes, bytes) else str(alias_bytes)
            except Exception:
                alias_match = None

        if not alias_match:
            alias_match = self.alias_table.get(text_lower)

        if alias_match:
            # Map alias to DB column if possible
            matched_col = col_map.get(alias_match)
            return {
                "original_span": text_raw,
                "resolved_value": alias_match,
                "matched_column": matched_col,
                "resolution_step": "2_alias_lookup",
                "confidence": 0.98,
                "is_resolved": True
            }

        # STEP 3: Fuzzy match via rapidfuzz
        if len(text_raw) < 2:
            return {
                "original_span": text_raw,
                "resolved_value": None,
                "matched_column": None,
                "resolution_step": "unresolved_short_span",
                "confidence": 0.0,
                "is_resolved": False
            }

        best_fuzzy_score = 0.0
        best_fuzzy_cand = None
        for candidate in all_candidates:
            if len(candidate.strip()) <= 2 and text_lower != candidate.lower():
                continue
            score = fuzz.WRatio(text_lower, candidate.lower())
            if score > best_fuzzy_score:
                best_fuzzy_score = score
                best_fuzzy_cand = candidate

        if best_fuzzy_score >= config.VALUE_RESOLVER_FUZZY_THRESHOLD:
            return {
                "original_span": text_raw,
                "resolved_value": best_fuzzy_cand,
                "matched_column": col_map[best_fuzzy_cand],
                "resolution_step": "3_rapidfuzz_match",
                "confidence": best_fuzzy_score / 100.0,
                "is_resolved": True
            }

        # STEP 4: Phonetic match via jellyfish (Soundex & Metaphone)
        target_soundex = jellyfish.soundex(text_lower)
        target_metaphone = jellyfish.metaphone(text_lower)
        for candidate in all_candidates:
            cand_lower = candidate.lower()
            if jellyfish.soundex(cand_lower) == target_soundex or jellyfish.metaphone(cand_lower) == target_metaphone:
                return {
                    "original_span": text_raw,
                    "resolved_value": candidate,
                    "matched_column": col_map[candidate],
                    "resolution_step": "4_jellyfish_phonetic_match",
                    "confidence": 0.82,
                    "is_resolved": True
                }

        # STEP 5: Embedding similarity fallback
        if self.embedder and all_candidates:
            try:
                text_emb = self.embedder.encode(text_raw, convert_to_tensor=True)
                cand_embs = self.embedder.encode(all_candidates, convert_to_tensor=True)
                cosine_scores = util.cos_sim(text_emb, cand_embs)[0]
                best_idx = int(cosine_scores.argmax())
                best_emb_score = float(cosine_scores[best_idx])

                if best_emb_score >= config.VALUE_RESOLVER_EMBEDDING_THRESHOLD:
                    resolved_cand = all_candidates[best_idx]
                    return {
                        "original_span": text_raw,
                        "resolved_value": resolved_cand,
                        "matched_column": col_map[resolved_cand],
                        "resolution_step": "5_embedding_similarity_match",
                        "confidence": best_emb_score,
                        "is_resolved": True
                    }
            except Exception as e:
                print(f"[VALUE RESOLVER WARNING] Embedding step failed: {e}")

        # UNRESOLVED: Score falls below all confidence thresholds
        return {
            "original_span": text_raw,
            "resolved_value": None,
            "matched_column": None,
            "resolution_step": "unresolved_below_threshold",
            "confidence": 0.0,
            "is_resolved": False
        }
