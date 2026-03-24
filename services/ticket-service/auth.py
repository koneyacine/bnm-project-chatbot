"""
auth.py — Authentification BNM Chatbot
JWT + bcrypt — aucun credential en dur.
Tous les paramètres viennent de os.getenv() / .env
"""
import logging
import os
from datetime import datetime, timedelta

import bcrypt
import psycopg2
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

load_dotenv()

logger = logging.getLogger(__name__)

SECRET = os.getenv("JWT_SECRET_KEY", "")
ALGO   = os.getenv("JWT_ALGORITHM", "HS256")
EXP_H  = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

_DB_PARAMS = dict(
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
)


def _conn():
    return psycopg2.connect(**_DB_PARAMS)


# ── Hachage ────────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception as e:
        logger.warning("verify_password error: %s", e)
        return False


# ── Gestion utilisateurs ──────────────────────────────────────────────────────

def create_user(
    username: str,
    email: str,
    password: str,
    role: str = "client",
) -> dict:
    """Crée un utilisateur. Lève ValueError si username/email dupliqué."""
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(
            """
            INSERT INTO users (username, email, password_hash, role)
            VALUES (%s, %s, %s, %s)
            RETURNING user_id, username, email, role, created_at
            """,
            (username, email, hash_password(password), role),
        )
        row = cur.fetchone()
        c.commit()
        cur.close()
        c.close()
        return {
            "user_id":    str(row[0]),
            "username":   row[1],
            "email":      row[2],
            "role":       row[3],
            "created_at": row[4].isoformat(),
        }
    except psycopg2.errors.UniqueViolation:
        raise ValueError("username_or_email_taken")
    except Exception as e:
        if "unique" in str(e).lower():
            raise ValueError("username_or_email_taken")
        logger.error("create_user: %s", e)
        raise


def authenticate_user(username: str, password: str) -> dict | None:
    """Authentifie un utilisateur. Retourne le dict user ou None."""
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(
            """
            SELECT user_id, username, email, password_hash, role, agent_role
            FROM users
            WHERE username = %s
            """,
            (username,),
        )
        row = cur.fetchone()
        if not row or not verify_password(password, row[3]):
            cur.close()
            c.close()
            return None
        # Mettre à jour last_login
        cur.execute(
            "UPDATE users SET last_login = NOW() WHERE user_id = %s",
            (row[0],),
        )
        c.commit()
        cur.close()
        c.close()
        return {
            "user_id":    str(row[0]),
            "username":   row[1],
            "email":      row[2],
            "role":       row[4],
            "agent_role": row[5],
        }
    except Exception as e:
        logger.warning("authenticate_user: %s", e)
        return None


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(user_id: str, username: str, role: str, agent_role: str = None) -> str:
    payload = {
        "sub":        str(user_id),
        "username":   username,
        "role":       role,
        "agent_role": agent_role,
        "exp":        datetime.utcnow() + timedelta(hours=EXP_H),
    }
    return jwt.encode(payload, SECRET, algorithm=ALGO)


def verify_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGO])
    except JWTError:
        return None


# ── FastAPI Dependency ────────────────────────────────────────────────────────

_bearer = HTTPBearer()


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Dependency FastAPI — retourne le payload JWT ou lève HTTP 401."""
    payload = verify_token(creds.credentials)
    if not payload:
        raise HTTPException(
            status_code=401, detail="Token invalide ou expiré"
        )
    return payload
