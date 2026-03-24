# BNM Chatbot — Assistant Bancaire Intelligent

Chatbot bancaire avec pipeline RAG, gestion de tickets,
back-office agent et architecture microservices.

---

## Démarrage rapide — Docker (recommandé)

### Prérequis

- Docker + Docker Compose installés
- Clé API OpenAI

### 3 commandes et c'est parti

```bash
# 1. Cloner le projet
git clone https://github.com/koneyacine/bnm-project-chatbot.git
cd bnm-project-chatbot
git checkout feature/bnm-chatbot-fullstack

# 2. Configurer (copier et renseigner OPENAI_API_KEY)
cp .env.example .env
# nano .env  →  OPENAI_API_KEY=sk-...

# 3. Lancer TOUT en une seule commande
docker-compose up --build
```

Les services démarrent en parallèle. Après ~60 secondes :

```
✓ postgres:     prêt (port 5433)
✓ setup:        migrations + seed des comptes
✓ auth-service: prêt (port 8001)
✓ chat-service: prêt (port 8002)
✓ ticket-service: prêt (port 8003)
✓ document-service: prêt (port 8004)
✓ admin-service: prêt (port 8005)
✓ gateway:      prêt (port 8000)
✓ frontend:     prêt (port 5175)
```

### Accès

| Interface       | URL                                        |
|-----------------|--------------------------------------------|
| Frontend client | http://localhost:5175                      |
| Back-office     | http://localhost:5175/backoffice           |
| Gateway API     | http://localhost:8000                      |
| PostgreSQL      | localhost:5433 (si besoin de connexion DB) |

### Comptes de démonstration

Ces comptes sont **créés automatiquement** au premier démarrage :

| Utilisateur        | Mot de passe | Rôle        |
|--------------------|--------------|-------------|
| Jiddou             | admin123     | ADMIN       |
| agent_validation   | val123       | VALIDATION  |
| agent_reclamation  | rec123       | RECLAMATION |
| agent_information  | info123      | INFORMATION |

> ⚠️ Ces motspasse faibles sont pour le DEV LOCAL UNIQUEMENT — ne jamais déployer en production.

### Arrêter les services

```bash
docker-compose down          # Arrêter les services
docker-compose down -v       # Arrêter + supprimer les volumes (WARNING: données perdues !)
```

### Recréer les comptes (si supprimés accidentellement)

```bash
docker-compose exec setup python3 /app/seed/seed_all.py
```

---

## Développement local (sans Docker)

Pour développer localement sans Docker :

### Prérequis

- Python 3.10+
- Node 20+
- PostgreSQL avec pgvector (port 5433)

### Installation

```bash
# 1. Configurer l'environnement
cp .env.example .env
# Éditer .env :
#   - OPENAI_API_KEY=sk-...
#   - DB_HOST=localhost
#   - DB_PORT=5433

# 2. Installer les dépendances Python
pip install -r requirements.txt

# 3. Recréer les comptes agents
python3 seed/seed_all.py

# 4. Démarrer les microservices
bash services/start_local.sh

# 5. Démarrer le frontend (dans un autre terminal)
cd ui
npm install
npm run dev -- --port 5175
```

Accès : http://localhost:5175

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Frontend React (port 5175)                         │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP :8000
┌──────────────────────▼──────────────────────────────┐
│  Gateway (port 8000) — reverse proxy                │
└──┬──────┬────────┬────────┬────────┬────────────────┘
   │      │        │        │        │
 8001   8002     8003     8004     8005
auth  chat    ticket  document  admin
  │      │        │        │        │
  └──────┴────────┴────────┴────────┘
                   │
         PostgreSQL + pgvector
         (port 5432, volume persistant)
```

### Services

| Service          | Port | Rôle                                  |
|------------------|------|---------------------------------------|
| postgres         | 5432 | Base de données + pgvector            |
| setup            | —    | Migration SQL + seed comptes (1 fois) |
| auth-service     | 8001 | Login, register, JWT                  |
| chat-service     | 8002 | RAG, pipeline OpenAI, historique      |
| ticket-service   | 8003 | CRUD tickets, workflow métier         |
| document-service | 8004 | Upload / download pièces jointes      |
| admin-service    | 8005 | Stats, tableaux de bord               |
| gateway          | 8000 | Reverse proxy vers les services       |
| frontend         | 5175 | React SPA (Vite + Tailwind)           |

---

## Développement local (sans Docker)

```bash
# Démarrer tous les microservices
bash services/start_local.sh

# Démarrer le frontend
cd ui && npm install && npm run dev -- --port 5175
```

Prérequis : Python 3.10+, Node 20+, PostgreSQL avec pgvector.

---

## Structure du projet

```
bnm-project-chatbot/
├── docker-compose.yml          # ← lancer avec docker-compose up
├── Dockerfile.setup            # migration + seed automatique
├── docker-entrypoint-setup.sh  # script d'initialisation
├── .env.example                # modèle de configuration
├── migrations/                 # SQL incrémental
├── seed/                       # scripts de création des comptes
├── services/
│   ├── gateway/                # reverse proxy httpx
│   ├── auth-service/           # authentification JWT
│   ├── chat-service/           # RAG + conversation
│   ├── ticket-service/         # gestion des tickets
│   ├── document-service/       # pièces jointes
│   └── admin-service/          # statistiques
├── ui/                         # frontend React
│   ├── Dockerfile              # build + nginx
│   └── nginx.conf              # SPA routing
├── conversations/              # tickets JSON (volume Docker)
└── uploads/                    # fichiers uploadés (volume Docker)
```
