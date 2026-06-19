# session_store.py
# Store déterministe des documents validés par session.
# Indépendant du LLM — seul Python écrit ici, après validation de format.

import json
import time
import threading
from typing import Optional


class InMemorySessionStore:
    """
    Store en mémoire avec TTL.
    Thread-safe via Lock.
    Structure : { session_id: { "docs": set, "values": dict, "ts": float } }

    ⚠️ ATTENTION : ce store ne fonctionne correctement que si l'app tourne
    avec UN SEUL worker/process. Avec plusieurs workers (--workers N > 1),
    chaque worker a sa propre mémoire et ne voit pas les écritures des autres
    → utiliser RedisSessionStore à la place.
    """
    def __init__(self, ttl_seconds: int = 3600):
        self._data: dict = {}
        self._ttl        = ttl_seconds
        self._lock       = threading.Lock()

    def _is_expired(self, entry: dict) -> bool:
        return (time.time() - entry["ts"]) > self._ttl

    def _get_entry(self, session_id: str) -> Optional[dict]:
        entry = self._data.get(session_id)
        if entry is None or self._is_expired(entry):
            return None
        return entry

    def get_docs(self, session_id: str) -> set:
        with self._lock:
            entry = self._get_entry(session_id)
            if entry:
                entry["ts"] = time.time()   # refresh TTL à la lecture
            return set(entry["docs"]) if entry else set()

    def get_value(self, session_id: str, key: str):
        with self._lock:
            entry = self._get_entry(session_id)
            if entry:
                entry["ts"] = time.time()
            return entry["values"].get(key) if entry else None

    def add_doc(self, session_id: str, doc_key: str, value=True):
        """
        N'écrit la valeur QUE si le doc n'est pas déjà présent.
        La première valeur validée par Python est définitive pour la session.
        """
        with self._lock:
            entry = self._data.get(session_id)
            if entry is None or self._is_expired(entry):
                self._data[session_id] = {"docs": set(), "values": {}, "ts": time.time()}
                entry = self._data[session_id]

            if doc_key not in entry["docs"]:
                entry["docs"].add(doc_key)
                entry["values"][doc_key] = value

            entry["ts"] = time.time()

    def clear(self, session_id: str):
        with self._lock:
            self._data.pop(session_id, None)

    def cleanup_expired(self):
        with self._lock:
            expired = [sid for sid, e in self._data.items() if self._is_expired(e)]
            for sid in expired:
                del self._data[sid]

    def debug_dump(self, session_id: str) -> dict:
        """Utilitaire de debug : affiche l'état brut d'une session."""
        with self._lock:
            entry = self._data.get(session_id)
            return dict(entry) if entry else {}


class RedisSessionStore:
    """
    Même interface qu'InMemorySessionStore mais persisté dans Redis.
    Fonctionne avec N workers / N process — partagé via Redis.
    Nécessite : pip install redis
    """
    def __init__(self, redis_url: str = "redis://localhost:6379", ttl_seconds: int = 3600):
        import redis
        self._r   = redis.from_url(redis_url, decode_responses=True)
        self._ttl = ttl_seconds

    def _key(self, session_id: str) -> str:
        return f"yasmine:validation:{session_id}"

    def _load(self, session_id: str) -> dict:
        raw = self._r.get(self._key(session_id))
        if not raw:
            return {"docs": [], "values": {}}
        return json.loads(raw)

    def _save(self, session_id: str, data: dict):
        self._r.setex(self._key(session_id), self._ttl, json.dumps(data))

    def get_docs(self, session_id: str) -> set:
        data = self._load(session_id)
        if data["docs"]:
            self._save(session_id, data)   # refresh TTL
        return set(data["docs"])

    def get_value(self, session_id: str, key: str):
        data = self._load(session_id)
        if data["docs"]:
            self._save(session_id, data)   # refresh TTL
        return data["values"].get(key)

    def add_doc(self, session_id: str, doc_key: str, value=True):
        data = self._load(session_id)
        if doc_key not in data["docs"]:
            data["docs"].append(doc_key)
            data["values"][doc_key] = value
        self._save(session_id, data)

    def clear(self, session_id: str):
        self._r.delete(self._key(session_id))

    def cleanup_expired(self):
        pass  # Redis gère l'expiration automatiquement via setex

    def debug_dump(self, session_id: str) -> dict:
        return self._load(session_id)


# ── Instance globale ──────────────────────────────────────────────
session_store = InMemorySessionStore(ttl_seconds=3600)


# ── Cleanup automatique en arrière-plan (InMemory uniquement) ─────
def _start_cleanup_thread(store: InMemorySessionStore, interval_seconds: int = 1800):
    def _loop():
        while True:
            time.sleep(interval_seconds)
            store.cleanup_expired()
    t = threading.Thread(target=_loop, daemon=True)
    t.start()

if isinstance(session_store, InMemorySessionStore):
    _start_cleanup_thread(session_store)