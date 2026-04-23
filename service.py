"""
service.py — Pipeline RAG complet (standalone, sans dépendance externe).

Extrait et adapté depuis api_server.py du projet BNM Chatbot.
Aucun import depuis le projet original — tout est self-contained.
"""
import json
import logging
import os
import re
import time
import unicodedata
import uuid

import openai
import psycopg2
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

load_dotenv()
logger = logging.getLogger(__name__)

# ── DB (connexion lazy) ────────────────────────────────────────────────────────

_DB_PARAMS = dict(
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST", "localhost"),
    port=os.getenv("DB_PORT", "5432"),
)

_conn_global = None


def _get_conn():
    global _conn_global
    if _conn_global is None:
        _conn_global = psycopg2.connect(**_DB_PARAMS)
    try:
        _conn_global.cursor().execute("SELECT 1")
    except Exception:
        _conn_global = psycopg2.connect(**_DB_PARAMS)
    return _conn_global


# ── LLM / Embeddings (initialisés au premier appel) ───────────────────────────

_embeddings = None
_llm = None


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = OpenAIEmbeddings(
            model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-ada-002"),
        )
    return _embeddings


def _get_llm():
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        )
    return _llm


# ── Historique conversationnel ─────────────────────────────────────────────────

def save_message(
    session_id: str,
    role: str,
    content: str,
    intent: str = None,
    meta: dict = None,
) -> None:
    """Insère un message dans conversation_history (non-bloquant)."""
    if not session_id or not session_id.strip():
        return
    try:
        c = psycopg2.connect(**_DB_PARAMS)
        cur = c.cursor()
        cur.execute(
            """
            INSERT INTO conversation_history
                (session_id, role, content, intent, meta)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                session_id,
                role,
                content,
                intent,
                json.dumps(meta, ensure_ascii=False) if meta else None,
            ),
        )
        c.commit()
        cur.close()
        c.close()
    except Exception as e:
        logger.warning("save_message failed (non-fatal): %s", e)


def get_session_history(session_id: str, limit: int = 6) -> list:
    """Retourne les N derniers messages d'une session (ordre chronologique)."""
    try:
        c = psycopg2.connect(**_DB_PARAMS)
        cur = c.cursor()
        cur.execute(
            """
            SELECT role, content FROM (
                SELECT role, content, timestamp
                FROM conversation_history
                WHERE session_id = %s
                ORDER BY timestamp DESC
                LIMIT %s
            ) sub ORDER BY timestamp ASC
            """,
            (session_id, limit),
        )
        rows = cur.fetchall()
        cur.close()
        c.close()
        return [{"role": r[0], "content": r[1]} for r in rows]
    except Exception as e:
        logger.warning("get_session_history failed: %s", e)
        return []


# ── Classificateur ─────────────────────────────────────────────────────────────

_CLASSIFIER_SYSTEM = (
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


# ── Patterns conversationnels ──────────────────────────────────────────────────

_CONV_PATTERNS: dict = {
    # Priorité haute : produits BNM spécifiques
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
    # Patterns conversationnels génériques
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

_CONV_RESPONSES: dict = {
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


# ── Helpers ────────────────────────────────────────────────────────────────────

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


def _is_rag_weak(response: str) -> bool:
    """Retourne True si la réponse RAG est trop faible pour être utile."""
    if not response or len(response.strip()) < 60:
        return True
    lower = response.lower()
    return any(p in lower for p in _FALLBACK_PATTERNS)


def _llm_invoke_with_retry(prompt, max_retries: int = 1):
    for attempt in range(max_retries + 1):
        try:
            return _get_llm().invoke(prompt)
        except openai.RateLimitError:
            if attempt < max_retries:
                time.sleep(5)
            else:
                raise


def _classify_intent(question: str, contexte: list = None) -> dict:
    """Classifie l'intention via OpenAI avec prise en compte du contexte conversationnel.
    
    Args:
        question: La question de l'utilisateur
        contexte: Liste des messages précédents au format 
                  [{"role": "client"|"assistant", "content": str}]
    """
    try:
        # Construire le message avec contexte si disponible
        message_a_classifier = question
        if contexte and len(contexte) > 0:
            # Formater l'historique de la conversation
            historique = "\n".join([
                f"{msg['role']}: {msg['content']}" 
                for msg in contexte[-5:]  # Garder les 5 derniers échanges
            ])
            message_a_classifier = f"""Historique de la conversation :
{historique}

Nouvelle question de l'utilisateur : {question}

IMPORTANT : Utilise l'historique pour comprendre les références implicites (pronoms, sujets sous-entendus). Exemples :
- Si l'utilisateur dit "oui" ou "je confirme" après une proposition, c'est une VALIDATION
- Si l'utilisateur dit "non", "je ne suis pas d'accord" ou "problème", c'est une RECLAMATION
- Si l'utilisateur demande une information générale, c'est INFORMATION
- Les pronoms comme "celui-ci", "ça", "il" font référence au dernier sujet mentionné

RÈGLE DE PRIORITÉ :
- La question actuelle détermine l'intention principale
- Le contexte sert à interpréter les questions ambiguës ou les réponses courtes
- En cas de doute entre INFORMATION et autre intention, privilégie INFORMATION"""

        msgs = [
            SystemMessage(content=_CLASSIFIER_SYSTEM),
            HumanMessage(content=message_a_classifier),
        ]
        raw = _llm_invoke_with_retry(msgs).content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception:
        return {
            "intent":     "INFORMATION",
            "confidence": "LOW",
            "reason":     "classification échouée"
            }

 


# ── Pipeline principal ─────────────────────────────────────────────────────────

def process_question(
    question: str,
    session_id: str,
    phone: str = None,
) -> dict:
    """
    Pipeline RAG complet :
    1. Vérifier pattern conversationnel → réponse directe
    2. Classifier l'intent (OpenAI)
    3. Chercher dans pgvector (top-5 chunks)
    4. Générer réponse (OpenAI GPT-4o-mini)
    5. Détecter si réponse faible
    6. Sauvegarder dans l'historique
    Retourne : answer, intent, confidence, sources, pipeline, session_id
    """
    # Normaliser session_id
    if not session_id:
        if phone:
            phone_clean = re.sub(r"\D", "", phone)
            session_id = f"phone_{phone_clean}"
        else:
            session_id = f"sess_{uuid.uuid4().hex[:12]}"

    # Sauvegarder la question
    save_message(session_id, "user", question)

    # ── Étape 1 : patterns conversationnels ──────────────────────────────────
    conv_match = _detect_conv_pattern(question)
    if conv_match:
        answer = _CONV_RESPONSES[conv_match]
        save_message(session_id, "assistant", answer, intent="CONV")
        return {
            "question":   question,
            "answer":     answer,
            "intent":     "CONV",
            "confidence": "HIGH",
            "sources":    [],
            "pipeline":   ["conv_pattern"],
            "session_id": session_id,
        }

    # ── Étape 2 : classification intent ──────────────────────────────────────
    classification = _classify_intent(question)
    intent     = classification.get("intent", "INFORMATION")
    confidence = classification.get("confidence", "N/A")

    # ── Étape 3 : historique conversationnel ─────────────────────────────────
    history_msgs = get_session_history(session_id, limit=6)
    hist_text = ""
    if history_msgs:
        lines = []
        for m in history_msgs:
            label = "Client" if m["role"] == "user" else "Assistant"
            lines.append(f"{label}: {m['content']}")
        hist_text = "\n".join(lines)

    # ── Étape 4 : recherche pgvector ─────────────────────────────────────────
    q_vec = _get_embeddings().embed_query(question)
    cur = _get_conn().cursor()
    cur.execute(
        "SELECT content, source FROM documents "
        "ORDER BY embedding <-> %s::vector LIMIT 5;",
        (q_vec,),
    )
    rows = cur.fetchall()
    cur.close()
    context = "\n\n".join(c for c, _ in rows)
    sources = list({s for _, s in rows})

    # ── Étape 5 : génération RAG ─────────────────────────────────────────────
    prompt_parts = [
        "Tu es assistant bancaire BNM. "
        "Réponds UNIQUEMENT avec le contexte fourni.",
    ]
    if hist_text:
        prompt_parts.append(f"\nHistorique de la conversation :\n{hist_text}")
    prompt_parts.append(
        f"\nContexte documentaire:\n{context}"
        f"\n\nQuestion: {question}\n\nRéponse:"
    )
    answer = _llm_invoke_with_retry("\n".join(prompt_parts)).content

    # ── Étape 6 : détection réponse faible ───────────────────────────────────
    pipeline = ["classify", "pgvector", "rag"]
    if _is_rag_weak(answer):
        answer = (
            "Je n'ai pas trouvé de réponse précise dans notre documentation. "
            "Votre demande a été transmise à un conseiller BNM qui vous "
            "répondra dans les meilleurs délais. "
            "Vous pouvez également nous contacter directement pour un traitement rapide."
        )
        pipeline.append("fallback")
        sources = []

    # ── Étape 7 : sauvegarder la réponse ─────────────────────────────────────
    save_message(session_id, "assistant", answer, intent=intent)

    return {
        "question":   question,
        "answer":     answer,
        "intent":     intent,
        "confidence": confidence,
        "sources":    sources,
        "pipeline":   pipeline,
        "session_id": session_id,
    }
