import json
import time
from app.config import config

class SessionMemory:
    """
    Stage 16: Session Memory
    Stores per-session multi-turn dialogue history (last 3-5 turns):
    {question, plan, SQL, result_summary, timestamp}.
    Uses Redis if available, with graceful fallback to an in-memory TTL dictionary.
    """
    def __init__(self, redis_client=None, max_turns: int = 5, ttl_seconds: int = 1800):
        self.redis_client = redis_client
        self.max_turns = max_turns
        self.ttl_seconds = ttl_seconds
        self.local_memory = {} # {session_id: {"turns": [...], "last_active": timestamp}}

    def add_turn(self, session_id: str, question: str, plan: dict, sql: str, result_summary: str):
        """
        Appends turn record to session history.
        """
        turn_data = {
            "question": question,
            "plan": plan,
            "sql": sql,
            "result_summary": result_summary,
            "timestamp": time.time()
        }

        # Redis storage if available
        if self.redis_client:
            try:
                key = f"session:{session_id}"
                existing_bytes = self.redis_client.get(key)
                turns = json.loads(existing_bytes) if existing_bytes else []
                turns.append(turn_data)
                turns = turns[-self.max_turns:]
                self.redis_client.setex(key, self.ttl_seconds, json.dumps(turns))
                return
            except Exception as e:
                print(f"[SESSION MEMORY WARNING] Redis push failed: {e}")

        # Local dict fallback
        self._cleanup_expired()
        session_entry = self.local_memory.get(session_id, {"turns": []})
        turns = session_entry["turns"]
        turns.append(turn_data)
        turns = turns[-self.max_turns:]
        self.local_memory[session_id] = {
            "turns": turns,
            "last_active": time.time()
        }

    def get_last_turn(self, session_id: str) -> dict:
        """
        Retrieves the most recent turn for a session.
        """
        turns = self.get_session_turns(session_id)
        return turns[-1] if turns else {}

    def get_session_turns(self, session_id: str) -> list[dict]:
        """
        Returns full turns list for a session.
        """
        if self.redis_client:
            try:
                key = f"session:{session_id}"
                existing_bytes = self.redis_client.get(key)
                if existing_bytes:
                    return json.loads(existing_bytes)
            except Exception:
                pass

        self._cleanup_expired()
        entry = self.local_memory.get(session_id)
        return entry["turns"] if entry else []

    def reset_session(self, session_id: str):
        """
        Clears session memory on explicit user reset.
        """
        if self.redis_client:
            try:
                self.redis_client.delete(f"session:{session_id}")
            except Exception:
                pass
        self.local_memory.pop(session_id, None)

    def _cleanup_expired(self):
        now = time.time()
        expired_keys = [
            sid for sid, data in self.local_memory.items()
            if now - data.get("last_active", 0) > self.ttl_seconds
        ]
        for sid in expired_keys:
            self.local_memory.pop(sid, None)
