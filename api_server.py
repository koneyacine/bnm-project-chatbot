"""
API FastAPI — BNM Chatbot back-office v2.

Usage :
  uvicorn api_server:app --port 8011 --reload
"""
import json
import os
import re
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Optional

import openai
import psycopg2
from auth import (
    authenticate_user,
    create_access_token,
    create_user,
    get_current_user,
)
from conversation_store import (
    get_session_history,
    get_user_conversations,
    save_message,
)
from backoffice import (
    UPLOADS_DIR,
    add_comment,
    ask_client,
    assign_ticket,
    client_responds,
    close_ticket,
    find_by_session,
    load_ticket,
    reject_ticket,
    reopen_ticket,
    reply_ticket,
    request_complement,
    return_to_bot,
    save_ticket,
    set_priority,
    ticket_stats,
    validate_ticket,
)
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import BaseModel
from router import route

load_dotenv()

app = FastAPI(title="BNM Chatbot API (OpenAI) v2", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Init DB + modèles ─────────────────────────────────────────────────────────
_DB_PARAMS = dict(
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
)
conn = psycopg2.connect(**_DB_PARAMS)


def get_conn():
    global conn
    try:
        conn.cursor().execute("SELECT 1")
    except Exception:
        conn = psycopg2.connect(**_DB_PARAMS)
    return conn


embeddings = OpenAIEmbeddings(
    model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-ada-002"),
)
llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
)

CLASSIFIER_SYSTEM = (
    "Tu es un classificateur bancaire. Analyse la demande client "
    "et réponds UNIQUEMENT en JSON valide avec ce format exact :\n"
    '{"intent": "INFORMATION" | "RECLAMATION" | "VALIDATION", '
    '"confidence": "HIGH" | "MEDIUM" | "LOW", '
    '"reason": "explication courte en français (max 10 mots)"}\n'
    "Ne réponds rien d'autre que ce JSON."
)

_FALLBACK_PATTERNS = (
    "je ne sais pas",
    "je ne dispose pas",
    "cette information n'est pas",
    "n'est pas mentionné",
    "n'est pas fourni",
    "pas dans le contexte",
    "pas dans les documents",
    "aucune information",
    "je n'ai pas cette information",
    "non disponible",
    "i don't know",
    "don't know",
    "ne contient pas d'information",
    "ne contient pas cette information",
    "ne mentionne pas",
    "pas d'information",
    "pas mentionné dans",
    "n'est pas dans le contexte",
    "context provided does not",
    "not mentioned in",
)


# ── Pydantic models ───────────────────────────────────────────────────────────

class QuestionRequest(BaseModel):
    question:   str
    session_id: Optional[str] = None
    user_id:    Optional[str] = None
    phone:      Optional[str] = None


class ClientSessionRequest(BaseModel):
    phone: str


class AssignBody(BaseModel):
    agent: str


class ReplyBody(BaseModel):
    agent: str
    message: str


class ComplementBody(BaseModel):
    message: str
    agent: Optional[str] = "agent"


class ValidateBody(BaseModel):
    note: Optional[str] = ""
    agent: Optional[str] = "agent"


class RejectBody(BaseModel):
    reason: str
    agent: Optional[str] = "agent"


class AskClientBody(BaseModel):
    question: str
    agent: Optional[str] = "agent"


class CommentBody(BaseModel):
    comment: str
    visible_to_client: Optional[bool] = False
    agent: Optional[str] = "agent"


class PriorityBody(BaseModel):
    priority: str


class ClientResponseBody(BaseModel):
    message: str


class RegisterRequest(BaseModel):
    username: str
    email:    str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


# ── Auth state ────────────────────────────────────────────────────────────────

_token_blacklist: set = set()
_auth_bearer = HTTPBearer()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_rag_weak(rag_response: str) -> bool:
    """Retourne True si la réponse RAG est trop faible pour être utile (A2)."""
    if not rag_response or len(rag_response.strip()) < 60:
        return True
    lower = rag_response.lower()
    return any(p in lower for p in _FALLBACK_PATTERNS)


def _llm_invoke_with_retry(prompt, max_retries: int = 1):
    for attempt in range(max_retries + 1):
        try:
            return llm.invoke(prompt)
        except openai.RateLimitError:
            if attempt < max_retries:
                time.sleep(5)
            else:
                raise


def _normalize_ticket(t: dict) -> dict:
    """Assure les defaults rétrocompat pour l'affichage frontend."""
    t.setdefault("state", t.get("status", "NOUVEAU"))
    t.setdefault("history", [])
    t.setdefault("fallback_reason", None)
    t.setdefault("messages", [])
    t.setdefault("documents", [])
    t.setdefault("resolution", {
        "decision": None, "decision_at": None,
        "decision_by": None, "client_message": None,
        "internal_note": None,
    })
    return t


# ── Patterns conversationnels ─────────────────────────────────────────────────

