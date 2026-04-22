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
    intent = result.get("intent", "INFORMATION").upper()
 
    if intent not in ["VALIDATION", "RECLAMATION", "INFORMATION"]:
        intent = "INFORMATION"
 
    return IntentResponse(intent=intent)
 
 
@router.post("/getAnswer", response_model=AnswerResponse)
def get_answer(req: AnswerRequest):
    """
    Reçoit une question + contexte et retourne la réponse RAG +
    open_conversation + intent + context utilisé.
 
    Règle Spécifique :
    - Si open_conversation = True  → Prompt = Context (Derniers messages) + Base de Connaissance.
    - Si open_conversation = False → Prompt = Base de Connaissance UNIQUEMENT.
    """
    import json
    from service import (
        _llm_invoke_with_retry,
        _get_embeddings,
        _get_conn,
        _classify_intent,
        _is_rag_weak,
        save_message,
    )
    from langchain_core.messages import HumanMessage, SystemMessage
 
    # ── Étape 1 : construire l'historique ───────────────────────────
    context_to_use = req.context[-5:] if len(req.context) > 5 else req.context
    lines = []
    for msg in context_to_use:
        role = "Client" if msg.role == "client" else "Conseiller BNM"
        lines.append(f"{role}: {msg.content}")
    historique = "\n".join(lines)
 
    # ── Étape 2 : classifier l'intent ───────────────────────────────
    classification = _classify_intent(req.question)
    intent = classification.get("intent", "INFORMATION").upper()
 
    # ── Étape 3 : détecter open_conversation ────────────────────────
    if not req.context:
        open_conv = False
    else:
        system_check = (
            "Tu analyses si le nouveau message du client est lié à la conversation en cours "
            "ou s'il introduit un sujet complètement nouveau. "
            "Réponds UNIQUEMENT en JSON strict : "
            '{"open_conversation": true | false}'
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
 
    # ── Étape 4 : recherche pgvector ────────────────────────────────
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
 
    # ── Étape 5 : construire le Prompt ──────────────────────────────
    SYSTEM_HUMAIN = (
        "Tu es Yasmine, conseillère virtuelle de la Banque Nationale de Mauritanie (BNM). "
        "Tu réponds de façon précise, professionnelle et bienveillante, "
        "en te basant UNIQUEMENT sur les documents BNM fournis. "
        "Si l'information n'est pas dans les documents, oriente le client vers le service client."
    )
 
    if open_conv:
        rag_prompt = (
            f"Historique de la conversation :\n{historique}\n\n"
            f"Base de connaissance BNM :\n{context_docs}\n\n"
            f"Question client : {req.question}"
        )
    else:
        rag_prompt = (
            f"Base de connaissance BNM :\n{context_docs}\n\n"
            f"Nouvelle question client : {req.question}"
        )
 
    # ── Étape 6 : générer la réponse ────────────────────────────────
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
    Version enrichie :
    - Utilise intent et context depuis req
    - Décide si un ticket doit être créé
    - Retourne answer + intent + create_ticket + open_conversation
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
 
    # ── Étape 2 : intent depuis req ─────────────────────
    intent = (req.intent if hasattr(req, "intent") and req.intent else "INFORMATION").upper()
 
    # ── Étape 3 : open_conversation ─────────────────────
    if not req.context:
        open_conv = False
    else:
        system_check = (
            "Tu analyses si le nouveau message du client est lié à la conversation en cours "
            "ou s'il introduit un sujet complètement nouveau. "
            'Réponds UNIQUEMENT en JSON strict : {"open_conversation": true | false}'
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
 
    # ── Étape 5 : PROMPT ────────────────────────────────
    SYSTEM = (
        "Tu es Yasmine, conseillère virtuelle de la BNM.\n"
        "Tu dois répondre au client ET décider si un ticket doit être créé.\n\n"
 
        "Réponds STRICTEMENT en JSON valide avec exactement ces deux champs :\n"
        '{"answer": "...", "create_ticket": true | false}\n\n'
 
        "═══ RÈGLES DE DÉCISION ═══\n\n"
 
        "✅ create_ticket = TRUE si :\n"
        "  • Le client souhaite OUVRIR une NOUVELLE réclamation (problème précis et nouveau)\n"
        "  • Le client souhaite INITIER une NOUVELLE demande de validation\n\n"
 
        "❌ create_ticket = FALSE si :\n"
        "  • Le client fait un suivi d'une réclamation ou validation EXISTANTE\n"
        "  • Le client demande le statut, la progression ou la réponse d'un dossier\n"
        "  • Le client pose une question d'information générale\n"
        "  • Le message est vague ou sans objet précis\n\n"
 
        "═══ EXEMPLES ═══\n"
        "  • 'je veux faire une réclamation'           → create_ticket=false (vague, demander précision)\n"
        "  • 'mon virement du 10/04 n'est pas arrivé'  → create_ticket=true  (réclamation précise)\n"
        "  • 'je veux valider mon dossier de prêt'     → create_ticket=true  (validation précise)\n"
        "  • 'où en est ma réclamation ?'              → create_ticket=false (suivi)\n"
        "  • 'j'ai déjà soumis une réclamation'        → create_ticket=false (existant)\n"
        "  • 'c'est quoi les frais bancaires ?'        → create_ticket=false (information)\n"
    )
 
    if open_conv:
        prompt = (
            f"Intent détecté : {intent}\n\n"
            f"Historique de la conversation :\n{historique}\n\n"
            f"Base de connaissance BNM :\n{context_docs}\n\n"
            f"Message client : {req.question}"
        )
    else:
        prompt = (
            f"Intent détecté : {intent}\n\n"
            f"Base de connaissance BNM :\n{context_docs}\n\n"
            f"Message client : {req.question}"
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
 
    return {
        "answer":            answer,
        "intent":            intent,
        "create_ticket":     create_ticket,
        "open_conversation": open_conv,
    }
 
 
# ════════════════════════════════════════════════════════════════════
#  ENDPOINT RÉCLAMATION (SANS ticket_update)
# ════════════════════════════════════════════════════════════════════
 
@router.post("/reclamation")
def handle_reclamation(req: AnswerRequest):
    """
    Endpoint dédié aux réclamations.
    - Crée UNIQUEMENT nouveau_ticket si toutes les infos sont prêtes
    - Pas de ticket_update (supprimé)
    - Une seule réclamation par message
    """
    import json
    from service import (
        _llm_invoke_with_retry,
        _get_embeddings,
        _get_conn,
        _is_rag_weak,
    )
    from langchain_core.messages import HumanMessage, SystemMessage
 
    # ── Étape 1 : historique ────────────────────────────────────────
    context_to_use = req.context[-5:] if len(req.context) > 5 else req.context
    lines = []
    for msg in context_to_use:
        role = "Client" if msg.role == "client" else "Conseiller BNM"
        lines.append(f"{role}: {msg.content}")
    historique = "\n".join(lines)
 
    # ── Étape 2 : tickets existants ─────────────────────────────────
    tickets_list = getattr(req, "tickets", None) or []
    if tickets_list:
        tickets_lines = []
        for i, t in enumerate(tickets_list, 1):
            if hasattr(t, "dict"):
                t = t.dict()
            ticket_id     = t.get("id", f"#{i}")
            ticket_titre  = t.get("titre") or t.get("title") or t.get("subject", "Sans titre")
            ticket_statut = t.get("statut") or t.get("status", "Inconnu")
            ticket_date   = t.get("date") or t.get("created_at", "")
            date_str      = f" ({ticket_date})" if ticket_date else ""
            tickets_lines.append(
                f"  - Ticket {ticket_id} : {ticket_titre} | Statut : {ticket_statut}{date_str}"
            )
        tickets_section = "Tickets de réclamation existants du client :\n" + "\n".join(tickets_lines)
    else:
        tickets_section = "Tickets de réclamation existants du client : Aucun ticket existant."
 
    # ── Étape 3 : open_conversation ─────────────────────────────────
    if not req.context:
        open_conv = False
    else:
        system_check = (
            "Tu analyses si le nouveau message du client est lié à la conversation en cours. "
            'Réponds UNIQUEMENT en JSON : {"open_conversation": true | false}'
        )
        user_check = f"Conversation :\n{historique}\n\nNouveau message : {req.question}"
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
 
    # ── Étape 4 : RAG ───────────────────────────────────────────────
    q_vec = _get_embeddings().embed_query(req.question)
    cur = _get_conn().cursor()
    cur.execute(
        "SELECT content FROM documents ORDER BY embedding <-> %s::vector LIMIT 3;",
        (q_vec,),
    )
    rows = cur.fetchall()
    cur.close()
    context_docs = "\n\n".join(c for (c,) in rows)
 
    # ── Étape 5 : PROMPT RÉCLAMATION ────────────────────────────────
    SYSTEM_RECLAMATION = (
        "Tu es Yasmine, conseillère BNM. Tu gères les RÉCLAMATIONS.\n\n"
 
        "Réponds STRICTEMENT en JSON :\n"
        "{\n"
        '  "answer": "réponse au client",\n'
        '  "nouveau_ticket": "description du ticket | null"\n'
        "}\n\n"
 
        "═══ RÈGLES ═══\n\n"
 
        "1) UNE SEULE RÉCLAMATION PAR MESSAGE :\n"
        "   - Si plusieurs réclamations, traiter la PREMIÈRE uniquement\n"
        "   - Informer le client d'envoyer les autres séparément\n\n"
 
        "2) CRÉER UN TICKET UNIQUEMENT SI :\n"
        "   - Le problème est CLAIR et PRÉCIS (type, montant, date)\n"
        "   - Ce n'est pas un suivi de ticket existant\n"
        "   - Le client n'est pas déjà en attente de documents\n\n"
 
        "3) NE PAS CRÉER DE TICKET SI :\n"
        "   - Demande vague ('je veux faire une réclamation')\n"
        "   - Ticket existe déjà sur le même sujet\n"
        "   - Client est en attente de fournir des documents\n"
        "   - C'est un simple suivi ('où en est ma réclamation ?')\n\n"
 
        "4) PAS DE ticket_update - Ce champ est SUPPRIMÉ\n"
        "5) PAS DE pending_tickets - Ce champ est SUPPRIMÉ\n"
    )
 
    if open_conv:
        prompt = (
            f"{tickets_section}\n\n"
            f"Historique :\n{historique}\n\n"
            f"Base BNM :\n{context_docs}\n\n"
            f"Client : {req.question}"
        )
    else:
        prompt = (
            f"{tickets_section}\n\n"
            f"Base BNM :\n{context_docs}\n\n"
            f"Client : {req.question}"
        )
 
    # ── Étape 6 : appel LLM ─────────────────────────────────────────
    raw = _llm_invoke_with_retry([
        SystemMessage(content=SYSTEM_RECLAMATION),
        HumanMessage(content=prompt),
    ]).content.strip()
 
    # ── Étape 7 : parsing ───────────────────────────────────────────
    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        answer = result.get("answer", "")
        nouveau_ticket = result.get("nouveau_ticket", None)
    except Exception:
        answer = raw
        nouveau_ticket = None
 
    # ── Étape 8 : fallback ──────────────────────────────────────────
    if _is_rag_weak(answer):
        answer = "Je vous invite à contacter notre service client pour votre réclamation."
 
    return {
        "answer": answer,
        "intent": "RECLAMATION",
        "nouveau_ticket": nouveau_ticket,
        "open_conversation": open_conv,
    }
 
 
# ════════════════════════════════════════════════════════════════════
#  ENDPOINT VALIDATION (SANS ticket_update, selfie supprimé)
# ════════════════════════════════════════════════════════════════════
 
@router.post("/validation")
def handle_validation(req: AnswerRequest):
    """
    Endpoint dédié aux validations de compte Click.
    - Documents requis UNIQUEMENT : Numéro Click + Photo d'identité (CIN/Passeport)
    - Selfie supprimé des documents requis
    - Ne pas redemander un document déjà fourni
    - Crée UNIQUEMENT nouveau_ticket si tous les documents sont prêts
    """
    import json
    import re
    from service import (
        _llm_invoke_with_retry,
        _get_embeddings,
        _get_conn,
        _is_rag_weak,
    )
    from langchain_core.messages import HumanMessage, SystemMessage
 
    # ── Étape 1 : historique ────────────────────────────────────────
    context_to_use = req.context[-5:] if len(req.context) > 5 else req.context
    lines = []
    for msg in context_to_use:
        role = "Client" if msg.role == "client" else "Conseiller BNM"
        lines.append(f"{role}: {msg.content}")
    historique = "\n".join(lines)
 
    # ── Étape 2 : Détection des documents déjà fournis ──────────────
    docs_deja_fournis = set()
    conversation_text = " ".join([m.content.lower() for m in context_to_use])
    question_text = req.question.lower()
    full_text = conversation_text + " " + question_text
 
    # Détection Numéro Click
    click_patterns = [r'click\s*[: ]?\s*(\d+)', r'numéro click', r'numero click', r'click numéro']
    for pattern in click_patterns:
        if re.search(pattern, full_text):
            docs_deja_fournis.add("numero_click")
            break
 
    # Détection Photo d'identité / CIN / Passeport
    id_patterns = [r'cin', r'passeport', r"pièce d'identité", r'photo d\'identité', r'carte d\'identité']
    for pattern in id_patterns:
        if re.search(pattern, full_text):
            docs_deja_fournis.add("cin_passeport")
            break
 
    # DOCUMENTS REQUIS POUR VALIDATION COMPTE CLICK (SELON LA NOUVELLE RÈGLE)
    DOCS_REQUIS = ["numero_click", "cin_passeport"]  # Plus de selfie !
    docs_manquants = [doc for doc in DOCS_REQUIS if doc not in docs_deja_fournis]
 
    # ── Étape 3 : open_conversation ─────────────────────────────────
    if not req.context:
        open_conv = False
    else:
        system_check = (
            "Analyse si le message est lié à la conversation. "
            'Réponds JSON : {"open_conversation": true | false}'
        )
        user_check = f"Conversation :\n{historique}\n\nMessage : {req.question}"
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
 
    # ── Étape 4 : RAG ───────────────────────────────────────────────
    q_vec = _get_embeddings().embed_query(req.question)
    cur = _get_conn().cursor()
    cur.execute(
        "SELECT content FROM documents ORDER BY embedding <-> %s::vector LIMIT 3;",
        (q_vec,),
    )
    rows = cur.fetchall()
    cur.close()
    context_docs = "\n\n".join(c for (c,) in rows)
 
    # ── Étape 5 : PROMPT VALIDATION ─────────────────────────────────
    SYSTEM_VALIDATION = (
        "Tu es Yasmine, conseillère BNM. Tu gères les VALIDATIONS de compte Click.\n\n"
 
        "Réponds STRICTEMENT en JSON :\n"
        "{\n"
        '  "answer": "réponse au client",\n'
        '  "nouveau_ticket": "description du ticket | null",\n'
        '  "documents_requis": ["doc1", "doc2"] | []\n'
        "}\n\n"
 
        "═══ DOCUMENTS REQUIS POUR VALIDATION COMPTE CLICK ═══\n"
        "   1. numero_click (identifiant client)\n"
        "   2. cin_passeport (pièce d'identité / CIN / Passeport)\n"
        "   ⚠️ Selfie n'est PLUS requis pour la validation compte Click\n\n"
 
        "═══ RÈGLES ═══\n\n"
 
        "1) NE PAS REDEMANDER un document déjà fourni par le client\n"
        "2) DEMANDER UNIQUEMENT les documents manquants en UNE SEULE FOIS\n"
        "3) CRÉER LE TICKET (nouveau_ticket) UNIQUEMENT si TOUS les documents sont fournis\n"
        "4) Sinon, nouveau_ticket = null et lister les documents_requis manquants\n"
        "5) PAS DE ticket_update - Ce champ est SUPPRIMÉ\n"
        "6) UNE SEULE DEMANDE DE VALIDATION PAR MESSAGE\n"
    )
 
    # Ajouter l'état des documents déjà détectés
    status_docs = f"Documents déjà détectés : {', '.join(docs_deja_fournis) if docs_deja_fournis else 'aucun'}\n"
    status_docs += f"Documents manquants : {', '.join(docs_manquants) if docs_manquants else 'aucun - tout est prêt !'}"
 
    if open_conv:
        prompt = (
            f"{status_docs}\n\n"
            f"Historique :\n{historique}\n\n"
            f"Base BNM :\n{context_docs}\n\n"
            f"Client : {req.question}"
        )
    else:
        prompt = (
            f"{status_docs}\n\n"
            f"Base BNM :\n{context_docs}\n\n"
            f"Client : {req.question}"
        )
 
    # ── Étape 6 : appel LLM ─────────────────────────────────────────
    raw = _llm_invoke_with_retry([
        SystemMessage(content=SYSTEM_VALIDATION),
        HumanMessage(content=prompt),
    ]).content.strip()
 
    # ── Étape 7 : parsing ───────────────────────────────────────────
    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        answer = result.get("answer", "")
        nouveau_ticket = result.get("nouveau_ticket", None)
        documents_requis = result.get("documents_requis", docs_manquants)
    except Exception:
        answer = raw
        nouveau_ticket = None
        documents_requis = docs_manquants
 
    # ── Étape 8 : Si tous les documents sont fournis, créer le ticket ──
    if len(docs_manquants) == 0 and nouveau_ticket is None:
        nouveau_ticket = "Validation compte Click - dossier complet"
        answer = answer or "Parfait ! Tous les documents sont fournis. Je valide votre compte Click immédiatement."
 
    if _is_rag_weak(answer):
        answer = "Pour toute validation de compte Click, veuillez fournir votre numéro Click et une pièce d'identité."
 
    return {
        "answer": answer,
        "intent": "VALIDATION",
        "nouveau_ticket": nouveau_ticket,
        "documents_requis": documents_requis if nouveau_ticket is None else [],
        "open_conversation": open_conv,
    }
 
 
# ════════════════════════════════════════════════════════════════════
#  ENDPOINT INFORMATION
# ════════════════════════════════════════════════════════════════════
 
@router.post("/information")
def handle_information(req: AnswerRequest):
    """
    Endpoint dédié aux questions d'INFORMATION générale.
    """
    import json
    from service import (
        _llm_invoke_with_retry,
        _get_embeddings,
        _get_conn,
        _is_rag_weak,
    )
    from langchain_core.messages import HumanMessage, SystemMessage
 
    # ── Étape 1 : historique ────────────────────────────────────────
    context_to_use = req.context[-5:] if len(req.context) > 5 else req.context
    lines = []
    for msg in context_to_use:
        role = "Client" if msg.role == "client" else "Conseiller BNM"
        lines.append(f"{role}: {msg.content}")
    historique = "\n".join(lines)
 
    # ── Étape 2 : open_conversation ─────────────────────────────────
    if not req.context:
        open_conv = False
    else:
        system_check = (
            "Tu analyses si le nouveau message du client est lié à la conversation en cours. "
            'Réponds UNIQUEMENT en JSON : {"open_conversation": true | false}'
        )
        user_check = f"Conversation :\n{historique}\n\nNouveau message : {req.question}"
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
 
    # ── Étape 3 : RAG ───────────────────────────────────────────────
    q_vec = _get_embeddings().embed_query(req.question)
    cur = _get_conn().cursor()
    cur.execute(
        "SELECT content FROM documents ORDER BY embedding <-> %s::vector LIMIT 5;",
        (q_vec,),
    )
    rows = cur.fetchall()
    cur.close()
    context_docs = "\n\n".join(c for (c,) in rows)
 
    # ── Étape 4 : PROMPT INFORMATION ────────────────────────────────
    SYSTEM_INFORMATION = (
        "Tu es Yasmine, conseillère virtuelle de la BNM.\n"
        "Tu réponds aux questions d'INFORMATION générale des clients.\n\n"
        "Consignes :\n"
        "  • Réponds de façon claire, concise et professionnelle.\n"
        "  • Utilise UNIQUEMENT les informations de la base de connaissance BNM fournie.\n"
        "  • Si la réponse ne se trouve pas dans les documents, oriente le client\n"
        "    vers le service client BNM plutôt que d'inventer une réponse.\n"
    )
 
    if open_conv:
        prompt = (
            f"Historique :\n{historique}\n\n"
            f"Base BNM :\n{context_docs}\n\n"
            f"Question : {req.question}"
        )
    else:
        prompt = (
            f"Base BNM :\n{context_docs}\n\n"
            f"Question : {req.question}"
        )
 
    answer = _llm_invoke_with_retry([
        SystemMessage(content=SYSTEM_INFORMATION),
        HumanMessage(content=prompt),
    ]).content.strip()
 
    if _is_rag_weak(answer):
        answer = "Je ne dispose pas de cette information. N'hésitez pas à contacter notre service client BNM."
 
    return {
        "answer": answer,
        "intent": "INFORMATION",
        "open_conversation": open_conv,
    }
 
 
# ════════════════════════════════════════════════════════════════════
#  ENDPOINT DISPATCH
# ════════════════════════════════════════════════════════════════════
 
@router.post("/dispatch")
def dispatch(req: AnswerRequest):
    """
    Endpoint orchestrateur : reçoit un message, détecte l'intent
    et redirige automatiquement vers le bon endpoint métier.
    """
    from service import _classify_intent
 
    classification = _classify_intent(req.question)
    intent = classification.get("intent", "INFORMATION").upper()
 
    if intent not in ["VALIDATION", "RECLAMATION", "INFORMATION"]:
        intent = "INFORMATION"
 
    if intent == "RECLAMATION":
        result = handle_reclamation(req)
    elif intent == "VALIDATION":
        result = handle_validation(req)
    else:
        result = handle_information(req)
 
    result["intent"] = intent
    return result