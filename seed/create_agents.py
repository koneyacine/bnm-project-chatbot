#!/usr/bin/env python3
"""SEED AGENTS — DEV LOCAL UNIQUEMENT. Mots de passe FAIBLES."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import psycopg2
from auth import hash_password

DB_PARAMS = dict(
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
)

agents = [
    ("agent_validation",  "val@bnm.mr",       "val123",  "agent", "VALIDATION"),
    ("agent_reclamation", "rec@bnm.mr",        "rec123",  "agent", "RECLAMATION"),
    ("agent_information", "info@bnm.mr",       "info123", "agent", "INFORMATION"),
]

conn = psycopg2.connect(**DB_PARAMS)
cur = conn.cursor()

for username, email, pwd, role, agent_role in agents:
    try:
        cur.execute(
            """INSERT INTO users (username, email, password_hash, role, agent_role)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (username) DO UPDATE SET agent_role = EXCLUDED.agent_role""",
            (username, email, hash_password(pwd), role, agent_role),
        )
        print(f"OK {username} ({agent_role})")
    except Exception as e:
        print(f"ERREUR {username}: {e}")

# Mettre a jour Jiddou si existant
cur.execute(
    "UPDATE users SET agent_role = 'ADMIN' WHERE username = 'Jiddou'",
)
conn.commit()
cur.close()
conn.close()
print("AVERTISSEMENT: MOTS DE PASSE FAIBLES — DEV LOCAL UNIQUEMENT")