_CONV_PATTERNS: dict[str, list[str]] = {
    # ── Priorité haute : produits BNM spécifiques (avant les patterns génériques) ──
    "compte_click": [
        r"(?i)^\s*click\s*$",  # réponse "Click" seul après clarification
        r"\b(compte\s*click|click\s*wallet|wallet\s*click"
        r"|valider\s*click|validation\s*click|ouvrir\s*click"
        r"|activer\s*click|v[eé]rifier\s*click|service\s*click"
        r"|mon\s*click|bnm\s*click)\b",
    ],
    "compte_ambigue": [
        r"\b(valider\s*mon\s*compte|validation\s*de\s*compte"
        r"|confirmer\s*mon\s*compte|ouvrir\s*un\s*compte"
        r"|activer\s*mon\s*compte|v[eé]rifier\s*mon\s*compte)\b",
    ],
    # ── Patterns conversationnels génériques ──────────────────────────────────────
    "salutation": [
        r"\b(bonjour|bonsoir|salut|hello|salam|مرحبا|السلام)\b",
    ],
    "remerciement": [
        r"\b(merci|thank(?:\s+you)?|thanks|شكرا|mرسي)\b",
    ],
    "identite_bot": [
        r"\b(qui\s+es.?tu|c.?est\s+quoi|ton\s+nom|vous\s+êtes\s+qui"
        r"|quel\s+est\s+ton\s+nom|peux.?tu\s+te\s+pr[eé]senter"
        r"|pr[eé]sente.?toi|qui\s+es-tu)\b",
    ],
    "au_revoir": [
        r"\b(au\s+revoir|bye|goodbye|bonne\s+journ[eé]e|[àa]\s+bient[oô]t"
        r"|bonne\s+soir[eé]e)\b",
    ],
    "confirmation": [
        r"\b(oui|yes|d.?accord|ok|bien\s+s[uû]r|absolument|exactement"
        r"|tout\s+[àa]\s+fait|affirmatif|c.?est\s+[çc]a|correct)\b",
    ],
    "negation": [
        r"\b(non|no|pas\s+du\s+tout|absolument\s+pas|jamais|n[eé]gatif"
        r"|ce\s+n.?est\s+pas|incorrect|faux)\b",
    ],
}

_CONV_RESPONSES: dict[str, str] = {
    "salutation": (
        "Bonjour ! Je suis l'assistant virtuel de la BNM. "
        "Comment puis-je vous aider ?"
    ),
    "remerciement": (
        "Je vous en prie ! N'hésitez pas si vous avez d'autres questions."
    ),
    "identite_bot": (
        "Je suis l'assistant virtuel de la Banque Nationale de Mauritanie (BNM). "
        "Je peux vous aider sur nos produits, services et réclamations."
    ),
    "au_revoir": (
        "Au revoir ! Bonne journée et à bientôt sur BNM."
    ),
    "confirmation": (
        "Parfait ! Je prends note de votre confirmation. "
        "Souhaitez-vous que je transmette votre demande à notre équipe ?"
    ),
    "negation": (
        "Bien entendu. N'hésitez pas à me préciser votre demande "
        "ou à poser une autre question."
    ),
    "compte_click": (
        "Bienvenue au service client BNM Click ! 🔵\n\n"
        "Pour vérifier et valider votre compte Click, "
        "veuillez préparer les documents suivants :\n\n"
        "📄 Documents requis :\n"
        "- Copie de votre Carte Nationale d'Identité (recto)\n"
        "- Une photo d'identité récente (non retouchée)\n\n"
        "📸 Envoyez ces documents à notre équipe via ce chat. "
        "Un agent vous contactera sous peu pour finaliser "
        "la validation de votre compte Click.\n\n"
        "Référence service : BNM Click Wallet"
    ),
    "compte_ambigue": (
        "Je vais vous aider avec votre demande de compte.\n\n"
        "Quel type de compte souhaitez-vous valider ?\n\n"
        "🔵 Compte Click — Wallet numérique BNM\n"
        "🏦 Compte Bancaire — Compte courant ou épargne\n\n"
        "Répondez \"Click\" ou \"Compte bancaire\" pour continuer."
    ),
}


def _normalize_str(text: str) -> str:
    """Supprime les accents et met en minuscule pour la détection."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
    )


def _detect_conv_pattern(question: str) -> str | None:
    """Retourne le nom du pattern conversationnel détecté, ou None."""
    q = _normalize_str(question)
    for intent, patterns in _CONV_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, q, re.IGNORECASE):
                return intent
    return None


# ── Auth endpoints ────────────────────────────────────────────────────────────

@app.post("/auth/register", status_code=201)
def auth_register(body: RegisterRequest):
    """Crée un nouveau compte utilisateur."""
    try:
        return create_user(body.username, body.email, body.password)
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail="Nom d'utilisateur ou email déjà utilisé",
        )


@app.post("/auth/login")
def auth_login(body: LoginRequest):
    """Authentifie un utilisateur et retourne un token JWT."""
    user = authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(
            status_code=401, detail="Identifiants incorrects"
        )
    token = create_access_token(
        user["user_id"], user["username"], user["role"],
        agent_role=user.get("agent_role")
    )
    return {"access_token": token, "token_type": "bearer", "user": user}


@app.get("/auth/me")
def auth_me(u=Depends(get_current_user)):
    """Retourne les informations de l'utilisateur connecté."""
    return u


