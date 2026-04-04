from fastapi import APIRouter
from models import IntentRequest, IntentResponse, AnswerRequest, AnswerResponse
from service import _CONV_PATTERNS

router = APIRouter(prefix="/rag", tags=["RAG"])


@router.get("/health")
def rag_health():
    return {
        "status":  "ok",
        "service": "bnm-rag-service",
        "port":    8021,
    }


@router.get("/patterns")
def rag_patterns():
    """Retourne tous les patterns conversationnels disponibles."""
    return {
        "patterns": list(_CONV_PATTERNS.keys()),
        "count":    len(_CONV_PATTERNS),
    }


@router.post("/getIntent", response_model=IntentResponse)
def get_intent(req: IntentRequest):
    """
    Reçoit une question et retourne uniquement son intention (intent).
    Valeurs possibles : VALIDATION | RECLAMATION | INFORMATION
    """
    from service import _classify_intent

    result = _classify_intent(req.question)
    intent = result.get("intent", "information")

    if intent not in ["VALIDATION", "RECLAMATION", "INFORMATION"]:
        intent = "information"

    return IntentResponse(intent=intent)


@router.post("/getAnswer", response_model=AnswerResponse)
def get_answer(req: AnswerRequest):
    """
    Reçoit une question + contexte et retourne la réponse RAG +
    open_conversation + intent + context utilisé.
    
    Règle Spécifique :
    - Si open_conversation = True : Prompt = Context (Derniers messages) + Base de Connaissance.
    - Si open_conversation = False : Prompt = Base de Connaissance UNIQUEMENT.
    """
    import json
    import uuid
    from service import (
        _llm_invoke_with_retry,
        _get_embeddings,
        _get_conn,
        _classify_intent,
        _is_rag_weak,
        save_message,
    )
    from langchain_core.messages import HumanMessage, SystemMessage

    # ── Étape 1 : construire l'historique ────────────────────────────
    # On prend les 5 derniers messages si présents
    context_to_use = req.context[-5:] if len(req.context) > 5 else req.context
    lines = []
    for msg in context_to_use:
        role = "Client" if msg.role == "client" else "Conseiller BNM"
        lines.append(f"{role}: {msg.content}")
    historique = "\n".join(lines)

    # ── Étape 2 : classifier l'intent ────────────────────────────────
    classification = _classify_intent(req.question)
    intent = classification.get("intent", "INFORMATION")

    # ── Étape 3 : détecter open_conversation ─────────────────────────
    if not req.context:
        open_conv = False
    else:
        system_check = (
            "Tu analyses si un message est lié  a une autre message de cette conversation.  "
            "à une message bancaire en cours."
            " Réponds UNIQUEMENT en JSON : "
            '{"open_conversation": true | false} '
        )
        user_check = (
            f"Conversation en cours :\n{historique}\n\n"
            f"Nouveau message : '{req.question}'\n"
            f"Ce message est-il lié à cette conversation ?"
        )
        try:
            raw = _llm_invoke_with_retry([
                SystemMessage(content=system_check),
                HumanMessage(content=user_check),
            ]).content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            open_conv = json.loads(raw).get("open_conversation", False)
        except Exception:
            open_conv = False

    # ── Étape 4 : recherche pgvector ─────────────────────────────────
    q_vec = _get_embeddings().embed_query(req.question)
    cur = _get_conn().cursor()
    cur.execute(
        "SELECT content, source FROM documents "
        "ORDER BY embedding <-> %s::vector LIMIT 5;",
        (q_vec,),
    )
    rows = cur.fetchall()
    cur.close()
    context_docs = "\n\n".join(c for c, _ in rows)

    # ── Étape 5 : construire le Prompt selon la règle demandée ───────
    SYSTEM_HUMAIN = (
        "Tu es Yasmine, conseillère virtuelle de la BNM. "
        "Tu donnes des réponses précises basées sur les documents BNM."
    )

    if open_conv:
        # CAS 1 : Match avec le contexte → Context + Base de Connaissance
        rag_prompt = (
            f"Historique de la conversation :\n{historique}\n\n"
            f"Base de connaissance BNM :\n{context_docs}\n\n"
            f"Question client : {req.question}"
        )
    else:
        # CAS 2 : Changement de sujet → Base de Connaissance UNIQUEMENT
        rag_prompt = (
            f"Base de connaissance BNM :\n{context_docs}\n\n"
            f"Nouvelle question client (nouveau sujet) : {req.question}"
        )

    # ── Étape 6 : générer la réponse ─────────────────────────────────
    answer = _llm_invoke_with_retry([
        SystemMessage(content=SYSTEM_HUMAIN),
        HumanMessage(content=rag_prompt),
    ]).content

    if _is_rag_weak(answer):
        answer = (
            "Je comprends votre demande. Malheureusement, je ne dispose pas "
            "de cette information. Je vous invite à contacter notre service client."
        )



    return AnswerResponse(
        answer=answer,
        intent=intent,
        open_conversation=open_conv,

    )


