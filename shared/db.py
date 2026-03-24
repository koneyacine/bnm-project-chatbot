"""
shared/db.py — Connexion PostgreSQL commune.
"""
import psycopg2
from shared.config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT


def get_connection():
    """Ouvre et retourne une nouvelle connexion psycopg2."""
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
    )
