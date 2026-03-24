#!/usr/bin/env bash
set -e

echo "=============================================="
echo "  BNM Setup — Migrations + Seed"
echo "=============================================="

PYTHON=python3

# ── Attendre PostgreSQL ──────────────────────────
echo "Attente PostgreSQL..."
until $PYTHON - <<'PYEOF' 2>/dev/null
import psycopg2, os
psycopg2.connect(
    dbname=os.getenv('DB_NAME','postgres'),
    user=os.getenv('DB_USER','postgres'),
    password=os.getenv('DB_PASSWORD','bnm_password'),
    host=os.getenv('DB_HOST','postgres'),
    port=int(os.getenv('DB_PORT', 5432)))
print('OK')
PYEOF
do
    echo "  PostgreSQL pas encore prêt, nouvelle tentative dans 2s..."
    sleep 2
done
echo "✓ PostgreSQL connecté"

# ── Appliquer les migrations SQL ────────────────
echo "Application des migrations SQL..."
$PYTHON - <<'PYEOF'
import psycopg2, os, glob, re

conn = psycopg2.connect(
    dbname=os.getenv('DB_NAME','postgres'),
    user=os.getenv('DB_USER','postgres'),
    password=os.getenv('DB_PASSWORD','bnm_password'),
    host=os.getenv('DB_HOST','postgres'),
    port=int(os.getenv('DB_PORT', 5432)))
cur = conn.cursor()

# Extension pgvector (pour RAG)
cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

# Appliquer chaque fichier SQL dans l'ordre
sql_files = sorted(glob.glob('/app/migrations/*.sql'))
for path in sql_files:
    fname = os.path.basename(path)
    try:
        with open(path) as f:
            sql = f.read()
        # Ignorer les SELECT de vérification (migration 003)
        stmts = [s.strip() for s in sql.split(';') if s.strip()
                 and not re.match(r'\s*SELECT\b', s.strip(), re.I)]
        for stmt in stmts:
            cur.execute(stmt)
        print(f"  ✓ {fname}")
    except Exception as e:
        print(f"  ⚠ {fname} : {e} (ignoré — probablement déjà appliqué)")
        conn.rollback()
        continue
    conn.commit()

cur.close()
conn.close()
print("✓ Migrations terminées")
PYEOF

# ── Créer les comptes agents ─────────────────────
echo "Création des comptes agents..."
$PYTHON /app/seed/seed_all.py

echo "=============================================="
echo "  Setup terminé avec succès ✓"
echo "=============================================="
