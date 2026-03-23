#!/usr/bin/env python3
"""
SEED LOCAL UNIQUEMENT — NE PAS DÉPLOYER EN PRODUCTION.

Ce script crée un compte de développement avec un mot de passe faible.
Le mot de passe '1234' est INTERDIT en production.

Usage : python seed/create_seed_user.py
         (à exécuter une seule fois, manuellement)

AVERTISSEMENT SÉCURITÉ :
  - Ce fichier ne doit JAMAIS être exécuté en production.
  - Ne pas versionner ce fichier dans un dépôt public.
  - Supprimer ou désactiver ce compte avant tout déploiement.
"""
import sys
import os

# Permet l'import depuis la racine du projet
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from dotenv import load_dotenv
load_dotenv()

from auth import create_user  # noqa: E402

# ── SEED LOCAL UNIQUEMENT — NE PAS DÉPLOYER EN PRODUCTION ──────────────────
SEED_USERNAME = "Jiddou"
SEED_EMAIL    = "jiddou@bnm.local"
SEED_PASSWORD = "1234"   # MOT DE PASSE FAIBLE — DEV LOCAL UNIQUEMENT
SEED_ROLE     = "agent"
# ───────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("⚠️  SEED LOCAL UNIQUEMENT — NE PAS DÉPLOYER EN PRODUCTION")
    print("=" * 60)
    print(f"   Compte : {SEED_USERNAME} / {SEED_EMAIL}")
    print(f"   Rôle   : {SEED_ROLE}")
    print(f"   ⚠️  Mot de passe faible ('{SEED_PASSWORD}') — DEV ONLY")
    print("=" * 60)

    try:
        user = create_user(
            username=SEED_USERNAME,
            email=SEED_EMAIL,
            password=SEED_PASSWORD,
            role=SEED_ROLE,
        )
        print(f"✓ Compte seed créé : {user['username']} (id={user['user_id']})")
        print("⚠️  Supprimer ce compte avant tout déploiement en production !")
    except ValueError:
        print(f"— Compte '{SEED_USERNAME}' existe déjà.")
    except Exception as e:
        print(f"✗ Erreur : {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