@app.post("/auth/logout")
def auth_logout(
    creds: HTTPAuthorizationCredentials = Depends(_auth_bearer),
):
    """Blackliste le token (logout côté serveur en mémoire)."""
    _token_blacklist.add(creds.credentials)
    return {"message": "Déconnecté"}


# ── POST /ask ─────────────────────────────────────────────────────────────────

@app.post("/client/session")
def create_client_session(body: ClientSessionRequest):
    phone_clean = re.sub(r'\D', '', body.phone)
    if len(phone_clean) < 8:
        raise HTTPException(400, "Numéro invalide")
    session_id = f"phone_{phone_clean}"
    return {"phone": phone_clean, "session_id": session_id, "message": "Session créée"}


@app.get("/history/phone/{phone}")
def get_phone_history(phone: str):
    phone_clean = re.sub(r'\D', '', phone)
    session_id = f"phone_{phone_clean}"
    return get_session_history(session_id, limit=20)


@app.post("/ask")
def ask(req: QuestionRequest):
    question   = req.question
    user_id    = req.user_id or None
    # Générer session_id si absent
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    # Si phone fourni et session_id vide, dériver session_id du phone
    if req.phone and not req.session_id:
        phone_clean = re.sub(r'\D', '', req.phone)
        session_id = f"phone_{phone_clean}"

    # ── Sauvegarder la question client (historique persistant) ────────────
    save_message(session_id, "user", question, user_id=user_id)

    # ── Détection patterns conversationnels (court-circuit rapide) ────────
    conv_match = _detect_conv_pattern(question)

    # Cas spécial compte_click : crée un ticket VALIDATION automatiquement
    if conv_match == "compte_click":
        response_text = _CONV_RESPONSES["compte_click"]
        save_message(session_id, "assistant", response_text,
                     user_id=user_id, intent="VALIDATION")
        # Vérifier un ticket actif existant pour éviter les doublons
        existing = find_by_session(session_id) if session_id else None
        click_ticket_id = None
        if existing and existing.get("state") not in ("VALIDE", "REJETE", "CLOTURE"):
            click_ticket_id = existing.get("ticket_id")
        else:
            from backoffice import pick_agent_for_role, _intent_to_role as _i2r
            _assigned_role  = "VALIDATION"
            _assigned_agent = pick_agent_for_role(_assigned_role, _DB_PARAMS)
            click_ticket_id, _ = save_ticket(
                question=question,
                intent="VALIDATION",
                confidence="HIGH",
                reason_classification="Demande validation compte Click",
                rag_response=response_text,
                routing_reason="Pattern compte Click — ticket auto",
                priority="NORMAL",
                fallback_reason=None,
                session_id=session_id,
                sources=[],
                assigned_role=_assigned_role,
                assigned_agent=_assigned_agent,
            )
        return {
            "question":       question,
            "classification": {
                "intent":     "VALIDATION",
                "confidence": "HIGH",
                "reason":     "Demande validation compte Click",
                "source":     "pattern",
            },
            "routing": {
                "channel":  "BACKOFFICE",
                "reason":   "Pattern compte Click — ticket auto",
                "priority": "NORMAL",
            },
            "rag_response":  response_text,
            "sources":       [],
            "ticket_id":     click_ticket_id,
            "fallback_reason": None,
            "session_id":    session_id,
            "pipeline":      ["conv_pattern", "ticket_auto"],
        }

    if conv_match:
        response_text = _CONV_RESPONSES[conv_match]
        save_message(
            session_id, "assistant", response_text,
            user_id=user_id, intent="CONV",
        )
        return {
            "question":       question,
            "classification": {
                "intent":     "CONV",
                "confidence": "HIGH",
                "reason":     conv_match,
                "source":     "pattern",
            },
            "routing": {
                "channel":  "CHATBOT",
                "reason":   "Pattern conversationnel",
                "priority": "NORMAL",
            },
            "rag_response": response_text,
            "sources":      [],
            "ticket_id":    None,
            "fallback_reason": None,
            "session_id":   session_id,
            "pipeline":     ["conv_pattern"],
        }

    # ── Mémoire métier : ticket actif pour cette session ──────────────────
    if session_id:
        active = find_by_session(session_id)
        if active:
            state = active.get("state", "NOUVEAU")
            resolution = active.get("resolution", {})
            client_msg = resolution.get("client_message")
            ticket_id = active.get("ticket_id")

            # Ticket résolu → retourner la décision directement
            if state in ("VALIDE", "REJETE") and client_msg:
                save_message(session_id, "assistant", client_msg,
                             user_id=user_id)
                return {
                    "question":       question,
                    "classification": active.get("classification", {}),
                    "routing":        {"channel": "CHATBOT",
                                       "reason": "Résolution backoffice",
                                       "priority": "NORMAL"},
                    "rag_response":   client_msg,
                    "sources":        [],
                    "ticket_id":      ticket_id,
                    "fallback_reason": None,
                    "source":         "backoffice_resolution",
                    "session_id":     session_id,
                }

            # Ticket en attente de réponse client → enregistrer réponse
            if state == "EN_ATTENTE_CLIENT":
                client_responds(ticket_id, question)
                _resp = (
                    "Merci pour votre réponse. "
                    "Notre équipe reviendra vers vous prochainement."
                )
                save_message(session_id, "assistant", _resp,
                             user_id=user_id)
                return {
                    "question":       question,
                    "classification": active.get("classification", {}),
                    "routing":        {"channel": "CHATBOT",
                                       "reason": "Réponse client enregistrée",
                                       "priority": "NORMAL"},
                    "rag_response":   _resp,
                    "sources":        [],
                    "ticket_id":      ticket_id,
                    "fallback_reason": None,
                    "source":         "backoffice_pending",
                    "session_id":     session_id,
                }

            # Ticket en cours → informer le client
            if state in ("NOUVEAU", "EN_COURS", "COMPLEMENT_REQUIS"):
                _resp = (
                    f"Votre demande (réf. {ticket_id}) est en cours "
                    "de traitement par notre équipe. "
                    "Nous vous contacterons dès que possible."
                )
                save_message(session_id, "assistant", _resp,
                             user_id=user_id)
                return {
                    "question":       question,
                    "classification": active.get("classification", {}),
                    "routing":        {"channel": "CHATBOT",
                                       "reason": "Ticket en cours de traitement",
                                       "priority": "NORMAL"},
                    "rag_response":   _resp,
                    "sources":        [],
                    "ticket_id":      ticket_id,
                    "fallback_reason": None,
                    "source":         "backoffice_pending",
                    "session_id":     session_id,
                }

    # ── Classification ────────────────────────────────────────────────────
    try:
        msgs = [
            SystemMessage(content=CLASSIFIER_SYSTEM),
            HumanMessage(content=question),
        ]
        raw = _llm_invoke_with_retry(msgs).content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        classification = json.loads(raw)
    except Exception:
        classification = {
            "intent":     "INFORMATION",
            "confidence": "LOW",
            "reason":     "classification échouée",
        }

    intent = classification.get("intent", "INFORMATION")
    confidence = classification.get("confidence", "N/A")
    reason_cls = classification.get("reason", "N/A")

    # ── Routage ───────────────────────────────────────────────────────────
    routing = route(intent=intent, question=question)

    # ── Injection historique conversationnel dans RAG (A1) ────────────────
    hist_text = ""
    if session_id:
        history_msgs = get_session_history(session_id, limit=6)
        if history_msgs:
            lines = []
            for m in history_msgs:
                role_label = "Client" if m["role"] == "user" else "Assistant"
                lines.append(f"{role_label}: {m['content']}")
            hist_text = "\n".join(lines)

    # ── RAG ───────────────────────────────────────────────────────────────
    cur = get_conn().cursor()
    q_vec = embeddings.embed_query(question)
    cur.execute(
        "SELECT content, source FROM documents "
        "ORDER BY embedding <-> %s::vector LIMIT 5;",
        (q_vec,),
    )
    rows = cur.fetchall()
    context = "\n\n".join(c for c, _ in rows)
    sources = list({s for _, s in rows})

    # Construire le prompt RAG avec historique si disponible (A1)
    rag_prompt_parts = [
        "Tu es assistant bancaire BNM. "
        "Réponds UNIQUEMENT avec le contexte fourni.",
    ]
    if hist_text:
        rag_prompt_parts.append(
            f"\nHistorique de la conversation :\n{hist_text}"
        )
    rag_prompt_parts.append(
        f"\nContexte documentaire:\n{context}"
        f"\n\nQuestion: {question}\n\nRéponse:"
    )
    rag_response = _llm_invoke_with_retry(
        "\n".join(rag_prompt_parts)
    ).content
    cur.close()

    # ── Détection fallback (A2) ───────────────────────────────────────────
    fallback_reason = None
    if _is_rag_weak(rag_response) and routing["channel"] == "CHATBOT":
        routing = {
            "channel":  "BACKOFFICE",
            "reason":   "Réponse RAG insuffisante — transfert automatique",
            "priority": "NORMAL",
        }
        fallback_reason = "RAG insuffisant"
        # Message de fallback crédible proposant un conseiller
        rag_response = (
            "Je n'ai pas trouvé de réponse précise dans notre documentation. "
            "Votre demande a été transmise à un conseiller BNM qui vous "
            "répondra dans les meilleurs délais. "
            "Vous pouvez également nous contacter directement pour un traitement rapide."
        )

    # ── Ticket si BACKOFFICE ──────────────────────────────────────────────
    ticket_id = None
    if routing["channel"] == "BACKOFFICE":
        # ── Affectation automatique (Phase 2) ─────────────────────
        from backoffice import pick_agent_for_role, _intent_to_role as _i2r
        _assigned_role  = _i2r(intent)
        _assigned_agent = pick_agent_for_role(_assigned_role, _DB_PARAMS)

        ticket_id, _ = save_ticket(
            question=question,
            intent=intent,
            confidence=confidence,
            reason_classification=reason_cls,
            rag_response=rag_response,
            routing_reason=routing["reason"],
            priority=routing["priority"],
            fallback_reason=fallback_reason,
            session_id=session_id,
            sources=sources,
            assigned_role=_assigned_role,
            assigned_agent=_assigned_agent,
        )

    # ── Sauvegarder réponse assistant (historique persistant) ────────────
    save_message(
        session_id, "assistant", rag_response,
        user_id=user_id, intent=intent,
    )

    return {
        "question":       question,
        "classification": {
            "intent":     intent,
            "confidence": confidence,
            "reason":     reason_cls,
        },
        "routing": {
            "channel":  routing["channel"],
            "reason":   routing["reason"],
            "priority": routing["priority"],
        },
        "rag_response":   rag_response,
        "sources":        sources,
        "ticket_id":      ticket_id,
        "fallback_reason": fallback_reason,
        "session_id":     session_id,
    }


