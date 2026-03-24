"""
conversation_store.py — Persistance de l'historique conversationnel
BNM Chatbot — PostgreSQL + psycopg2
Aucun credential en dur — tout depuis os.getenv() / .env
"""
import json
import logging
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_DB_PARAMS = dict(
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
)


def _conn():
    return psycopg2.connect(**_DB_PARAMS)


# ── Écriture ──────────────────────────────────────────────────────────────────

def save_message(
    session_id: str,
    role: str,
    content: str,
    user_id: str = None,
    intent: str = None,
    meta: dict = None,
) -> None:
    """
    Insère un message dans conversation_history.
    Ne lève pas d'exception (ne doit pas crasher /ask).
    """
    if not session_id or not session_id.strip():
        logger.warning("save_message: session_id vide, ignoré (role=%s)", role)
        return
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(
            """
            INSERT INTO conversation_history
                (session_id, user_id, role, content, intent, meta)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                session_id,
                user_id or None,
                role,
                content,
                intent,
                json.dumps(meta, ensure_ascii=False) if meta else None,
            ),
        )
        c.commit()
        cur.close()
        c.close()
        logger.info("save_message OK: session=%s role=%s", session_id, role)
    except Exception as e:
        logger.error("save_message ERREUR: %s", e)


def link_session_to_user(session_id: str, user_id: str) -> None:
    """
    Lie tous les messages d'une session anonyme à un user_id.
    Utilisé quand un client s'identifie après avoir déjà chatté.
    """
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(
            """
            UPDATE conversation_history
               SET user_id = %s
             WHERE session_id = %s AND user_id IS NULL
            """,
            (user_id, session_id),
        )
        c.commit()
        cur.close()
        c.close()
    except Exception as e:
        logger.warning("link_session_to_user failed (non-fatal): %s", e)


# ── Lecture ───────────────────────────────────────────────────────────────────

def get_session_history(
    session_id: str, limit: int = 6
) -> list[dict]:
    """
    Retourne les N derniers messages d'une session,
    triés par timestamp ASC (ordre chronologique).
    Format : [{"role": "user|assistant|agent", "content": "...", "meta": {...}}]
    """
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(
            """
            SELECT role, content, timestamp, intent, meta
            FROM (
                SELECT role, content, timestamp, intent, meta
                FROM conversation_history
                WHERE session_id = %s
                ORDER BY timestamp DESC
                LIMIT %s
            ) sub
            ORDER BY timestamp ASC
            """,
            (session_id, limit),
        )
        rows = cur.fetchall()
        cur.close()
        c.close()
        return [
            {
                "role":      row[0],
                "content":   row[1],
                "timestamp": row[2].isoformat() if row[2] else None,
                "intent":    row[3],
                "meta":      row[4] if row[4] else None,
            }
            for row in rows
        ]
    except Exception as e:
        logger.warning("get_session_history failed: %s", e)
        return []


def get_user_conversations(user_id: str) -> list[dict]:
    """
    Retourne la liste des sessions pour un utilisateur,
    groupées par session_id avec métadonnées.
    """
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(
            """
            SELECT
                session_id,
                MIN(content)                               AS first_message,
                MAX(timestamp)                             AS last_activity,
                COUNT(*)                                   AS message_count
            FROM conversation_history
            WHERE user_id = %s
            GROUP BY session_id
            ORDER BY last_activity DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()
        cur.close()
        c.close()
        return [
            {
                "session_id":     row[0],
                "first_message":  (row[1] or "")[:80],
                "last_activity":  row[2].isoformat(),
                "message_count":  row[3],
            }
            for row in rows
        ]
    except Exception as e:
        logger.warning("get_user_conversations failed: %s", e)
        return []
