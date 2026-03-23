# GUIDE DE DÉMONSTRATION — BNM Chatbot Bancaire

**Version :** 2.0 (Phase 2 — Intelligence + UX)
**Date :** 2026-03-16
**Stack :** FastAPI (port 8011) + React (Vite) + PostgreSQL + OpenAI GPT-4o Mini

---

## Démarrage rapide

### 1. Démarrer le backend

```bash
cd /Users/pro/Downloads/BNM/local-ai-packaged/bnm-project-chatbot
/opt/anaconda3/bin/python3 -m uvicorn api_server:app --host 0.0.0.0 --port 8011 --reload
```

Vérification :

```bash
curl -s http://localhost:8011/tickets | python3 -c "import sys,json; t=json.load(sys.stdin); print(f'OK — {len(t)} ticket(s)')"
```

### 2. Démarrer le frontend

```bash
cd /Users/pro/Downloads/BNM/local-ai-packaged/bnm-project-chatbot/ui
export PATH="/Users/pro/.nvm/versions/node/v22.21.1/bin:$PATH"
npm run dev
```

Accès : `http://localhost:5173`

---

## Architecture de l'interface

L'interface est organisée en **3 colonnes** :

| Colonne | Contenu |
| --- | --- |
| Gauche (300px) | Chat client — saisie, historique, scénarios rapides |
| Centre (flexible) | Analyse & Routage — classification, confiance, routage, réponse RAG |
| Droite (300px) | Back-Office — liste tickets, stats, filtres, actions |

---

## Scénarios de démonstration

### Scenario 1 — Réponse directe (Information)

**Question :** "Qu'est-ce que e-BNM et comment puis-je l'activer ?"

**Comportement attendu :**
- Classification : `INFORMATION` / Confiance : `HIGH`
- Canal : `CHATBOT` (bloc vert dans la colonne Analyse)
- Réponse RAG basée sur le document `EBNM_VERSION 01.docx`
- Aucun ticket créé

**Ce que montre ce scénario :** le pipeline RAG complet avec injection documentaire.

---

### Scenario 2 — Réclamation (Transfert Back-Office)

**Question :** "Je n'ai pas reçu ma carte MasterCard commandée il y a 3 semaines."

**Comportement attendu :**
- Classification : `RECLAMATION` / Confiance : `HIGH`
- Canal : `BACKOFFICE` (bloc orange) avec priorité `HIGH`
- Ticket créé (`BNM-YYYYMMDD_HHMMSS`) visible dans la colonne Back-Office
- Toast info "Ticket BNM-xxx créé et transmis au back-office"
- Badge ticket dans la bulle du bot

**Ce que montre ce scénario :** le routage automatique vers le back-office.

---

### Scenario 3 — Validation (Transfert Back-Office)

**Question :** "Je souhaite confirmer ma demande d'ouverture de compte courant entreprise."

**Comportement attendu :**
- Classification : `VALIDATION` / Confiance : `HIGH`
- Canal : `BACKOFFICE` / Priorité : `NORMAL`
- Ticket créé et visible

**Ce que montre ce scénario :** les demandes de validation sont toujours routées vers un agent humain.

---

### Scenario 4 — Fallback RAG (Transfert automatique)

**Question :** "Quel est le taux de change EUR/MRU aujourd'hui ?"

**Comportement attendu :**
- Classification : `INFORMATION`
- Canal initialement `CHATBOT`, puis basculé `BACKOFFICE` (fallback automatique)
- `fallback_reason: "RAG insuffisant"` affiché dans l'analyse
- Message de fallback crédible : *"Je n'ai pas trouvé de réponse précise…"*

**Ce que montre ce scénario :** la détection automatique des réponses RAG insuffisantes.

---

### Scenario 5 — Patterns conversationnels

Séquence de test :

```
"Bonjour"           → ⚡ Direct (pattern: salutation)
"Qui es-tu ?"       → ⚡ Direct (pattern: identite_bot)
"Merci"             → ⚡ Direct (pattern: remerciement)
"Oui, tout à fait"  → ⚡ Direct (pattern: confirmation)
"Non merci"         → ⚡ Direct (pattern: remerciement/negation)
"Au revoir"         → ⚡ Direct (pattern: au_revoir)
```

**Ce que montre ce scénario :** les court-circuits conversationnels sans appel OpenAI.

---

### Scenario 6 — Mode Démo

1. Cliquer sur **🎬 Mode Démo** dans le header
2. Sélectionner un scénario dans le panneau flottant
3. L'input du chat est pré-rempli — modifier si souhaité, puis Entrée pour envoyer

---

### Scenario 7 — Authentification

1. Cliquer sur **Connexion** (header droite)
2. Se connecter avec `Jiddou` / `1234` (compte dev local uniquement)
3. Le placeholder du chat devient *"Bonjour Jiddou, posez votre question…"*
4. Un toast "Bienvenue, Jiddou !" apparaît
5. La session anonyme est automatiquement liée à l'utilisateur (`POST /sessions/{id}/link`)
6. L'initiale "J" s'affiche dans le cercle orange du header

