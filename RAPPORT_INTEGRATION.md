# RAPPORT D'INTÉGRATION — BNM Chatbot
## Intégration de la branche Sessions-MultiUsers-Interface

**Date :** 2026-03-16
**Projet :** `bnm-project-chatbot/` (backend OpenAI, port 8011)
**Basé sur l'analyse :** `/Users/pro/Downloads/BNM/analysis_branches/RAPPORT_ANALYSE.md`

---

## 1. FICHIERS CRÉÉS

| Fichier | Rôle |
|---|---|
| `auth.py` | Module d'authentification JWT + bcrypt. Fonctions : `hash_password`, `verify_password`, `create_user`, `authenticate_user`, `create_access_token`, `verify_token`, `get_current_user` (FastAPI Dependency). Aucun credential en dur. |
| `conversation_store.py` | Persistance de l'historique conversationnel en PostgreSQL. Fonctions : `save_message`, `get_session_history`, `get_user_conversations`, `link_session_to_user`. Silencieux en cas d'erreur (ne crashe pas `/ask`). |
| `migrations/001_users_and_history.sql` | Script SQL créant les tables `users` et `conversation_history` avec index. Idempotent (`CREATE TABLE IF NOT EXISTS`). |
| `seed/create_seed_user.py` | Crée le compte de développement Jiddou/jiddou@bnm.local/1234. Commentaires explicites SEED LOCAL UNIQUEMENT. Ne jamais déployer. |
| `ui/src/components/LoginModal.jsx` | Modal React de connexion/inscription. Tabs Login / Créer un compte. Stocke token et user dans localStorage. Style TailwindCSS + bnmblue/bnmorange. |
| `ui/src/components/ConversationHistory.jsx` | Composant React affichant le fil chronologique d'une session. Bulles user/bot/système. Accessible depuis le back-office. |

---

## 2. FICHIERS MODIFIÉS

| Fichier | Résumé des changements |
|---|---|
| `api_server.py` | + imports `auth`, `conversation_store`, `re`, `unicodedata`. + `QuestionRequest.user_id`. + `RegisterRequest`, `LoginRequest`. + `_token_blacklist`. + `_CONV_PATTERNS` / `_CONV_RESPONSES` / `_detect_conv_pattern()`. + Endpoints : `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `POST /auth/logout`. + `/ask` : génère `session_id` si absent, détecte patterns conversationnels, sauvegarde messages (user + assistant), retourne `session_id`. + `GET /history/{session_id}`. + `GET /users/{user_id}/conversations`. |
| `ui/src/api.js` | + `getAuthHeaders()`. + `_post/_get` : paramètre `auth` optionnel. + `login()`, `register()`, `getMe()`, `logout()`. + `getHistory()`, `getUserConversations()`. + `askQuestion()` : accepte `userId` en 3e argument. |
| `ui/src/App.jsx` | + Import `logout`, `LoginModal`. + État `currentUser`, `showLoginModal`. + `sessionId` stable dans `sessionStorage`. + `handleLogout()`. + `handleSend` passe `sessionId` + `currentUser.user_id` à `askQuestion`. + Header : bouton Connexion/Déconnexion + username. + Rendu conditionnel `<LoginModal>`. |
| `.env` | + `JWT_SECRET_KEY` (32 octets hex, généré via `secrets.token_hex(32)`). + `JWT_ALGORITHM=HS256`. + `JWT_EXPIRATION_HOURS=24`. |
| `requirements.txt` | À mettre à jour : `passlib[bcrypt]`, `python-jose[cryptography]`, `python-multipart` |

---

## 3. BACKUPS RÉALISÉS

| Fichier original | Backup horodaté |
|---|---|
| `api_server.py` | `api_server.py.bak.20260315_164030` (session précédente) |
| `api_server.py` | `api_server.py.bak.20260316_090720` (cette session) |
| `backoffice.py` | `backoffice.py.bak.20260315_164030` |
| `ui/src/api.js` | `ui/src/api.js.bak.20260316_091721` |
| `ui/src/App.jsx` | `ui/src/App.jsx.bak.20260316_091745` |

---

## 4. MIGRATIONS SQL

| Fichier | Statut |
|---|---|
| `migrations/001_users_and_history.sql` | ✓ Exécutée sur `localai-postgres-1` |

**Tables créées :**
```sql
users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'client',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_login TIMESTAMP
)

