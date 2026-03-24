"""
Chat Service — port 8002
Pipeline RAG, historique conversationnel, sessions client.

Endpoints :
  POST /ask
  POST /client/session
  GET  /history/phone/{phone}
  GET  /history/{session_id}
  GET  /users/{user_id}/conversations
  POST /sessions/{session_id}/link
"""
import json
import os
import re
import time
import unicodedata
import uuid
from typing import Optional

import openai
import psycopg2
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import BaseModel

from auth import get_current_user
from backoffice import (
    _intent_to_role,
    client_responds,
    find_by_session,
    pick_agent_for_role,
    save_ticket,
)
from conversation_store import (
    get_session_history,
    get_user_conversations,
    link_session_to_user,
    save_message,
)
from router import route

load_dotenv()

app = FastAPI(title="BNM Chat Service", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Init DB + modèles LLM ─────────────────────────────────────────────────────

_DB_PARAMS = dict(
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
)
_conn_global = None


def get_conn():
    global _conn_global
    if _conn_global is None:
        _conn_global = psycopg2.connect(**_DB_PARAMS)
    try:
        _conn_global.cursor().execute("SELECT 1")
    except Exception:
        _conn_global = psycopg2.connect(**_DB_PARAMS)
    return _conn_global


embeddings = OpenAIEmbeddings(
    model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-ada-002"),
)
llm = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

CLASSIFIER_SYSTEM = (
    "Tu es un classificateur bancaire. Analyse la demande client "
    "et réponds UNIQUEMENT en JSON valide avec ce format exact :\n"
    '{"intent": "INFORMATION" | "RECLAMATION" | "VALIDATION", '
    '"confidence": "HIGH" | "MEDIUM" | "LOW", '
    '"reason": "explication courte en français (max 10 mots)"}\n'
    "Ne réponds rien d'autre que ce JSON."
)

_FALLBACK_PATTERNS = (
    "je ne sais pas", "je ne dispose pas",
    "cette information n'est pas", "n'est pas mentionné",
    "n'est pas fourni", "pas dans le contexte",
    "pas dans les documents", "aucune information",
    "je n'ai pas cette information", "non disponible",
    "i don't know", "don't know",
    "ne contient pas d'information", "ne contient pas cette information",
    "ne mentionne pas", "pas d'information",
    "pas mentionné dans", "n'est pas dans le contexte",
    "context provided does not", "not mentioned in",
)

# ── Pydantic models ───────────────────────────────────────────────────────────

class QuestionRequest(BaseModel):
    question:   str
    session_id: Optional[str] = None
    user_id:    Optional[str] = None
    phone:      Optional[str] = None


class ClientSessionRequest(BaseModel):
    phone: str


class LinkSessionBody(BaseModel):
    user_id: str


# ── Patterns conversationnels ─────────────────────────────────────────────────

_CONV_PATTERNS: dict[str, list[str]] = {
    "compte_click": [
        r"(?i)^\s*click\s*$",
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
    "salutation": [r"\b(bonjour|bonsoir|salut|hello|salam|مرحبا|السلام)\b"],
    "remerciement": [r"\b(merci|thank(?:\s+you)?|thanks|شكرا|mرسي)\b"],
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
    "salutation": "Bonjour ! Je suis l'assistant virtuel de la BNM. Comment puis-je vous aider ?",
    "remerciement": "Je vous en prie ! N'hésitez pas si vous avez d'autres questions.",
    "identite_bot": (
        "Je suis l'assistant virtuel de la Banque Nationale de Mauritanie (BNM). "
        "Je peux vous aider sur nos produits, services et réclamations."
    ),
    "au_revoir": "Au revoir ! Bonne journée et à bientôt sur BNM.",
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
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
    )


def _detect_conv_pattern(question: str) -> str | None:
    q = _normalize_str(question)
    for intent, patterns in _CONV_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, q, re.IGNORECASE):
                return intent
    return None


def _is_rag_weak(rag_response: str) -> bool:
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


# ── Endpoints ─────────────────────────────────────────────────────────────────

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


@app.get("/history/{session_id}")
def history_by_session(session_id: str):
    return get_session_history(session_id, limit=100)


@app.get("/users/{user_id}/conversations")
def user_conversations(user_id: str, _user=Depends(get_current_user)):
    return get_user_conversations(user_id)


@app.post("/sessions/{session_id}/link")
def link_session(
    session_id: str,
    body: LinkSessionBody,
    _user=Depends(get_current_user),
):
    link_session_to_user(session_id, body.user_id)
    return {"status": "ok", "session_id": session_id, "user_id": body.user_id}


@app.post("/ask")
def ask(req: QuestionRequest):
    question   = req.question
    user_id    = req.user_id or None
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    if req.phone and not req.session_id:
        phone_clean = re.sub(r'\D', '', req.phone)
        session_id = f"phone_{phone_clean}"

    save_message(session_id, "user", question, user_id=user_id)

    # ── Patterns conversationnels ─────────────────────────────────────────
    conv_match = _detect_conv_pattern(question)

    if conv_match == "compte_click":
        response_text = _CONV_RESPONSES["compte_click"]
        save_message(session_id, "assistant", response_text,
                     user_id=user_id, intent="VALIDATION")
        existing = find_by_session(session_id) if session_id else None
        click_ticket_id = None
        if existing and existing.get("state") not in ("VALIDE", "REJETE", "CLOTURE"):
            click_ticket_id = existing.get("ticket_id")
        else:
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
            "question": question,
            "classification": {"intent": "VALIDATION", "confidence": "HIGH",
                               "reason": "Demande validation compte Click", "source": "pattern"},
            "routing": {"channel": "BACKOFFICE", "reason": "Pattern compte Click — ticket auto", "priority": "NORMAL"},
            "rag_response": response_text, "sources": [], "ticket_id": click_ticket_id,
            "fallback_reason": None, "session_id": session_id,
            "pipeline": ["conv_pattern", "ticket_auto"],
        }

    if conv_match:
        response_text = _CONV_RESPONSES[conv_match]
        save_message(session_id, "assistant", response_text, user_id=user_id, intent="CONV")
        return {
            "question": question,
            "classification": {"intent": "CONV", "confidence": "HIGH", "reason": conv_match, "source": "pattern"},
            "routing": {"channel": "CHATBOT", "reason": "Pattern conversationnel", "priority": "NORMAL"},
            "rag_response": response_text, "sources": [], "ticket_id": None,
            "fallback_reason": None, "session_id": session_id, "pipeline": ["conv_pattern"],
        }

    # ── Mémoire ticket actif ──────────────────────────────────────────────
    if session_id:
        active = find_by_session(session_id)
        if active:
            state      = active.get("state", "NOUVEAU")
            resolution = active.get("resolution", {})
            client_msg = resolution.get("client_message")
            ticket_id  = active.get("ticket_id")

            if state in ("VALIDE", "REJETE") and client_msg:
                save_message(session_id, "assistant", client_msg, user_id=user_id)
                return {
                    "question": question,
                    "classification": active.get("classification", {}),
                    "routing": {"channel": "CHATBOT", "reason": "Résolution backoffice", "priority": "NORMAL"},
                    "rag_response": client_msg, "sources": [], "ticket_id": ticket_id,
                    "fallback_reason": None, "source": "backoffice_resolution", "session_id": session_id,
                }

            if state == "EN_ATTENTE_CLIENT":
                client_responds(ticket_id, question)
                _resp = "Merci pour votre réponse. Notre équipe reviendra vers vous prochainement."
                save_message(session_id, "assistant", _resp, user_id=user_id)
                return {
                    "question": question,
                    "classification": active.get("classification", {}),
                    "routing": {"channel": "CHATBOT", "reason": "Réponse client enregistrée", "priority": "NORMAL"},
                    "rag_response": _resp, "sources": [], "ticket_id": ticket_id,
                    "fallback_reason": None, "source": "backoffice_pending", "session_id": session_id,
                }

            if state in ("NOUVEAU", "EN_COURS", "COMPLEMENT_REQUIS"):
                _resp = (
                    f"Votre demande (réf. {ticket_id}) est en cours "
                    "de traitement par notre équipe. "
                    "Nous vous contacterons dès que possible."
                )
                save_message(session_id, "assistant", _resp, user_id=user_id)
                return {
                    "question": question,
                    "classification": active.get("classification", {}),
                    "routing": {"channel": "CHATBOT", "reason": "Ticket en cours de traitement", "priority": "NORMAL"},
                    "rag_response": _resp, "sources": [], "ticket_id": ticket_id,
                    "fallback_reason": None, "source": "backoffice_pending", "session_id": session_id,
                }

    # ── Classification ────────────────────────────────────────────────────
    try:
        msgs = [SystemMessage(content=CLASSIFIER_SYSTEM), HumanMessage(content=question)]
        raw = _llm_invoke_with_retry(msgs).content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        classification = json.loads(raw)
    except Exception:
        classification = {"intent": "INFORMATION", "confidence": "LOW", "reason": "classification échouée"}

    intent     = classification.get("intent", "INFORMATION")
    confidence = classification.get("confidence", "N/A")
    reason_cls = classification.get("reason", "N/A")

    # ── Routage ───────────────────────────────────────────────────────────
    routing = route(intent=intent, question=question)

    # ── Historique dans prompt RAG ────────────────────────────────────────
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

    rag_prompt_parts = ["Tu es assistant bancaire BNM. Réponds UNIQUEMENT avec le contexte fourni."]
    if hist_text:
        rag_prompt_parts.append(f"\nHistorique de la conversation :\n{hist_text}")
    rag_prompt_parts.append(
        f"\nContexte documentaire:\n{context}"
        f"\n\nQuestion: {question}\n\nRéponse:"
    )
    rag_response = _llm_invoke_with_retry("\n".join(rag_prompt_parts)).content
    cur.close()

    # ── Fallback ──────────────────────────────────────────────────────────
    fallback_reason = None
    if _is_rag_weak(rag_response) and routing["channel"] == "CHATBOT":
        routing = {"channel": "BACKOFFICE", "reason": "Réponse RAG insuffisante — transfert automatique", "priority": "NORMAL"}
        fallback_reason = "RAG insuffisant"
        rag_response = (
            "Je n'ai pas trouvé de réponse précise dans notre documentation. "
            "Votre demande a été transmise à un conseiller BNM qui vous "
            "répondra dans les meilleurs délais. "
            "Vous pouvez également nous contacter directement pour un traitement rapide."
        )

    # ── Ticket si BACKOFFICE ──────────────────────────────────────────────
    ticket_id = None
    if routing["channel"] == "BACKOFFICE":
        _assigned_role  = _intent_to_role(intent)
        _assigned_agent = pick_agent_for_role(_assigned_role, _DB_PARAMS)
        ticket_id, _ = save_ticket(
            question=question, intent=intent, confidence=confidence,
            reason_classification=reason_cls, rag_response=rag_response,
            routing_reason=routing["reason"], priority=routing["priority"],
            fallback_reason=fallback_reason, session_id=session_id,
            sources=sources, assigned_role=_assigned_role,
            assigned_agent=_assigned_agent,
        )

    save_message(session_id, "assistant", rag_response, user_id=user_id, intent=intent)

    return {
        "question": question,
        "classification": {"intent": intent, "confidence": confidence, "reason": reason_cls},
        "routing": {"channel": routing["channel"], "reason": routing["reason"], "priority": routing["priority"]},
        "rag_response": rag_response, "sources": sources,
        "ticket_id": ticket_id, "fallback_reason": fallback_reason, "session_id": session_id,
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "chat-service"}
