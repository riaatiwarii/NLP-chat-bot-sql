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

    def _normalize_matched_col(self, col: str) -> str:
        if not col:
            return col
        c_low = col.lower()
        if c_low in ["area", "location"]:
            return "Branch"
        if c_low in ["zone", "lho"]:
            return "LHOCircle"
        return col

    def resolve_entity(self, span_text: str, column_hint: str = None, entity_type: str = None) -> dict:
        """
        Executes the 5-step cascade for a single entity span text.
        For numeric_id entity spans, performs direct exact ID resolution.
        """
        text_raw = str(span_text or "").strip()
        text_lower = text_raw.lower()

        if not text_raw:
            return {
                "original_span": span_text,
                "resolved_value": None,
                "matched_column": None,
                "resolution_step": "unresolved_empty",
                "confidence": 0.0,
                "is_resolved": False
            }

        # MONTH NAMES WHITELIST: Whitelist all month names and date tokens (do not fail entity matching)
        month_names = {
            "january", "february", "march", "april", "may", "june", "july", "august",
            "september", "october", "november", "december", "jan", "feb", "mar", "apr",
            "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"
        }
        if text_lower in month_names:
            return {
                "original_span": text_raw,
                "resolved_value": None,
                "matched_column": None,
                "resolution_step": "date_month_token",
                "confidence": 1.0,
                "is_resolved": True
            }

        # STRUCTURAL / INTENT BLACKLIST: Never resolve structural words as DB entities
        structural_blacklist = {
            "breakdown", "summary", "distribution", "list", "show", "count",
            "highest", "lowest", "least", "most", "total", "alerts", "alert", "which",
            "what", "how", "many", "much", "type", "types", "subtype", "subtypes", "alerttype", "alerttypes",
            "status", "severity", "sensor", "sensors",
            "branch", "branches", "lho", "lhos", "zone", "zones", "area", "areas",
            "by", "their", "wise", "between", "from", "to", "during", "recent", "latest"
        }
        if text_lower in structural_blacklist:
            return {
                "original_span": text_raw,
                "resolved_value": None,
                "matched_column": None,
                "resolution_step": "unresolved_structural_keyword",
                "confidence": 1.0,
                "is_resolved": True
            }

        # STEP 0: Numeric ID direct exact-match resolution
        is_year = text_raw.isdigit() and len(text_raw) == 4 and 1900 <= int(text_raw) <= 2100
        if (entity_type == "numeric_id" or (text_raw.isdigit() and len(text_raw) >= 2)) and not (is_year and column_hint != "AlertID"):
            matched_col = column_hint if column_hint and column_hint in ["AlertID", "Id"] else "AlertID"
            print(f"[VALUE RESOLVER] Resolved numeric ID: {text_raw} -> column: {matched_col}", flush=True)
            return {
                "original_span": text_raw,
                "resolved_value": text_raw,
                "matched_column": matched_col,
                "resolution_step": "exact_numeric_id",
                "confidence": 1.0,
                "is_resolved": True
            }

        # STEP 0.5: Canonical Severity & Status Mapping Rules
        if text_lower in ["high", "high severe", "high severity"]:
            return {
                "original_span": text_raw,
                "resolved_value": "High",
                "matched_column": "Severity",
                "resolution_step": "0_canonical_severity",
                "confidence": 1.0,
                "is_resolved": True
            }
        if text_lower in ["low"]:
            return {
                "original_span": text_raw,
                "resolved_value": "Low",
                "matched_column": "Severity",
                "resolution_step": "0_canonical_severity",
                "confidence": 1.0,
                "is_resolved": True
            }
        if text_lower in ["medium"]:
            return {
                "original_span": text_raw,
                "resolved_value": "Medium",
                "matched_column": "Severity",
                "resolution_step": "0_canonical_severity",
                "confidence": 1.0,
                "is_resolved": True
            }
        # CRITICAL maps to High (DB has only High, Medium, Low)
        if text_lower in ["critical", "crit", "severe"]:
            return {
                "original_span": text_raw,
                "resolved_value": "High",
                "matched_column": "Severity",
                "resolution_step": "0_canonical_severity",
                "confidence": 1.0,
                "is_resolved": True
            }
        if text_lower in ["pending", "closed", "acknowledged", "unresolved", "open", "resolved"]:
            res_val = "Pending" if text_lower in ["unresolved", "open"] else ("Closed" if text_lower == "resolved" else text_raw.capitalize())
            return {
                "original_span": text_raw,
                "resolved_value": res_val,
                "matched_column": "Status",
                "resolution_step": "0_canonical_status",
                "confidence": 1.0,
                "is_resolved": True
            }

        # Canonical AlertSubtype Mapping
        alert_subtype_map = {
            "motion": "Motion",
            "activity detection": "Activity Detection",
            "device alert": "Device Alert",
            "recording alert": "Recording Alert",
            "device reboot": "Device Reboot",
            "tamper": "Tamper",
            "tampering": "Tamper",
            "glass break": "Glass Break",
            "glass-break": "Glass Break",
            "panic": "Panic",
            "shutter": "Shutter",
            "two way": "Two Way",
            "two-way": "Two Way",
            "pir": "PIR",
            "vibration": "Vibration",
            "smoke": "Smoke",
            "fire": "Fire",
            "burglary": "Burglary"
        }
        if text_lower in alert_subtype_map:
            return {
                "original_span": text_raw,
                "resolved_value": alert_subtype_map[text_lower],
                "matched_column": "AlertSubtype",
                "resolution_step": "0_canonical_alert_subtype",
                "confidence": 1.0,
                "is_resolved": True
            }

        # Canonical AlertType Mapping
        alert_type_map = {
            "vms": "VMS",
            "analytics": "Analytics",
            "cctv": "CCTV",
            "atm": "ATM",
            "intrusion": "Intrusion",
            "dvr": "DVR",
            "nvr": "NVR"
        }
        if text_lower in alert_type_map or entity_type == "alert_type":
            canon_type = alert_type_map.get(text_lower, text_raw.upper() if len(text_raw) <= 4 else text_raw.title())
            return {
                "original_span": text_raw,
                "resolved_value": canon_type,
                "matched_column": "AlertType",
                "resolution_step": "0_canonical_alert_type",
                "confidence": 1.0,
                "is_resolved": True
            }

        # Gather candidate values to match against
        all_candidates = []
        col_map = {}
        for col_name, val_list in self.distinct_db_values.items():
            norm_c = self._normalize_matched_col(col_name)
            for val in val_list:
                str_val = str(val)
                all_candidates.append(str_val)
                col_map[str_val] = norm_c

        # STEP 1: Exact match against known distinct column values
        for candidate in all_candidates:
            if candidate.lower() == text_lower:
                return {
                    "original_span": text_raw,
                    "resolved_value": candidate,
                    "matched_column": self._normalize_matched_col(col_map[candidate]),
                    "resolution_step": "1_exact_db_match",
                    "confidence": 1.0,
                    "is_resolved": True
                }
            elif text_lower in candidate.lower() and len(text_lower) >= 4:
                return {
                    "original_span": text_raw,
                    "resolved_value": candidate,
                    "matched_column": self._normalize_matched_col(col_map[candidate]),
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
            if not matched_col:
                if alias_match.startswith("AO_") or any(k in alias_match.lower() for k in ["agra", "noida", "kanpur", "branch"]):
                    matched_col = "Branch"
                elif any(k in alias_match.lower() for k in ["circle", "new delhi", "delhi", "lho"]):
                    matched_col = "LHOCircle"
                else:
                    matched_col = "Branch"
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
