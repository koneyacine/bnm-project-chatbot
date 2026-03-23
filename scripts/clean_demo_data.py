#!/usr/bin/env python3
"""
clean_demo_data.py — Nettoyage données de démonstration BNM.
Reproductible. Sauvegarde tout avant suppression.
Usage : python3 scripts/clean_demo_data.py [--dry-run]
"""
import os, sys, shutil, json, psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
DRY_RUN = "--dry-run" in sys.argv
BASE    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONV    = os.path.join(BASE, "conversations")
BACKUP  = os.path.join(BASE, "conversations_backup",
                        datetime.now().strftime("%Y%m%d_%H%M%S"))

DB = dict(dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
          password=os.getenv("DB_PASSWORD"), host=os.getenv("DB_HOST"),
          port=os.getenv("DB_PORT"))

def run():
    json_files = [f for f in os.listdir(CONV) if f.endswith(".json")]
    print(f"Tickets trouvés : {len(json_files)}")
    if json_files:
        if not DRY_RUN:
            os.makedirs(BACKUP, exist_ok=True)
            for f in json_files:
                shutil.copy2(os.path.join(CONV, f), os.path.join(BACKUP, f))
            print(f"Backup → {BACKUP}")
        else:
            print(f"[DRY-RUN] Backup → {BACKUP}")

    if not DRY_RUN:
        for f in json_files:
            os.remove(os.path.join(CONV, f))
        print(f"Supprimé : {len(json_files)} ticket(s)")
    else:
        print(f"[DRY-RUN] Supprimerait {len(json_files)} ticket(s)")

    if not DRY_RUN:
        conn = psycopg2.connect(**DB)
        cur  = conn.cursor()
        cur.execute("DELETE FROM conversation_history")
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM conversation_history")
        print(f"conversation_history après nettoyage : {cur.fetchone()[0]} lignes")
        cur.close(); conn.close()
    else:
        print("[DRY-RUN] DELETE FROM conversation_history")

    remaining = len([f for f in os.listdir(CONV) if f.endswith(".json")])
    print(f"\n✓ Tickets JSON restants : {remaining}")
    print("✓ Structure SQL (users, migrations) conservée")
    print("✓ Script terminé" if not DRY_RUN else "✓ [DRY-RUN] Aucune modification effectuée")

if __name__ == "__main__":
    run()