# ── GET /tickets ──────────────────────────────────────────────────────────────

@app.get("/tickets")
def list_tickets(
    state:    Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    intent:   Optional[str] = Query(None),
    role:     Optional[str] = Query(None),
    creds: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
):
    """Liste les tickets avec filtres optionnels."""
    from auth import verify_token
    # Sécurité : filtrage par rôle agent si token présent
    user_payload = None
    if creds and creds.credentials:
        user_payload = verify_token(creds.credentials)

    if user_payload:
        agent_role_from_token = user_payload.get("agent_role")
        if agent_role_from_token and agent_role_from_token != "ADMIN" and not role:
            role = agent_role_from_token

    conv_dir = os.path.join(os.path.dirname(__file__), "conversations")
    tickets = []
    if os.path.exists(conv_dir):
        for f in sorted(os.listdir(conv_dir), reverse=True):
            if not f.endswith(".json"):
                continue
            try:
                with open(
                    os.path.join(conv_dir, f), encoding="utf-8"
                ) as fp:
                    t = json.load(fp)
                t = _normalize_ticket(t)
                # Filtres
                if state and t.get("state") != state:
                    continue
                if priority and t.get("priority") != priority:
                    continue
                if intent and t.get(
                    "classification", {}
                ).get("intent") != intent:
                    continue
                if role:
                    if role == "VALIDATION":
                        if t.get("classification", {}).get("intent") != "VALIDATION":
                            continue
                    elif role == "RECLAMATION":
                        if t.get("classification", {}).get("intent") != "RECLAMATION":
                            continue
                    elif role == "INFORMATION":
                        if not (t.get("classification", {}).get("intent") == "INFORMATION" and t.get("routing", {}).get("channel") == "BACKOFFICE"):
                            continue
                tickets.append(t)
            except Exception:
                pass
    # Tri : URGENT/HIGH en haut, puis par created_at desc
    _prio_order = {"URGENT": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
    tickets.sort(
        key=lambda x: (
            _prio_order.get(x.get("priority", "NORMAL"), 2),
            x.get("created_at", x.get("timestamp", "")),
        )
    )
    return tickets


# ── GET /tickets/{id} ─────────────────────────────────────────────────────────

@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str):
    try:
        return load_ticket(ticket_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")


# ── GET /conversations/{id} (rétrocompat) ─────────────────────────────────────

@app.get("/conversations/{ticket_id}")
def get_conversation(ticket_id: str):
    try:
        ticket = load_ticket(ticket_id)
        return {
            "ticket_id":     ticket["ticket_id"],
            "state":         ticket.get("state", "NOUVEAU"),
            "agent_assigned": ticket.get("agent_assigned"),
            "fallback_reason": ticket.get("fallback_reason"),
            "history":       ticket.get("history", []),
        }
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail="Conversation introuvable"
        )