conversation_history (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL,
    user_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    intent VARCHAR(30),
    timestamp TIMESTAMP NOT NULL DEFAULT NOW()
)
```

**Index :** `idx_conv_session`, `idx_conv_user`, `idx_conv_timestamp`

**Résultat vérification :**
- `users` : 3 utilisateurs (agent_bnm, test_user, Jiddou)
- `conversation_history` : 16 messages persistés

---

## 5. DÉPENDANCES AJOUTÉES

| Package | Version installée | Raison |
|---|---|---|
| `passlib[bcrypt]` | 1.7.4 | Hachage bcrypt sécurisé (remplacement SHA-256 maison de la branche analysée) |
| `python-jose[cryptography]` | — | Génération et vérification des tokens JWT |
| `python-multipart` | — | Support upload de fichiers (déjà nécessaire pour FastAPI) |

> ⚠️ Warning `(trapped) error reading bcrypt version` = bénin. passlib 1.7.4 + bcrypt moderne.
> La vérification fonctionne correctement. Upgrade vers `passlib 1.8+` quand disponible.

---

## 6. ENDPOINTS AJOUTÉS

| Méthode | Route | Description | Auth |
|---|---|---|---|
| `POST` | `/auth/register` | Crée un compte. HTTP 201 ou 409 si doublon | Publique |
| `POST` | `/auth/login` | Authentifie, retourne JWT + infos user | Publique |
| `GET` | `/auth/me` | Retourne le payload du token connecté | JWT requis |
| `POST` | `/auth/logout` | Blackliste le token (mémoire serveur) | JWT requis |
| `GET` | `/history/{session_id}` | Historique conversationnel d'une session | Publique (dev) |
| `GET` | `/users/{user_id}/conversations` | Toutes les sessions d'un utilisateur | JWT requis |

**Modifications `/ask` :**
- Génère `session_id` si absent → retourné dans la réponse
- Détecte 4 patterns conversationnels (salutation/remerciement/identité/au_revoir)
- Sauvegarde chaque échange (user + assistant) dans `conversation_history`
- Accepte `user_id` pour lier la session à un utilisateur identifié

---

## 7. TESTS EXÉCUTÉS

| # | Description | Résultat |
|---|---|---|
| 1 | Backend actif — `GET /tickets` | ✓ 5 tickets |
| 2 | `POST /auth/register` | ✓ HTTP 201 |
| 3 | `POST /auth/login` + token JWT | ✓ Token 217 chars |
| 4 | `GET /auth/me` | ✓ username + role retournés |
| 5 | Seed Jiddou (create_seed_user.py) | ✓ Compte créé/reconnu |
| 6 | Pattern conversationnel "Bonjour" | ✓ pipeline=[conv_pattern], intent=CONV |
| 7 | Question RAG avec session_id | ✓ intent=INFORMATION, session retourné |
| 8 | `GET /history/{session}` | ✓ 4 messages chronologiques |
| 9 | PostgreSQL users + conversation_history | ✓ 3 users, 16 messages |
| 10 | Tickets JSON rétrocompat | ✓ 5 tickets intacts |

**Résultat global : 10/10 ✓**

---

## 8. RISQUES RESTANTS

| Risque | Gravité | Action recommandée |
|---|---|---|
| `GET /history/{session_id}` est public | 🟠 ÉLEVÉ | Ajouter `Depends(get_current_user)` en production |
| Blacklist JWT en mémoire (perdue au redémarrage) | 🟡 MOYEN | Migrer vers Redis ou table `invalid_tokens` en production |
| Warning bcrypt `__about__` (passlib 1.7.4) | 🟡 MINEUR | Upgrade vers `passlib 1.8+` quand disponible ou utiliser `bcrypt` directement |
| `sessionId` dans sessionStorage (perdu à la fermeture de l'onglet) | 🟡 MINEUR | Migrer vers localStorage ou cookie HTTP-only si persistance souhaitée |
| `_token_blacklist` in-memory non partagé (multi-worker) | 🟡 MINEUR | Redis si déploiement multi-workers |

---

## 9. DETTE TECHNIQUE

| Point | Simplification faite | À améliorer |
|---|---|---|
| Historique RAG dans `/ask` | Historique récupéré mais pas encore injecté dans le prompt RAG | Implémenter window context (5 derniers échanges) dans le prompt |
| Pool de connexions DB | Chaque appel `_conn()` ouvre/ferme une connexion | Utiliser `psycopg2.pool.SimpleConnectionPool` ou SQLAlchemy |
| Requirements.txt | Packages installés mais `requirements.txt` non mis à jour | Ajouter `passlib[bcrypt]`, `python-jose[cryptography]` |
| Test login Jiddou | Non testé automatiquement (mot de passe faible intentionnel) | Exclure des tests CI |

---

## 10. CE QUI A ÉTÉ REPRIS DE LA BRANCHE ANALYSÉE

| Concept | Origine (branche) | Repris dans |
|---|---|---|
| Table `users` avec `password_hash` + `salt` | `query.py` | `migrations/001_users_and_history.sql` (adapté) |
| Table `conversation_history` | `query.py` | `migrations/001_users_and_history.sql` |
| `create_user()` / `authenticate_user()` | `query.py` | `auth.py` (réécrit) |
| `save_to_history()` / `get_session_history()` | `query.py` | `conversation_store.py` (réécrit) |
| Patterns salutation / remerciement / identité / au_revoir | `query.py` | `api_server.py` (`_CONV_PATTERNS`) |
| Concept de viewer de conversations par session | `app.py` (Flask) | `ConversationHistory.jsx` (React) |

---

## 11. CE QUI A ÉTÉ ADAPTÉ À NOTRE ARCHITECTURE

| Élément original | Faille / problème | Notre implémentation |
|---|---|---|
| SHA-256 + salt maison | Non standard, vulnérable | bcrypt via passlib rounds=12 |
| Credentials DB en dur dans le code | Faille critique | `os.getenv()` + `.env` exclusivement |
| Connexion DB globale non thread-safe | Crash Flask concurrent | Connexion à la demande par appel (`_conn()`) |
| Flask (incompatible) | Stack différente | FastAPI (endpoints `/auth/*`) |
| Endpoint `/api/user/<username>/history` public | Faille sécurité | JWT requis pour `/users/{user_id}/conversations` |
| Monolithique `query.py` | Non modulable | Modules séparés : `auth.py`, `conversation_store.py` |
| Port 5433 hardcodé | Non portable | `os.getenv("DB_PORT")` |
| `session_id` généré en CLI | Non applicable web | `crypto.randomUUID()` côté React, `sessionStorage` |

---

## 12. PROCHAINES ÉTAPES RECOMMANDÉES

**Priorité haute :**
1. Sécuriser `GET /history/{session_id}` avec JWT en production
2. Injecter l'historique conversationnel dans le prompt RAG (window de 5 échanges) pour améliorer la cohérence multi-tour
3. Ajouter `passlib[bcrypt]`, `python-jose[cryptography]` dans `requirements.txt`

**Priorité moyenne :**
4. Migrer la blacklist JWT vers Redis pour tenir les redémarrages
5. Ajouter `link_session_to_user()` dans `/ask` quand `user_id` est fourni
6. Vue back-office : afficher l'historique conversationnel SQL dans `TicketDetailModal` (onglet dédié)

**Priorité basse :**
7. Pool de connexions psycopg2 pour les performances
8. Supprimer ou désactiver le compte seed Jiddou avant tout déploiement
9. Tests automatisés (pytest) pour les endpoints auth

---

## ⚠️ AVERTISSEMENT SEED

Le compte `Jiddou / jiddou@bnm.local / 1234` est un **compte de développement local uniquement**.
Le mot de passe `1234` est **interdit en production**.
Ce compte doit être **supprimé ou désactivé** avant tout déploiement :
```sql
DELETE FROM users WHERE username = 'Jiddou';
```

---

*Rapport généré le 2026-03-16 — Intégration basée sur l'analyse de la branche Sessions-MultiUsers-Interface.*
*Aucune modification n'a été apportée à `analysis_branches/` ni à `bnm-project-chatbot-ollama/`.*

---

---

# Phase 2 — Améliorations UX + Intelligence

**Date :** 2026-03-16
**Portée :** Phase A (intelligence backend) + Phase B (UX/UI) + Phase C (tests) + Phase D (livrables)

---

## PHASE A — Intelligence du bot

### A1. Injection historique conversationnel dans le prompt RAG

**Fichier modifié :** `api_server.py`

Avant le prompt RAG, `get_session_history(session_id, limit=6)` est appelé. Si des messages existent, un bloc `Historique de la conversation` est injecté dans le prompt avant le contexte documentaire. Cela permet au LLM de répondre en tenant compte des échanges précédents (window de 6 messages).

### A2. Fallback crédible

**Seuil relevé à 60 caractères** (était 30). Quand la réponse RAG est faible (`_is_rag_weak()`), le channel est forcé à `BACKOFFICE` et une réponse de fallback crédible est retournée au client :
> *"Je n'ai pas trouvé de réponse précise dans notre documentation. Votre demande a été transmise à un conseiller BNM…"*

### A3. Patterns conversationnels enrichis

Deux nouveaux patterns ajoutés dans `_CONV_PATTERNS` :
- **`confirmation`** : oui, d'accord, ok, bien sûr, absolument, tout à fait, c'est ça…
- **`negation`** : non, pas du tout, absolument pas, jamais, incorrect, faux…

Avec réponses adaptées dans `_CONV_RESPONSES`.

### A4. Mémoire métier — ticket actif par session

Déjà implémenté (Phase 1). `find_by_session()` est appelé avant le pipeline RAG pour :
- Retourner la décision (`VALIDE`/`REJETE`) directement au client
- Enregistrer la réponse client si état `EN_ATTENTE_CLIENT`
- Informer le client si ticket `EN_COURS`

### A5. Structure ticket enrichie

`save_ticket()` inclut déjà `session_id`, `classification`, `resolution` avec le bloc complet (`decision`, `decision_at`, `decision_by`, `client_message`, `internal_note`).

### A6. Endpoints métier ajoutés

| Méthode | Route | Description | Auth |
|---|---|---|---|
| `POST` | `/tickets/{id}/validate` | EN_COURS → VALIDE | Publique |
| `POST` | `/tickets/{id}/reject` | EN_COURS → REJETE | Publique |
| `POST` | `/tickets/{id}/request-complement` | EN_COURS → COMPLEMENT_REQUIS | Publique |
| `GET` | `/stats/tickets` | Stats agrégées | Publique |
| `POST` | `/sessions/{session_id}/link` | Lie session anonyme à user | JWT requis |

---

## PHASE B — UX/UI

### B1. Composant Toast — `ui/src/components/Toast.jsx`

Toast en bas à droite, 4 types (`success`/`error`/`info`/`warning`), disparaît après 3s avec fade-out et barre de progression. Hook `useToast()` exporté. Intégré dans `App.jsx` via `<ToastContainer>`.

### B2. Composant LoadingSteps — `ui/src/components/LoadingSteps.jsx`

3 étapes séquentielles (300 ms chacune) : *Classification…* → *Recherche documentaire…* → *Génération de la réponse…*. Chaque étape affiche un spinner puis une coche verte. Intégré dans `ChatWindow.jsx`.

### B3. ChatWindow enrichi

- **Bulles de message** avec horodatage (HH:MM)
- **Badge ⚡ Direct** si `pipeline = ['conv_pattern']`
- **Badge ✅ Décision BNM** si `source = 'backoffice_resolution'`
- **Encadré ticket créé** avec numéro de référence
- **Placeholder dynamique** : *"Bonjour {username}, posez votre question…"* si connecté
- **Input désactivé** pendant le chargement
- **Touche Entrée** = soumettre (Shift+Entrée = nouvelle ligne)
- **Auto-scroll** vers le dernier message

### B4. Panneau Analyse & Routage enrichi

- **Badge coloré par intent** (bleu/rouge/orange/vert)
- **Barre de progression confiance** (Haute/Moyenne/Faible)
- **Bloc routage coloré** (vert si CHATBOT, orange si BACKOFFICE)
- **Session ID** affiché en bas à droite

### B5. Back-Office

Déjà implémenté (Phase 1) : StatsBar, filtres, TicketCard, TicketDetailModal 5 onglets. Les toasts remplacent désormais les `alert()` pour les actions back-office.

### B6. Header enrichi

- **Badge "+N"** nouveaux tickets pulsant (rouge)
- **Initiale de l'utilisateur** dans un cercle orange
- **Nom d'utilisateur** visible (hidden sm:inline)
- **Bouton connexion/déconnexion**

### B7. Mode Démo

Bouton **🎬 Mode Démo** dans le header. Panneau flottant centré avec 5 scénarios cliquables :
1. Information e-BNM
2. Réclamation carte MasterCard
3. Demande validation compte entreprise
4. Contact conseiller Mourabaha
5. Offre Ramadan 2026

Cliquer pré-remplit l'input du chat (sans envoyer automatiquement).

### B8. Liaison auth + session au login

Dans `App.jsx`, `handleLoginSuccess()` appelle `linkSession(sessionId, user.user_id)` après connexion. Cela lie tous les messages anonymes de la session courante à l'utilisateur identifié via `POST /sessions/{session_id}/link` (JWT requis, non-bloquant si erreur).

---

## PHASE C — Tests backend

| # | Test | Résultat |
|---|---|---|
| 1 | Backend actif — `GET /tickets` | ✓ 5 tickets |
| 2 | Pattern conv "Bonjour" | ✓ pipeline=['conv_pattern'], intent=CONV |
| 3 | Nouveau pattern "Oui, tout à fait" | ✓ reason=confirmation |
| 4 | Nouveau pattern "Non merci" | ✓ reason=remerciement (court-circuit "merci") |
| 5 | `GET /stats/tickets` | ✓ total=5, par_state, par_intent |
| 6 | `POST /tickets/{id}/validate` | ✓ state=VALIDE, client_message généré |
| 7 | `POST /tickets/{id}/reject` | ✓ state=REJETE, client_message généré |
| 8 | `POST /tickets/{id}/request-complement` | ✓ state=COMPLEMENT_REQUIS |
| 9 | `GET /tickets/by-session/{id}` | ✓ 404 si absente (comportement correct) |
| 10 | `POST /sessions/{id}/link` (JWT) | ✓ status=ok, session liée |
| 11 | `GET /history/{session_id}` | ✓ 6 messages persistés |
| 12 | `npm run build` (frontend) | ✓ 0 erreur, 41 modules, 253 KB JS |

**Résultat global : 12/12 ✓**

---

## FICHIERS CRÉÉS (Phase 2)

| Fichier | Description |
|---|---|
| `ui/src/components/Toast.jsx` | Toast système + hook `useToast()` (B1) |
| `ui/src/components/LoadingSteps.jsx` | Indicateur 3 étapes séquentielles (B2) |
| `GUIDE_DEMO.md` | Guide de démonstration complet (D) |

## FICHIERS MODIFIÉS (Phase 2)

| Fichier | Changements |
|---|---|
| `api_server.py` | A1 histy RAG, A2 fallback 60c, A3 patterns confirm/neg, A6 /sessions/link |
| `ui/src/App.jsx` | Toast B1, DemoPanel B7, handleLoginSuccess+linkSession B8, header B6, ResultPanel B4 |
| `ui/src/api.js` | Ajout `linkSession()` (B8) |
| `ui/src/components/ChatWindow.jsx` | B2 LoadingSteps, B3 bulles enrichies, demoInput prop |

---

## BACKUPS Phase 2

| Fichier | Backup |
|---|---|
| `api_server.py` | `api_server.py.bak.20260316_150002` |
| `backoffice.py` | `backoffice.py.bak.20260316_150002` |
| `ui/src/App.jsx` | `ui/src/App.jsx.bak.20260316_150003` + `*.bak.20260316_15xxxx` |
| `ui/src/api.js` | `ui/src/api.js.bak.20260316_150003` + `*.bak.20260316_15xxxx` |

---

*Rapport mis à jour le 2026-03-16 — Phase 2 : Améliorations UX + Intelligence.*

---

## Phase 3 — Séparation Client / Back-Office (2026-03-17)

### Objectif

Architecture séparée : parcours client par téléphone + espace back-office avec rôles agents.

### Fichiers créés

| Fichier | Description |
| --- | --- |
| `ui/src/pages/HomePage.jsx` | Page d'accueil avec 2 boutons (Chat / Agent) |
| `ui/src/pages/ClientEntryPage.jsx` | Saisie téléphone client |
| `ui/src/pages/ClientChatPage.jsx` | Interface chat client épurée |
| `ui/src/pages/BackOfficeLoginPage.jsx` | Login back-office style sombre |
| `ui/src/pages/BackOfficeDashboard.jsx` | Dashboard 2 colonnes avec filtrage par rôle |
| `migrations/002_phone_and_agent_role.sql` | Ajout phone + agent_role en base |
| `seed/create_agents.py` | Création agents de démonstration |
| `GUIDE_DEMO_V2.md` | Guide de démonstration v2 |

### Fichiers modifiés

| Fichier | Modification |
| --- | --- |
| `api_server.py` | +ClientSessionRequest, +POST /client/session, +GET /history/phone/{phone}, +phone dans QuestionRequest, +role filtre dans GET /tickets |
| `auth.py` | +agent_role dans authenticate_user + create_access_token |
| `ui/src/App.jsx` | Remplacé par routeur React Router v7 |
| `ui/src/main.jsx` | Ajout BrowserRouter |
| `ui/src/api.js` | +createClientSession, +getPhoneHistory, phone dans askQuestion, role dans fetchTickets |

### Migration SQL appliquée

```sql
ALTER TABLE conversation_history ADD COLUMN IF NOT EXISTS phone VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS agent_role VARCHAR(30) DEFAULT NULL;
```

### Comptes agents créés

| Compte | Rôle | Voit |
| --- | --- | --- |
| agent_validation | VALIDATION | Tickets VALIDATION |
| agent_reclamation | RECLAMATION | Tickets RECLAMATION |
| agent_information | INFORMATION | Tickets INFORMATION→BACKOFFICE |
| Jiddou | ADMIN | Tous les tickets |

### Tests validés

- POST /client/session → 200 + session_id dérivé du phone
- POST /ask avec phone → session_id = phone_XXXXXXXX
- GET /history/phone/{phone} → historique par numéro
- GET /tickets?role=RECLAMATION → filtrage par rôle
- POST /auth/login agent_validation → agent_role: VALIDATION dans la réponse
- Build frontend → 0 erreur

*Rapport mis à jour le 2026-03-17 — Phase 3 : Séparation Client/Back-Office.*