@router.post("/postAnswer")
def post_answer(req: AnswerRequest):
    """
    Version corrigée :
    - utilise intent et context depuis req
    - corrige le bug réclamation existante
    - retourne answer + intent + create_ticket + open_conversation
    """

    import json
    from service import (
        _llm_invoke_with_retry,
        _get_embeddings,
        _get_conn,
        _is_rag_weak,
    )
    from langchain_core.messages import HumanMessage, SystemMessage

    # ── Étape 1 : historique ────────────────────────────
    context_to_use = req.context[-5:] if len(req.context) > 5 else req.context
    lines = []
    for msg in context_to_use:
        role = "Client" if msg.role == "client" else "Conseiller BNM"
        lines.append(f"{role}: {msg.content}")
    historique = "\n".join(lines)

    # ── Étape 2 : intent DIRECT depuis req ✅ ───────────
    intent = req.intent if hasattr(req, "intent") else "INFORMATION"

    # ── Étape 3 : open conversation ────────────────────
    if not req.context:
        open_conv = False
    else:
        system_check = (
            "Tu analyses si un message est lié à une conversation en cours. "
            'Réponds UNIQUEMENT en JSON : {"open_conversation": true | false}'
        )
        user_check = (
            f"Conversation :\n{historique}\n\n"
            f"Nouveau message : {req.question}"
        )
        try:
            raw = _llm_invoke_with_retry([
                SystemMessage(content=system_check),
                HumanMessage(content=user_check),
            ]).content.strip()

            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            open_conv = json.loads(raw).get("open_conversation", False)
        except Exception:
            open_conv = False

    # ── Étape 4 : RAG ───────────────────────────────────
    q_vec = _get_embeddings().embed_query(req.question)
    cur = _get_conn().cursor()
    cur.execute(
        "SELECT content FROM documents "
        "ORDER BY embedding <-> %s::vector LIMIT 5;",
        (q_vec,),
    )
    rows = cur.fetchall()
    cur.close()

    context_docs = "\n\n".join(c for (c,) in rows)

    # ── Étape 5 : PROMPT corrigé 🔥 ─────────────────────
    SYSTEM = (
        "Tu es Yasmine, conseillère virtuelle de la BNM.\n"
        "Tu dois répondre ET décider si un ticket doit être créé.\n\n"

        "Réponds STRICTEMENT en JSON avec :\n"
        "- answer\n"
        "- create_ticket\n\n"

        "Règles IMPORTANTES :\n"

        "1. create_ticket = true UNIQUEMENT si le client veut créer une NOUVELLE réclamation.\n"

        "2. create_ticket = false si :\n"
        "- le client parle d’une réclamation déjà existante\n"
        "- il demande un suivi (statut, progression, réponse...)\n"
        "- il pose une question d'information\n\n"

        "Exemples :\n"
        "- 'je veux faire une réclamation' → true\n"
        "- 'où en est ma réclamation ?' → false\n"
        "- 'j'ai déjà fait une réclamation' → false\n"
    )

    if open_conv:
        prompt = (
            f"Intent: {intent}\n\n"
            f"Historique:\n{historique}\n\n"
            f"Base BNM:\n{context_docs}\n\n"
            f"Question: {req.question}"
        )
    else:
        prompt = (
            f"Intent: {intent}\n\n"
            f"Base BNM:\n{context_docs}\n\n"
            f"Question: {req.question}"
        )

    # ── Étape 6 : appel LLM ─────────────────────────────
    raw = _llm_invoke_with_retry([
        SystemMessage(content=SYSTEM),
        HumanMessage(content=prompt),
    ]).content.strip()

    # ── Étape 7 : parsing ───────────────────────────────
    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        result = json.loads(raw)

        answer = result.get("answer", "")
        create_ticket = bool(result.get("create_ticket", False))

    except Exception:
        answer = raw
        create_ticket = False

    # ── Étape 8 : fallback ──────────────────────────────
    if _is_rag_weak(answer):
        answer = (
            "Je ne dispose pas de cette information. "
            "Veuillez contacter le support BNM."
        )

    # ── Étape 9 : retour final ✅ ───────────────────────
    return {
        "answer": answer,
        "intent": intent,
        "create_ticket": create_ticket,
        "open_conversation": open_conv
    }