---

### Scenario 8 — Cycle de vie d'un ticket (Back-Office)

1. Envoyer une réclamation → ticket `BNM-xxx` créé (état `NOUVEAU`)
2. Dans la colonne Back-Office, cliquer sur le ticket → modal s'ouvre
3. **Onglet Actions** :
   - Renseigner un nom d'agent → "Prendre en charge" → état `EN_COURS`
   - Cliquer "Valider" → saisir une note → état `VALIDE`
   - Le `client_message` est généré automatiquement par GPT-4o Mini
4. Envoyer un nouveau message dans le chat avec la même session → le bot retourne directement la décision BNM
5. Badge **✅ Décision BNM** s'affiche sur la bulle

---

## Endpoints API disponibles

### Chat & Sessions

```bash
POST /ask                                 # Question → classification + RAG + routage
GET  /history/{session_id}               # Historique conversationnel
GET  /tickets/by-session/{session_id}    # Ticket actif pour une session
POST /sessions/{session_id}/link         # Lier session → user (JWT requis)
```

### Tickets — Lecture

```bash
GET  /tickets                            # Liste (filtres: state, priority, intent)
GET  /tickets/{id}                       # Détail d'un ticket
GET  /stats/tickets                      # Stats agrégées
```

### Tickets — Actions

```bash
POST /tickets/{id}/assign                # Prendre en charge
POST /tickets/{id}/reply                 # Répondre au client
POST /tickets/{id}/validate              # Valider → VALIDE
POST /tickets/{id}/reject                # Rejeter → REJETE
POST /tickets/{id}/request-complement    # Demander complément → COMPLEMENT_REQUIS
POST /tickets/{id}/ask-client            # Question client → EN_ATTENTE_CLIENT
POST /tickets/{id}/add-comment           # Commentaire interne ou visible
POST /tickets/{id}/set-priority          # Changer priorité
POST /tickets/{id}/client-response       # Enregistrer réponse client
POST /tickets/{id}/close                 # Clôturer
```

### Auth

```bash
POST /auth/register                      # Créer un compte
POST /auth/login                         # Connexion → JWT
GET  /auth/me                            # Infos utilisateur connecté (JWT)
POST /auth/logout                        # Déconnexion (blacklist token)
```

### Documents

```bash
POST /tickets/{id}/documents             # Upload document
GET  /tickets/{id}/documents             # Lister documents
GET  /tickets/{id}/documents/{doc_id}    # Télécharger document
```

---

## Machine d'états des tickets

```
NOUVEAU
  ├── EN_COURS (assign / reply)
  └── CLOTURE

EN_COURS
  ├── VALIDE (validate)
  ├── REJETE (reject)
  ├── COMPLEMENT_REQUIS (request-complement)
  ├── EN_ATTENTE_CLIENT (ask-client)
  └── CLOTURE

COMPLEMENT_REQUIS → EN_COURS (client répond)
EN_ATTENTE_CLIENT → EN_COURS (client répond)
VALIDE            → CLOTURE
REJETE            → CLOTURE
CLOTURE           → (terminal)
```

---

## Compte de développement

> **ATTENTION — USAGE LOCAL UNIQUEMENT**

| Champ | Valeur |
| --- | --- |
| Username | `Jiddou` |
| Email | `jiddou@bnm.local` |
| Password | `1234` |
| Role | `client` |

Ce compte doit être supprimé avant tout déploiement :

```sql
DELETE FROM users WHERE username = 'Jiddou';
```

---

## Logs et debug

```bash
# Backend logs en temps réel
tail -f /tmp/bnm_backend.log

# Tester un pattern conversationnel
curl -s -X POST http://localhost:8011/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"Bonjour","session_id":"test_demo"}' | python3 -m json.tool

# Voir les stats
curl -s http://localhost:8011/stats/tickets | python3 -m json.tool

# Vérifier l'historique d'une session
curl -s http://localhost:8011/history/test_demo | python3 -m json.tool
```

---

## Points clés à démontrer

1. **Routage intelligent** — classification LLM en 3 intents + règles métier
2. **Fallback automatique** — détection réponse RAG insuffisante (<60 chars ou patterns)
3. **Mémoire contextuelle** — historique injecté dans le prompt RAG (window 6 messages)
4. **Mémoire métier** — retour décision back-office directement dans le chat
5. **Patterns conversationnels** — 6 patterns sans appel OpenAI (latence < 100ms)
6. **Mode Démo** — 5 scénarios prédéfinis pour présentation
7. **Toast system** — feedback visuel pour toutes les actions
8. **Auth JWT** — connexion + liaison session anonyme
9. **Back-office complet** — cycle de vie tickets, stats temps réel, documents

---

*Guide généré le 2026-03-16 — BNM Chatbot Bancaire v2.0*
