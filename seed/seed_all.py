#!/usr/bin/env python3
"""
seed_all.py — Crée TOUS les comptes nécessaires (idempotent).
Usage : python seed/seed_all.py
        (ou appelé automatiquement par docker-entrypoint-setup.sh)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import psycopg2
import bcrypt

DB_PARAMS = dict(
    dbname=os.getenv("DB_NAME", "postgres"),
    user=os.getenv("DB_USER", "postgres"),
    password=os.getenv("DB_PASSWORD", "bnm_password"),
    host=os.getenv("DB_HOST", "localhost"),
    port=os.getenv("DB_PORT", "5432"),
)

ACCOUNTS = [
    # (username, email, password, role, agent_role)
    ("Jiddou",            "jiddou@bnm.local",  "admin123", "agent", "ADMIN"),
    ("agent_validation",  "val@bnm.mr",         "val123",   "agent", "VALIDATION"),
    ("agent_reclamation", "rec@bnm.mr",         "rec123",   "agent", "RECLAMATION"),
    ("agent_information", "info@bnm.mr",        "info123",  "agent", "INFORMATION"),
]


def make_hash(pwd: str) -> str:
    return bcrypt.hashpw(pwd.encode(), bcrypt.gensalt(12)).decode()


def main():
    print("=" * 55)
    print("  BNM Seed — Comptes agents (idempotent)")
    print("=" * 55)

    conn = psycopg2.connect(**DB_PARAMS)
    cur  = conn.cursor()

    for username, email, pwd, role, agent_role in ACCOUNTS:
        cur.execute(
            """
            INSERT INTO users (username, email, password_hash, role, agent_role)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (username) DO UPDATE
              SET agent_role    = EXCLUDED.agent_role,
                  password_hash = EXCLUDED.password_hash,
                  email         = EXCLUDED.email
            """,
            (username, email, make_hash(pwd), role, agent_role),
        )
        print(f"  ✓ {username:24s} ({agent_role})")

    conn.commit()
    cur.close()
    conn.close()

    print("=" * 55)
    print("  ⚠️  MOTS DE PASSE FAIBLES — DEV LOCAL UNIQUEMENT")
    print("=" * 55)


if __name__ == "__main__":
    main()
