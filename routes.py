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
 
    result = _classify_intent(req.question, req.contexte)  # contexte directement depuis req
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
#  ENDPOINT RÉCLAMATION (MODIFIÉ - supprimé type/montant)
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
 
    # ── Étape 5 : PROMPT RÉCLAMATION MODIFIÉ ────────────────────────────────
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
        "   - Le problème est CLAIR et PRÉCIS (le client a expliqué ce qui ne va pas)\n"
        "   - Ce n'est pas un suivi de ticket existant\n"
        "   - Le client n'est pas déjà en attente de documents\n\n"
 
        "3) NE PAS CRÉER DE TICKET SI :\n"
        "   - Demande vague ('je veux faire une réclamation')\n"
        "   - Ticket existe déjà sur le même sujet\n"
        "   - Client est en attente de fournir des documents\n"
        "   - C'est un simple suivi ('où en est ma réclamation ?')\n\n"
 
        "4) POUR ÊTRE EFFICACE :\n"
        "   - Pose UNE SEULE question regroupant les informations nécessaires\n"
        "   - Attends la réponse du client avant de créer le ticket\n"
        "   - Ne demande pas systématiquement montant/date/type, sois adaptatif\n\n"
 
        "5) PAS DE ticket_update - Ce champ est SUPPRIMÉ\n"
        "6) PAS DE pending_tickets - Ce champ est SUPPRIMÉ\n"
        "7) QUAND TU CRÉES LE TICKET :\n"
        "   - Il est FORMELLEMENT INTERDIT de dire 'j'ai créé un ticket' ou toute phrase contenant le mot 'ticket'\n"
        "   - Il est FORMELLEMENT INTERDIT de dire 'consultez un conseiller' ou 'contactez le service client' ou toute phrase invitant le client à consulter un agent\n"
        "   - La description dans nouveau_ticket doit être claire et précise, résumant le problème\n"
        "   - Exemple de bonne description : 'Problème d'affichage du solde Click - client ne voit pas son solde'\n"
        "   - Exemple de mauvaise description : 'réclamation client' (trop vague)\n"
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
#  ENDPOINT VALIDATION (MODIFIÉ - numéro d'identité au lieu de photo)
# ════════════════════════════════════════════════════════════════════
 
# ════════════════════════════════════════════════════════════════════
#  ENDPOINT VALIDATION — VERSION AMÉLIORÉE
# ════════════════════════════════════════════════════════════════════

