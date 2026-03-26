from fastapi import APIRouter
from models import ClassifyRequest, ClassifyResponse, ChatRequest, ChatResponse
from service import _CONV_PATTERNS

router = APIRouter(prefix="/rag", tags=["RAG"])


@router.get("/health")
def rag_health():
    return {
        "status":  "ok",
        "service": "bnm-rag-service",
        "port":    8020,
    }


@router.get("/patterns")
def rag_patterns():
    """Retourne tous les patterns conversationnels disponibles."""
    return {
        "patterns": list(_CONV_PATTERNS.keys()),
        "count":    len(_CONV_PATTERNS),
    }


@router.post("/classify", response_model=ClassifyResponse)
def classify(req: ClassifyRequest):
    """
    Reçoit un message et retourne uniquement son intention (intent).
    Valeurs possibles : VALIDATION | RECLAMATION | INFORMATION
    """
    from service import _classify_intent

    result = _classify_intent(req.message)
    intent = result.get("intent", "INFORMATION")

    if intent not in ["VALIDATION", "RECLAMATION", "INFORMATION"]:
        intent = "INFORMATION"

    return ClassifyResponse(intent=intent)


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """
    Reçoit un message + contexte et retourne la réponse RAG +
    open_conversation + intent.
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
    lines = []
    for msg in req.context:
        role = "Client" if msg.role == "client" else "Conseiller BNM"
        lines.append(f"{role}: {msg.content}")
    historique = "\n".join(lines)

    # ── Étape 2 : classifier l'intent ────────────────────────────────
    classification = _classify_intent(req.message)
    intent = classification.get("intent", "INFORMATION")

    # ── Étape 3 : open_conversation ──────────────────────────────────
    if not req.context:
        open_conv = False
    else:
        system_check = (
            "Tu analyses si un message est lié "
            "à une conversation bancaire en cours."
            " Réponds UNIQUEMENT en JSON : "
            '{"open_conversation": true | false} '
            "Exemples : "
            "message='mon dossier est validé ?' → true. "
            "message='j ai envoyé ma photo' → true. "
            "message='c est quoi le sms banking' → false. "
            "message='bonjour' → false."
        )
        user_check = (
            f"Conversation en cours :\n{historique}\n\n"
            f"Nouveau message : '{req.message}'\n"
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
    q_vec = _get_embeddings().embed_query(req.message)
    cur = _get_conn().cursor()
    cur.execute(
        "SELECT content, source FROM documents "
        "ORDER BY embedding <-> %s::vector LIMIT 5;",
        (q_vec,),
    )
    rows = cur.fetchall()
    cur.close()
    context_docs = "\n\n".join(c for c, _ in rows)

    # ── Étape 5 : générer la réponse ─────────────────────────────────
    SYSTEM_HUMAIN = (
        "Tu es Yasmine, conseillère virtuelle "
        "de la Banque Nationale de Mauritanie. "
        "Tu parles avec bienveillance, clarté "
        "et professionnalisme. "
        "Tu vouvoies toujours le client. "
        "Tu commences ta réponse par une "
        "phrase d'accueil chaleureuse adaptée "
        "au contexte. "
        "Tu donnes des réponses précises basées "
        "sur les documents BNM. "
        "Tu termines toujours par une phrase "
        "proposant de l'aide supplémentaire. "
        "IMPORTANT : tu n'inventes jamais "
        "d'informations. Si tu ne sais pas, "
        "tu le dis poliment et tu proposes "
        "de mettre en relation avec un conseiller."
    )

    if open_conv:
        rag_prompt = (
            f"Historique de la conversation :\n{historique}\n\n"
            f"Documents BNM disponibles :\n{context_docs}\n\n"
            f"Le client demande maintenant : {req.message}\n\n"
            f"Réponds en tenant compte de l'historique et des documents."
        )
    else:
        rag_prompt = (
            f"Voici le contexte de la conversation avec ce client :\n"
            f"{historique}\n\n"
            f"Documents BNM sur ce sujet :\n{context_docs}\n\n"
            f"Nouvelle question du client : {req.message}\n\n"
            f"Le client change de sujet. "
            f"Réponds à sa nouvelle question en utilisant les documents BNM. "
            f"Reste attentionné et professionnel."
        )

    answer = _llm_invoke_with_retry([
        SystemMessage(content=SYSTEM_HUMAIN),
        HumanMessage(content=rag_prompt),
    ]).content

    if _is_rag_weak(answer):
        answer = (
            "Je comprends votre demande et je souhaite vous aider au mieux. "
            "Malheureusement, je ne dispose pas de cette information en ce moment. "
            "Je vous invite à contacter directement votre agence BNM ou "
            "notre service client au numéro habituel. "
            "Nous ferons tout notre possible pour vous accompagner."
        )

    # ── Sauvegarder ──────────────────────────────────────────────────
    session_id = f"chat_{uuid.uuid4().hex[:8]}"
    save_message(session_id, "user", req.message)
    save_message(session_id, "assistant", answer, intent=intent)

    return ChatResponse(
        answer=answer,
        open_conversation=open_conv,
        intent=intent,
    )