# ── Actions existantes (rétrocompat) ──────────────────────────────────────────

@app.post("/tickets/{ticket_id}/assign")
def ticket_assign(ticket_id: str, body: AssignBody,
                  _user=Depends(get_current_user)):
    from permissions import can_access_ticket as _can
    try:
        _td = load_ticket(ticket_id)
        if not _can(_user, _td):
            raise HTTPException(status_code=403, detail="Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")
    data = assign_ticket(ticket_id, body.agent)
    return {
        "status":        "ok",
        "state":         data["state"],
        "agent_assigned": data["agent_assigned"],
    }


@app.post("/tickets/{ticket_id}/reply")
def ticket_reply(ticket_id: str, body: ReplyBody,
                 _user=Depends(get_current_user)):
    from permissions import can_access_ticket as _can
    try:
        _td = load_ticket(ticket_id)
        if not _can(_user, _td):
            raise HTTPException(status_code=403, detail="Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")
    data = reply_ticket(ticket_id, body.agent, body.message)
    # Sync → conversation_history
    session_id = _td.get("client", {}).get("session_id", "")
    if session_id:
        save_message(
            session_id=session_id,
            role="agent",
            content=body.message,
            intent=_td.get("classification", {}).get("intent"),
            meta={
                "agent":        body.agent,
                "ticket_id":    ticket_id,
                "action":       "reply",
                "role_display": f"Conseiller BNM ({body.agent})",
            },
        )
    return {"status": "ok", "history_length": len(data["history"])}


@app.post("/tickets/{ticket_id}/return-to-bot")
def ticket_return_to_bot(ticket_id: str):
    try:
        data = return_to_bot(ticket_id)
        return {"status": "ok", "state": data["state"]}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")