@router.post("/validation")
def handle_validation(req: AnswerRequest):
    import json, re
    from service import (
        _llm_invoke_with_retry,
        _get_embeddings,
        _get_conn,
        _is_rag_weak,
    )
    from langchain_core.messages import HumanMessage, SystemMessage
 
    # ── Étape 1 : Historique ───────────────────────────────────────
    context_to_use = req.context[-5:] if len(req.context) > 5 else req.context
    lines = []
    for msg in context_to_use:
        role = "Client" if msg.role == "client" else "Conseiller BNM"
        lines.append(f"{role}: {msg.content}")
    historique = "\n".join(lines)
    question_lower = req.question.lower()
 
    # ── Étape 2 : Construire la section tickets existants ──────────
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
        tickets_section = "Tickets de validation existants du client :\n" + "\n".join(tickets_lines)
    else:
        tickets_section = "Tickets de validation existants du client : Aucun ticket existant."
 
    # ── Étape 3 : Détection sémantique LLM des documents ──────────
    SYSTEM_EXTRACT = (
        "Tu es un extracteur d'informations bancaires. "
        "Analyse le texte et retourne UNIQUEMENT ce JSON strict, sans texte autour :\n"
        '{"numero_click": "<valeur ou null>", "numero_identite": "<valeur ou null>"}\n\n'
        "Règles STRICTES :\n"
        "- numero_click : numéro de téléphone Mobile Money/Click mauritanien. "
        "  DOIT contenir EXACTEMENT 8 chiffres, commence souvent par 2, 3 ou 4. "
        "  Tout numéro avec moins ou plus de 8 chiffres est INVALIDE = retourner null. "
        "  Accepté : 'mon numéro', 'mon tel', 'click : XXXX', '22XXXXXXX'.\n"
        "- numero_identite : NNI/CIN/passeport mauritanien. "
        "  DOIT contenir EXACTEMENT 10 chiffres. "
        "  Tout numéro avec moins ou plus de 10 chiffres est INVALIDE = retourner null. "
        "  Doit être présenté comme pièce d'identité, carte nationale, CIN, NNI, passeport, "
        "  OU être le deuxième numéro fourni si le contexte ne permet pas de distinguer.\n"
        "- Si le contexte permet de distinguer les deux numéros, les assigner correctement.\n"
        "- Si le contexte ne permet PAS de distinguer : le PREMIER numéro fourni = "
        "  numero_click, le DEUXIÈME numéro fourni = numero_identite.\n"
        "- Si la valeur n'est pas présente ou invalide : retourner null (JSON null, "
        "  pas la string 'null', pas la string 'None').\n"
        "- Ne jamais retourner une string contenant le mot 'null'."
    )
    extract_prompt = (
        f"Historique de la conversation :\n{historique}\n\n"
        f"Dernier message du client : {req.question}"
    )
    try:
        raw_extract = _llm_invoke_with_retry([
            SystemMessage(content=SYSTEM_EXTRACT),
            HumanMessage(content=extract_prompt),
        ]).content.strip()
        if raw_extract.startswith("```"):
            raw_extract = raw_extract.split("```")[1]
            if raw_extract.startswith("json"):
                raw_extract = raw_extract[4:]
        extracted       = json.loads(raw_extract)
        numero_click    = extracted.get("numero_click")
        numero_identite = extracted.get("numero_identite")
        # Nettoyer les faux "null" string
        if isinstance(numero_click, str) and numero_click.strip().lower() in ("null", "none", ""):
            numero_click = None
        if isinstance(numero_identite, str) and numero_identite.strip().lower() in ("null", "none", ""):
            numero_identite = None
    except Exception:
        numero_click    = None
        numero_identite = None
 
    # ── Validation stricte des formats côté Python (filet de sécurité) ──
    # numero_click : exactement 8 chiffres
    if numero_click is not None:
        digits_click = re.sub(r'\D', '', str(numero_click))
        if len(digits_click) != 8:
            numero_click = None
 
    # numero_identite : exactement 10 chiffres
    if numero_identite is not None:
        digits_id = re.sub(r'\D', '', str(numero_identite))
        if len(digits_id) != 10:
            numero_identite = None
 
    docs_deja_fournis = set()
    if numero_click:
        docs_deja_fournis.add("numero_click")
    if numero_identite:
        docs_deja_fournis.add("numero_identite")
 
    DOCS_REQUIS    = ["numero_click", "numero_identite"]
    docs_manquants = [doc for doc in DOCS_REQUIS if doc not in docs_deja_fournis]
 
    # ── Étape 4 : Détection de demandes multiples ─────────────────
    SYSTEM_MULTI = (
        "Analyse si le message contient PLUSIEURS demandes de validation DISTINCTES "
        "(ex : valider compte A ET compte B, deux numéros Click différents). "
        "IMPORTANT : donner son numéro de téléphone ET sa pièce d'identité = "
        "UNE SEULE demande, pas deux. "
        'Réponds JSON strict : {"multiple_validations": true | false}'
    )
    try:
        raw_multi = _llm_invoke_with_retry([
            SystemMessage(content=SYSTEM_MULTI),
            HumanMessage(content=req.question),
        ]).content.strip()
        if raw_multi.startswith("```"):
            raw_multi = raw_multi.split("```")[1]
            if raw_multi.startswith("json"):
                raw_multi = raw_multi[4:]
        is_multiple = json.loads(raw_multi).get("multiple_validations", False)
    except Exception:
        is_multiple = False
 
    # ── Étape 5 : open_conversation ───────────────────────────────
    if not req.context:
        open_conv = False
    else:
        system_check = (
            "Analyse si le message est lié à la conversation en cours. "
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
 
    # ── Étape 6 : RAG ─────────────────────────────────────────────
    q_vec = _get_embeddings().embed_query(req.question)
    cur   = _get_conn().cursor()
    cur.execute(
        "SELECT content FROM documents ORDER BY embedding <-> %s::vector LIMIT 3;",
        (q_vec,),
    )
    rows = cur.fetchall()
    cur.close()
    context_docs = "\n\n".join(c for (c,) in rows)
 
    # ── Étape 7 : État des documents ──────────────────────────────
    doc_labels = {
        "numero_click":    f"numéro Click ({numero_click})"         if numero_click    else "numéro Click",
        "numero_identite": f"numéro d'identité ({numero_identite})" if numero_identite else "numéro d'identité",
    }
    status_docs = (
        f"Documents déjà détectés : "
        f"{', '.join(doc_labels[d] for d in docs_deja_fournis) if docs_deja_fournis else 'aucun'}\n"
        f"Documents manquants : "
        f"{', '.join(doc_labels[d] for d in docs_manquants) if docs_manquants else 'aucun - tout est prêt !'}"
    )
 
    # Note demandes multiples — injectée dans le prompt ET utilisée comme verrou Python
    multiple_note = (
        "\n⚠️ Le client envoie plusieurs demandes. "
        "Traiter UNIQUEMENT la première et lui demander d'envoyer les autres séparément.\n"
        if is_multiple else ""
    )
 
    # ── Étape 8 : Prompt LLM ──────────────────────────────────────
    SYSTEM_VALIDATION = (
        "Tu es Yasmine, conseillère BNM. Tu gères les VALIDATIONS de compte Click.\n\n"
 
        "Réponds STRICTEMENT en JSON :\n"
        "{\n"
        '  "answer": "réponse au client",\n'
        '  "nouveau_ticket": null,\n'
        '  "documents_requis": ["doc1"] | []\n'
        "}\n\n"
 
        "═══ GESTION DES TICKETS EXISTANTS ═══\n"
        "Tu as accès à la liste complète des tickets de validation du client dans le prompt.\n"
        "- Si le client demande le statut ou l'avancement → réponds en te basant sur "
        "  les tickets existants (titre, statut, date). Sois précis et naturel.\n"
        "- Si un ticket existe déjà pour la même demande → ne pas créer de nouveau ticket, "
        "  informer le client et lui communiquer le statut du ticket existant.\n"
        "- Si aucun ticket existant → procéder à la collecte des documents.\n\n"
 
        "🚨 RÈGLE ABSOLUE — CRÉATION DE TICKET 🚨\n"
        "Tu te fies EXCLUSIVEMENT à la variable 'Documents manquants' du prompt.\n"
        "Si 'Documents manquants' contient au moins un élément → "
        "nouveau_ticket DOIT être null (JSON null, PAS la string 'null').\n"
        "Si 'Documents manquants' = 'aucun - tout est prêt !' → "
        "nouveau_ticket = description courte et précise du dossier.\n\n"
 
        "FORMATS VALIDES DES DOCUMENTS :\n"
        "- numéro Click : exactement 8 chiffres.\n"
        "- numéro d'identité : exactement 10 chiffres.\n"
        "Si un numéro fourni ne respecte pas ces formats, demander au client de le corriger.\n\n"
 
        "DOCUMENTS REQUIS : numero_click + numero_identite (les deux obligatoires).\n\n"
 
        "INTERDICTIONS ABSOLUES :\n"
        "- Ne JAMAIS retourner la string 'null' ou '| null' dans nouveau_ticket.\n"
        "- Ne JAMAIS créer un ticket si un document manque.\n"
        "- Ne JAMAIS demander un document déjà listé dans 'Documents déjà détectés'.\n"
        "- Ne JAMAIS rediriger le client vers le service client pour une validation.\n"
        "- Ne JAMAIS mentionner le mot 'ticket' dans la réponse au client.\n\n"
 
        "QUAND TOUT EST PRÊT (nouveau_ticket non null) :\n"
        "- Confirmer chaleureusement la prise en charge.\n"
        "- Mentionner un délai de traitement de 24 à 48 heures.\n"
    )
 
    if open_conv:
        prompt = (
            f"{tickets_section}\n\n"
            f"{status_docs}\n{multiple_note}\n"
            f"Historique :\n{historique}\n\n"
            f"Base BNM :\n{context_docs}\n\n"
            f"Client : {req.question}"
        )
    else:
        prompt = (
            f"{tickets_section}\n\n"
            f"{status_docs}\n{multiple_note}\n"
            f"Base BNM :\n{context_docs}\n\n"
            f"Client : {req.question}"
        )
 
    # ── Étape 9 : Appel LLM ───────────────────────────────────────
    raw = _llm_invoke_with_retry([
        SystemMessage(content=SYSTEM_VALIDATION),
        HumanMessage(content=prompt),
    ]).content.strip()
 
    # ── Étape 10 : Parsing + nettoyage des faux "null" string ─────
    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result           = json.loads(raw)
        answer           = result.get("answer", "")
        nouveau_ticket   = result.get("nouveau_ticket", None)
        documents_requis = result.get("documents_requis", docs_manquants)
 
        # Nettoyer les faux "null" string que le LLM génère parfois
        if isinstance(nouveau_ticket, str):
            cleaned = nouveau_ticket.strip().lower()
            if (
                cleaned in ("null", "none", "")
                or cleaned.endswith("| null")
                or cleaned.endswith("|null")
                or "besoin de" in cleaned
                or "manquant"  in cleaned
                or "fournir"   in cleaned
                or "veuillez"  in cleaned
            ):
                nouveau_ticket = None
 
    except Exception:
        answer           = raw
        nouveau_ticket   = None
        documents_requis = docs_manquants
 
    # ── Étape 11 : Verrous Python — priorité absolue sur le LLM ───
 
    # Verrou 1 : documents manquants → pas de ticket
    if len(docs_manquants) > 0:
        nouveau_ticket = None
 
    # Verrou 2 : demandes multiples → pas de ticket pour cette passe
    elif is_multiple:
        nouveau_ticket = None
 
    # Safety net : tous les docs sont là, le LLM a oublié de créer le ticket
    elif len(docs_manquants) == 0 and nouveau_ticket is None:
        click_val = f" ({numero_click})"    if numero_click    else ""
        id_val    = f" ({numero_identite})" if numero_identite else ""
        nouveau_ticket = (
            f"Validation compte Click{click_val} — "
            f"numéro d'identité{id_val} — dossier complet"
        )
        if not answer:
            answer = (
                "Parfait ! J'ai bien reçu tous vos documents. "
                "Votre demande de validation est en cours de traitement. "
                "Vous recevrez une confirmation dans les 24 à 48 heures."
            )
 
    # ── Étape 12 : Fallback ───────────────────────────────────────
    if _is_rag_weak(answer):
        answer = (
            "Pour valider votre compte Click, j'ai besoin de votre numéro Click "
            "et de votre numéro d'identité nationale."
        )
 
    return {
        "answer":            answer,
        "intent":            "VALIDATION",
        "nouveau_ticket":    nouveau_ticket,
        "documents_requis":  documents_requis if nouveau_ticket is None else [],
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