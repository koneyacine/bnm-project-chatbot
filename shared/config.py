"""
shared/config.py — Variables de configuration centralisées BNM Chatbot.
Importé par chaque microservice.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Base de données ────────────────────────────────────────────────────────────
DB_NAME     = os.getenv("DB_NAME")
DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = os.getenv("DB_PORT", "5433")

# ── OpenAI ─────────────────────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL      = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
EMBED_MODEL    = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-ada-002")

# ── JWT ────────────────────────────────────────────────────────────────────────
JWT_SECRET    = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXP_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

# ── Chemins données partagées ──────────────────────────────────────────────────
BNM_DATA_DIR      = os.getenv("BNM_DATA_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
CONVERSATIONS_DIR = os.path.join(BNM_DATA_DIR, "conversations")
UPLOADS_DIR       = os.path.join(BNM_DATA_DIR, "uploads")

# ── URLs inter-services ────────────────────────────────────────────────────────
AUTH_SERVICE_URL     = os.getenv("AUTH_SERVICE_URL",     "http://localhost:8001")
CHAT_SERVICE_URL     = os.getenv("CHAT_SERVICE_URL",     "http://localhost:8002")
TICKET_SERVICE_URL   = os.getenv("TICKET_SERVICE_URL",   "http://localhost:8003")
DOCUMENT_SERVICE_URL = os.getenv("DOCUMENT_SERVICE_URL", "http://localhost:8004")
ADMIN_SERVICE_URL    = os.getenv("ADMIN_SERVICE_URL",    "http://localhost:8005")