@app.post("/tickets/{ticket_id}/close")
def ticket_close(ticket_id: str, _user=Depends(get_current_user)):
    from permissions import can_access_ticket as _can
    try:
        _td = load_ticket(ticket_id)
        if not _can(_user, _td):
            raise HTTPException(status_code=403, detail="Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")
    data = close_ticket(ticket_id)
    return {"status": "ok", "state": data["state"]}


@app.post("/tickets/{ticket_id}/reopen")
def ticket_reopen(ticket_id: str, u=Depends(get_current_user)):
    """CLOTURE → EN_COURS. Réservé aux ADMIN."""
    if u.get("agent_role") != "ADMIN":
        raise HTTPException(status_code=403, detail="ADMIN uniquement")
    try:
        data = reopen_ticket(ticket_id, agent_id=u.get("username", "admin"))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")
    return {"status": "ok", "state": data["state"], "ticket_id": ticket_id}


# ── Nouveaux endpoints métier ─────────────────────────────────────────────────

@app.post("/tickets/{ticket_id}/request-complement")
def ticket_request_complement(ticket_id: str, body: ComplementBody,
                               _user=Depends(get_current_user)):
    """EN_COURS → COMPLEMENT_REQUIS. Génère message client."""
    from permissions import can_access_ticket as _can
    try:
        _td = load_ticket(ticket_id)
        if not _can(_user, _td):
            raise HTTPException(status_code=403, detail="Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")
    data = request_complement(ticket_id, body.message, body.agent or "agent")
    # Sync → conversation_history (message généré visible client)
    session_id = _td.get("client", {}).get("session_id", "")
    client_msg = data["resolution"].get("client_message") or body.message
    if session_id and client_msg:
        save_message(
            session_id=session_id,
            role="agent",
            content=client_msg,
            intent=_td.get("classification", {}).get("intent"),
            meta={
                "agent":        body.agent or "BNM",
                "ticket_id":    ticket_id,
                "action":       "request_complement",
                "role_display": "Conseiller BNM",
            },
        )
    return {
        "status": "ok",
        "state":  data["state"],
        "client_message": client_msg,
    }


@app.post("/tickets/{ticket_id}/validate")
def ticket_validate(ticket_id: str, body: ValidateBody,
                    _user=Depends(get_current_user)):
    """EN_COURS → VALIDE. Génère message client."""
    from permissions import can_access_ticket as _can
    try:
        _td = load_ticket(ticket_id)
        if not _can(_user, _td):
            raise HTTPException(status_code=403, detail="Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")
    data = validate_ticket(ticket_id, body.agent or "agent", body.note or "")
    # Sync → conversation_history
    session_id = _td.get("client", {}).get("session_id", "")
    client_msg = data["resolution"].get("client_message")
    if session_id and client_msg:
        save_message(
            session_id=session_id,
            role="agent",
            content=client_msg,
            intent="VALIDATION",
            meta={
                "agent":        body.agent or "agent",
                "ticket_id":    ticket_id,
                "action":       "validate",
                "role_display": "✅ Conseiller BNM",
            },
        )
    return {
        "status": "ok",
        "state":  data["state"],
        "client_message": client_msg,
    }


@app.post("/tickets/{ticket_id}/reject")
def ticket_reject(ticket_id: str, body: RejectBody,
                  _user=Depends(get_current_user)):
    """EN_COURS → REJETE. Génère message client."""
    from permissions import can_access_ticket as _can
    try:
        _td = load_ticket(ticket_id)
        if not _can(_user, _td):
            raise HTTPException(status_code=403, detail="Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")
    data = reject_ticket(ticket_id, body.agent or "agent", body.reason)
    # Sync → conversation_history
    session_id = _td.get("client", {}).get("session_id", "")
    client_msg = data["resolution"].get("client_message")
    if session_id and client_msg:
        save_message(
            session_id=session_id,
            role="agent",
            content=client_msg,
            intent=_td.get("classification", {}).get("intent"),
            meta={
                "agent":        body.agent or "agent",
                "ticket_id":    ticket_id,
                "action":       "reject",
                "role_display": "❌ Conseiller BNM",
            },
        )
    return {
        "status": "ok",
        "state":  data["state"],
        "client_message": client_msg,
    }


@app.post("/tickets/{ticket_id}/ask-client")
def ticket_ask_client(ticket_id: str, body: AskClientBody,
                      _user=Depends(get_current_user)):
    """EN_COURS → EN_ATTENTE_CLIENT."""
    from permissions import can_access_ticket as _can
    try:
        _td = load_ticket(ticket_id)
        if not _can(_user, _td):
            raise HTTPException(status_code=403, detail="Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")
    data = ask_client(ticket_id, body.question, body.agent or "agent")
    # Sync → conversation_history
    session_id = _td.get("client", {}).get("session_id", "")
    client_msg = data["resolution"].get("client_message") or body.question
    if session_id and client_msg:
        save_message(
            session_id=session_id,
            role="agent",
            content=client_msg,
            intent=_td.get("classification", {}).get("intent"),
            meta={
                "agent":        body.agent or "agent",
                "ticket_id":    ticket_id,
                "action":       "ask_client",
                "role_display": "👤 Conseiller BNM",
            },
        )
    return {
        "status": "ok",
        "state":  data["state"],
        "client_message": client_msg,
    }


@app.post("/tickets/{ticket_id}/add-comment")
def ticket_add_comment(ticket_id: str, body: CommentBody,
                       _user=Depends(get_current_user)):
    """Ajoute un commentaire (interne ou visible client)."""
    from permissions import can_access_ticket as _can
    try:
        _td = load_ticket(ticket_id)
        if not _can(_user, _td):
            raise HTTPException(status_code=403, detail="Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")
    data = add_comment(
        ticket_id, body.comment, body.visible_to_client, body.agent or "agent"
    )
    return {
        "status":         "ok",
        "messages_count": len(data.get("messages", [])),
    }


@app.post("/tickets/{ticket_id}/set-priority")
def ticket_set_priority(ticket_id: str, body: PriorityBody):
    """Met à jour la priorité."""
    try:
        data = set_priority(ticket_id, body.priority)
        return {"status": "ok", "priority": data["priority"]}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/tickets/{ticket_id}/client-response")
def ticket_client_response(ticket_id: str, body: ClientResponseBody):
    """Le client répond → EN_ATTENTE_CLIENT → EN_COURS."""
    try:
        data = client_responds(ticket_id, body.message)
        return {"status": "ok", "state": data["state"]}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")


# ── Documents ─────────────────────────────────────────────────────────────────

@app.post("/tickets/{ticket_id}/documents")
async def upload_document(
    ticket_id: str,
    file: UploadFile = File(...),
    creds: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
):
    """Upload un document pour ce ticket (client ou agent)."""
    try:
        t = load_ticket(ticket_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")

    # Déterminer l'origine de l'upload
    uploaded_by = "agent" if (creds and creds.credentials) else "client"

    dest_dir = Path(UPLOADS_DIR) / ticket_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    doc_id = str(uuid.uuid4())
    filename = file.filename or f"file_{doc_id}"
    safe_fn = "".join(
        c for c in filename if c.isalnum() or c in "._- "
    ).strip()
    dest = dest_dir / f"{doc_id}_{safe_fn}"

    content = await file.read()
    dest.write_bytes(content)

    doc_entry = {
        "doc_id":       doc_id,
        "filename":     safe_fn,
        "mime_type":    file.content_type or "application/octet-stream",
        "size_bytes":   len(content),
        "uploaded_at":  time.strftime("%Y-%m-%dT%H:%M:%S"),
        "uploaded_by":  uploaded_by,
        "storage_path": str(dest),
        "status":       "pending",
    }
    t.setdefault("documents", []).append(doc_entry)

    from backoffice import _save, _add_message
    t = _add_message(
        t, "system",
        f"Document ajouté : {safe_fn}",
        visible_to_client=False,
    )
    _save(t)

    # Sync → conversation_history (client uploads uniquement)
    if uploaded_by == "client":
        session_id = t.get("client", {}).get("session_id", "")
        if session_id:
            save_message(
                session_id=session_id,
                role="user",
                content=f"📎 Document envoyé : {safe_fn}",
                meta={
                    "doc_id":     doc_id,
                    "filename":   safe_fn,
                    "mime_type":  file.content_type or "application/octet-stream",
                    "ticket_id":  ticket_id,
                    "isFile":     True,
                    "size_bytes": len(content),
                },
            )

    return {"status": "ok", "doc_id": doc_id, "filename": safe_fn}


@app.get("/tickets/{ticket_id}/documents")
def list_documents(ticket_id: str):
    """Liste les documents d'un ticket."""
    try:
        t = load_ticket(ticket_id)
        return t.get("documents", [])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")


@app.get("/tickets/{ticket_id}/documents/{doc_id}")
def download_document(ticket_id: str, doc_id: str):
    """Télécharge un document."""
    try:
        t = load_ticket(ticket_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")

    docs = t.get("documents", [])
    doc = next((d for d in docs if d["doc_id"] == doc_id), None)
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")

    path = Path(doc["storage_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fichier introuvable")

    return FileResponse(
        path=str(path),
        filename=doc["filename"],
        media_type=doc.get("mime_type", "application/octet-stream"),
        headers={
            "Content-Disposition": f'inline; filename="{doc["filename"]}"',
        },
    )


# ── Lecture métier chatbot ────────────────────────────────────────────────────

@app.get("/tickets/by-session/{session_id}")
def ticket_by_session(session_id: str):
    """Retourne le dernier ticket actif pour une session."""
    t = find_by_session(session_id)
    if not t:
        raise HTTPException(
            status_code=404, detail="Aucun ticket pour cette session"
        )
    return t


@app.get("/tickets/{ticket_id}/client-message")
def get_client_message(ticket_id: str):
    """Retourne le message destiné au client (résolution)."""
    try:
        t = load_ticket(ticket_id)
        msg = t.get("resolution", {}).get("client_message")
        return {
            "ticket_id":      ticket_id,
            "state":          t.get("state"),
            "client_message": msg,
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Ticket introuvable")


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/stats/tickets")
def stats_tickets():
    """Stats agrégées des tickets."""
    return ticket_stats()


# ── Historique conversationnel ─────────────────────────────────────────────────

@app.get("/history/{session_id}")
def history_by_session(session_id: str):
    """
    Retourne l'historique conversationnel d'une session.
    Public pour le développement — à sécuriser via JWT en production.
    """
    return get_session_history(session_id, limit=100)


@app.get("/users/{user_id}/conversations")
def user_conversations(
    user_id: str,
    _user=Depends(get_current_user),
):
    """Liste des sessions conversationnelles d'un utilisateur (protégé JWT)."""
    return get_user_conversations(user_id)


# ── Liaison session ↔ utilisateur (A6 / B8) ───────────────────────────────────

class LinkSessionBody(BaseModel):
    user_id: str


@app.post("/sessions/{session_id}/link")
def link_session(
    session_id: str,
    body: LinkSessionBody,
    _user=Depends(get_current_user),
):
    """
    Lie une session anonyme à un utilisateur authentifié.
    Protégé JWT — appelé depuis le front après connexion (B8).
    """
    from conversation_store import link_session_to_user
    link_session_to_user(session_id, body.user_id)
    return {"status": "ok", "session_id": session_id, "user_id": body.user_id}


# ── Agents ────────────────────────────────────────────────────────────────────

@app.get("/agents")
def list_agents(role: Optional[str] = Query(None)):
    """Liste les agents avec leur charge actuelle."""
    try:
        cur2 = get_conn().cursor()
        if role:
            cur2.execute(
                "SELECT username, agent_role FROM users"
                " WHERE agent_role = %s ORDER BY username",
                (role,)
            )
        else:
            cur2.execute(
                "SELECT username, agent_role FROM users"
                " WHERE agent_role IS NOT NULL ORDER BY username"
            )
        rows = cur2.fetchall()
        cur2.close()
    except Exception:
        rows = []

    from backoffice import CONVERSATIONS_DIR
    import json as _json

    result = []
    for username, agent_role_val in rows:
        total = en_cours = 0
        if os.path.exists(CONVERSATIONS_DIR):
            for f in os.listdir(CONVERSATIONS_DIR):
                if not f.endswith(".json"):
                    continue
                try:
                    with open(
                        os.path.join(CONVERSATIONS_DIR, f), encoding="utf-8"
                    ) as fp:
                        t = _json.load(fp)
                    if t.get("assigned_agent") == username:
                        total += 1
                        if t.get("state") in ("NOUVEAU", "EN_COURS"):
                            en_cours += 1
                except Exception:
                    pass
        result.append({
            "username":   username,
            "agent_role": agent_role_val,
            "total":      total,
            "en_cours":   en_cours,
        })
    return result


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.get("/admin/stats")
def admin_stats(_user=Depends(get_current_user)):
    if _user.get("agent_role") != "ADMIN":
        raise HTTPException(403, "Accès ADMIN requis")
    from backoffice import CONVERSATIONS_DIR
    import json as _json
    from datetime import timedelta
    stats = {
        "total": 0, "par_state": {}, "par_role": {},
        "par_agent": {}, "par_jour": {},
    }
    today = __import__("datetime").datetime.now().date()
    days = {str(today - timedelta(days=i)): 0 for i in range(6, -1, -1)}
    if os.path.exists(CONVERSATIONS_DIR):
        for f in os.listdir(CONVERSATIONS_DIR):
            if not f.endswith(".json"):
                continue
            try:
                with open(
                    os.path.join(CONVERSATIONS_DIR, f), encoding="utf-8"
                ) as fp:
                    t = _json.load(fp)
                stats["total"] += 1
                state   = t.get("state", "NOUVEAU")
                role_t  = t.get("assigned_role", "?")
                agent   = t.get("assigned_agent") or "non_affecte"
                created = t.get("created_at", "")[:10]
                stats["par_state"][state] = (
                    stats["par_state"].get(state, 0) + 1
                )
                stats["par_role"][role_t] = (
                    stats["par_role"].get(role_t, 0) + 1
                )
                if created in days:
                    days[created] += 1
                if agent not in stats["par_agent"]:
                    stats["par_agent"][agent] = {
                        "username": agent, "total": 0,
                        "traites": 0, "en_cours": 0,
                    }
                stats["par_agent"][agent]["total"] += 1
                if state in ("VALIDE", "REJETE", "CLOTURE"):
                    stats["par_agent"][agent]["traites"] += 1
                elif state in ("NOUVEAU", "EN_COURS"):
                    stats["par_agent"][agent]["en_cours"] += 1
            except Exception:
                pass
    stats["par_jour"]  = days
    stats["par_agent"] = list(stats["par_agent"].values())
    return stats


@app.get("/admin/agents/{username}/tickets")
def admin_agent_tickets(username: str, _user=Depends(get_current_user)):
    if _user.get("agent_role") != "ADMIN":
        raise HTTPException(403, "Accès ADMIN requis")
    from backoffice import CONVERSATIONS_DIR
    import json as _json
    result = []
    if os.path.exists(CONVERSATIONS_DIR):
        for f in sorted(os.listdir(CONVERSATIONS_DIR), reverse=True):
            if not f.endswith(".json"):
                continue
            try:
                with open(
                    os.path.join(CONVERSATIONS_DIR, f), encoding="utf-8"
                ) as fp:
                    t = _json.load(fp)
                if t.get("assigned_agent") == username:
                    result.append(t)
            except Exception:
                pass
    return result
