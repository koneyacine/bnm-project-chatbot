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
 
    # ── Étape 2 : Tickets existants ────────────────────────────────
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
 
    # ── Étape 3 : Extraction sémantique LLM ───────────────────────
    #
    #  Trois champs retournés par le LLM :
    #    - sujet_reclamation  : type/thème du problème
    #    - description_detail : ce qui s'est passé (même court)
    #    - info_suffisante    : true si le contexte global est assez clair
    #                           pour créer le ticket sans poser de question
    # ──────────────────────────────────────────────────────────────
 
    SYSTEM_EXTRACT = (
        "Tu es un extracteur d'informations bancaires. "
        "Analyse la conversation et retourne UNIQUEMENT ce JSON strict, sans texte autour :\n"
        "{\n"
        '  "sujet_reclamation": "<valeur ou null>",\n'
        '  "description_detail": "<valeur ou null>",\n'
        '  "info_suffisante": true\n'
        "}\n\n"
 
        "Regles STRICTES :\n"
        "- sujet_reclamation : le THEME ou TYPE du probleme du client.\n"
        "  Exemples valides : 'solde Click incorrect', 'virement non recu',\n"
        "  'carte bloquee', 'frais injustifies', 'probleme de connexion'.\n"
        "  Retourner null si le client dit juste 'je veux faire une reclamation'\n"
        "  sans preciser aucun sujet.\n"
        "- description_detail : tout texte du client qui decrit ce qui s'est passe,\n"
        "  meme une phrase tres courte ('mon virement n est pas arrive',\n"
        "  'j ai ete debite deux fois').\n"
        "  SOIS PERMISSIF : ne pas exiger de montant, de date ou de details supplementaires.\n"
        "  Retourner null UNIQUEMENT si le client n a absolument rien decrit\n"
        "  (ex : 'je veux faire une reclamation' sans aucun detail).\n"
        "- info_suffisante : evalue l ENSEMBLE de la conversation (historique + message actuel).\n"
        "  Mettre true si on comprend clairement QUEL est le probleme et CE QUI s est passe,\n"
        "  meme sans montant ni date precise — suffisant pour ouvrir un dossier.\n"
        "  Mettre false si le probleme reste flou ou si le client n a rien precise du tout.\n"
        "  Exemples true  : 'mon virement de hier n est pas arrive',\n"
        "                   'j ai ete debite deux fois ce matin',\n"
        "                   'mon solde Click est incorrect depuis lundi'.\n"
        "  Exemples false : 'je veux faire une reclamation',\n"
        "                   'j ai un probleme', 'ca ne marche pas'.\n"
        "- Si une valeur texte est absente : retourner null\n"
        "  (JSON null, pas la string 'null', pas la string 'None').\n"
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
        extracted          = json.loads(raw_extract)
        sujet_reclamation  = extracted.get("sujet_reclamation")
        description_detail = extracted.get("description_detail")
        info_suffisante    = bool(extracted.get("info_suffisante", False))
 
        # Nettoyer les faux "null" string
        if isinstance(sujet_reclamation, str) and sujet_reclamation.strip().lower() in ("null", "none", ""):
            sujet_reclamation = None
        if isinstance(description_detail, str) and description_detail.strip().lower() in ("null", "none", ""):
            description_detail = None
 
    except Exception:
        sujet_reclamation  = None
        description_detail = None
        info_suffisante    = False
 
    # ── Étape 4 : État des champs + statut global ──────────────────
    #
    #  dossier_complet = True si le LLM juge les infos suffisantes
    #  (info_suffisante), indépendamment des champs null/non-null.
    #  C'est ce flag qui commande la création du ticket.
    # ──────────────────────────────────────────────────────────────
    CHAMPS_REQUIS = ["sujet_reclamation", "description_detail"]
 
    champs_deja_fournis = set()
    if sujet_reclamation:
        champs_deja_fournis.add("sujet_reclamation")
    if description_detail:
        champs_deja_fournis.add("description_detail")
 
    champs_manquants = [c for c in CHAMPS_REQUIS if c not in champs_deja_fournis]
 
    champ_labels = {
        "sujet_reclamation":  f"sujet ({sujet_reclamation})"              if sujet_reclamation  else "sujet de la reclamation",
        "description_detail": f"description ({description_detail[:60]}...)" if description_detail else "description du probleme",
    }
 
    # Statut injecté dans le prompt du LLM principal
    if info_suffisante:
        status_champs = (
            f"Informations deja collectees : "
            f"{', '.join(champ_labels[c] for c in champs_deja_fournis) if champs_deja_fournis else 'aucune'}\n"
            f"Informations manquantes : aucune — dossier complet !\n"
            f"[info_suffisante = TRUE — creer le ticket immediatement, ne pas poser de question]"
        )
    else:
        status_champs = (
            f"Informations deja collectees : "
            f"{', '.join(champ_labels[c] for c in champs_deja_fournis) if champs_deja_fournis else 'aucune'}\n"
            f"Informations manquantes : "
            f"{', '.join(champ_labels[c] for c in champs_manquants) if champs_manquants else 'aucune — dossier complet !'}\n"
            f"[info_suffisante = FALSE — poser une question sur ce qui manque]"
        )
 
    # ── Étape 5 : Détection de réclamations multiples ─────────────
    SYSTEM_MULTI = (
        "Analyse si le message contient PLUSIEURS reclamations DISTINCTES "
        "(ex : probleme de virement ET probleme de carte). "
        "IMPORTANT : donner le sujet ET les details d un meme probleme = "
        "UNE SEULE reclamation, pas deux. "
        'Reponds JSON strict : {"multiple_reclamations": true | false}'
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
        is_multiple = json.loads(raw_multi).get("multiple_reclamations", False)
    except Exception:
        is_multiple = False
 
    # ── Étape 6 : open_conversation ───────────────────────────────
    if not req.context:
        open_conv = False
    else:
        system_check = (
            "Analyse si le message est lie a la conversation en cours. "
            'Reponds JSON : {"open_conversation": true | false}'
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
 
    # ── Étape 7 : RAG ─────────────────────────────────────────────
    q_vec = _get_embeddings().embed_query(req.question)
    cur   = _get_conn().cursor()
    cur.execute(
        "SELECT content FROM documents ORDER BY embedding <-> %s::vector LIMIT 3;",
        (q_vec,),
    )
    rows = cur.fetchall()
    cur.close()
    context_docs = "\n\n".join(c for (c,) in rows)
 
    # ── Étape 8 : Note demandes multiples ─────────────────────────
    multiple_note = (
        "\n ATTENTION : Le client envoie plusieurs reclamations distinctes. "
        "Traiter UNIQUEMENT la premiere et lui demander d envoyer les autres separement.\n"
        if is_multiple else ""
    )
 
    # ── Étape 9 : Prompt LLM principal ────────────────────────────
    SYSTEM_RECLAMATION = (
        "Tu es Yasmine, conseillere BNM. Tu geres les RECLAMATIONS.\n\n"
 
        "Reponds STRICTEMENT en JSON :\n"
        "{\n"
        '  "answer": "reponse au client",\n'
        '  "nouveau_ticket": null\n'
        "}\n\n"
 
        "=== GESTION DES TICKETS EXISTANTS ===\n"
        "Tu as acces a la liste complete des tickets de reclamation du client dans le prompt.\n"
        "- Si le client demande le statut ou l avancement → reponds en te basant sur "
        "  les tickets existants (titre, statut, date). Sois precis et naturel.\n"
        "- Si un ticket existe deja pour la meme reclamation → ne pas creer de nouveau ticket, "
        "  informer le client et lui communiquer le statut du ticket existant.\n"
        "- Si aucun ticket existant → proceder a la collecte des informations.\n\n"
 
        "REGLE ABSOLUE — CREATION DE TICKET\n"
        "Tu te fies EXCLUSIVEMENT au flag [info_suffisante] dans le prompt.\n\n"
        "CAS 1 — [info_suffisante = TRUE] :\n"
        "  → nouveau_ticket = description courte et precise de la reclamation.\n"
        "  → Ne pose AUCUNE question. Confirme la prise en charge directement.\n\n"
        "CAS 2 — [info_suffisante = FALSE] :\n"
        "  → nouveau_ticket = null.\n"
        "  → Pose UNE question ciblée sur ce qui manque.\n"
        "  → Ne redemande JAMAIS ce qui est deja dans 'Informations deja collectees'.\n\n"
 
        "INTERDICTIONS ABSOLUES :\n"
        "- Ne JAMAIS retourner la string 'null' ou '| null' dans nouveau_ticket.\n"
        "- Ne JAMAIS creer un ticket si info_suffisante = FALSE.\n"
        "- Ne JAMAIS poser une question si info_suffisante = TRUE.\n"
        "- Ne JAMAIS redemander une information deja collectee.\n"
        "- Ne JAMAIS rediriger le client vers le service client.\n"
        "- Ne JAMAIS mentionner le mot 'ticket' dans la reponse au client.\n\n"
 
        "QUAND TOUT EST PRET (nouveau_ticket non null) :\n"
        "- Confirmer chaleureusement la prise en charge de la reclamation.\n"
        "- Mentionner un delai de traitement de 48 a 72 heures.\n"
        "- Ne pas mentionner de ticket ni de conseiller.\n"
    )
 
    if open_conv:
        prompt = (
            f"{tickets_section}\n\n"
            f"{status_champs}\n{multiple_note}\n"
            f"Historique :\n{historique}\n\n"
            f"Base BNM :\n{context_docs}\n\n"
            f"Client : {req.question}"
        )
    else:
        prompt = (
            f"{tickets_section}\n\n"
            f"{status_champs}\n{multiple_note}\n"
            f"Base BNM :\n{context_docs}\n\n"
            f"Client : {req.question}"
        )
 
    # ── Étape 10 : Appel LLM ──────────────────────────────────────
    raw = _llm_invoke_with_retry([
        SystemMessage(content=SYSTEM_RECLAMATION),
        HumanMessage(content=prompt),
    ]).content.strip()
 
    # ── Étape 11 : Parsing + nettoyage des faux "null" string ─────
    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result         = json.loads(raw)
        answer         = result.get("answer", "")
        nouveau_ticket = result.get("nouveau_ticket", None)
 
        # Nettoyer les faux "null" string que le LLM genere parfois
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
        answer         = raw
        nouveau_ticket = None
 
    # ── Étape 12 : Verrous Python — priorité absolue sur le LLM ───
 
    # Verrou 1 : info pas suffisante selon le LLM → pas de ticket
    if not info_suffisante:
        nouveau_ticket = None
 
    # Verrou 2 : demandes multiples → pas de ticket pour cette passe
    elif is_multiple:
        nouveau_ticket = None
 
    # Safety net : info suffisante mais le LLM a oublie de creer le ticket
    elif info_suffisante and nouveau_ticket is None:
        sujet_val = sujet_reclamation or "reclamation"
        desc_val  = (
            (description_detail[:80] + "...")
            if description_detail and len(description_detail) > 80
            else (description_detail or "")
        )
        nouveau_ticket = f"{sujet_val} — {desc_val}"
        if not answer:
            answer = (
                "Merci pour ces informations. Votre reclamation a bien ete prise en charge. "
                "Notre equipe vous contactera dans les 48 a 72 heures."
            )
 
    # ── Étape 13 : Fallback ───────────────────────────────────────
    if _is_rag_weak(answer):
        answer = (
            "Pour traiter votre reclamation, pourriez-vous me preciser "
            "le probleme rencontre ?"
        )
 
    return {
        "answer":            answer,
        "intent":            "RECLAMATION",
        "nouveau_ticket":    nouveau_ticket,
        "champs_manquants":  champs_manquants if nouveau_ticket is None else [],
        "info_suffisante":   info_suffisante,
        "open_conversation": open_conv,
    } 
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
    #
    # LOGIQUE EN 2 PASSES :
    #
    # PASSE A — Quel document le bot attendait-il ?
    #   On regarde le dernier message du conseiller dans l'historique.
    #   S'il demandait précisément le numéro click OU le numéro d'identité,
    #   on le note → ça sert à interpréter la réponse ambiguë du client.
    #
    # PASSE B — Extraction enrichie
    #   Retourne non seulement la valeur mais aussi si un numéro a été fourni
    #   mais est invalide (pour que Yasmine puisse le dire naturellement).
    #   Champs :
    #     numero_click         : valeur valide ou null
    #     numero_identite      : valeur valide ou null
    #     click_invalide       : true si un numéro click a été fourni mais est invalide
    #     identite_invalide    : true si un numéro identité a été fourni mais est invalide
    #     doc_attendu_inconnu  : true si le client a fourni un numéro sans qu'on sache
    #                            à quel champ il correspond ET le bot ne demandait rien
    #                            de précis → il faut poser la question
 
    # -- Passe A : contexte conversationnel complet --
    #
    # On récupère :
    # 1. dernier_msg_conseiller → ce que le bot attendait
    # 2. dernier_msg_client_precedent → le message client AVANT le message actuel
    #    (utile si le client précise "c'est mon click" sans renvoyer le numéro)
    #
    dernier_msg_conseiller       = ""
    dernier_msg_client_precedent = ""
 
    for msg in reversed(context_to_use):
        if msg.role != "client" and not dernier_msg_conseiller:
            dernier_msg_conseiller = msg.content
        elif msg.role == "client" and dernier_msg_conseiller and not dernier_msg_client_precedent:
            dernier_msg_client_precedent = msg.content
            break
 
    SYSTEM_DOC_ATTENDU = (
        "Tu analyses une conversation bancaire et tu retournes ce JSON strict, sans texte autour :\n"
        "{\n"
        '  "doc_attendu": "numero_click" | "numero_identite" | "les_deux" | "aucun",\n'
        '  "numero_recupere": "<numéro brut ou null>"\n'
        "}\n\n"
        "doc_attendu — ce que le conseiller attendait dans son dernier message :\n"
        "- 'numero_click'   : demandait le numéro Click / Mobile Money\n"
        "- 'numero_identite': demandait la pièce d'identité / NNI / CIN / passeport\n"
        "- 'les_deux'       : demandait les deux\n"
        "- 'aucun'          : ne demandait aucun document précis\n\n"
        "numero_recupere — UNIQUEMENT dans ce cas précis :\n"
        "- Le conseiller avait demandé de PRÉCISER à quoi correspond un numéro\n"
        "  (ex: 'est-ce votre click ou votre identité ?')\n"
        "- ET le message actuel du client est une précision SANS nouveau numéro\n"
        "  (ex: 'c est mon click', 'identité', 'c est pour le click')\n"
        "- Dans ce cas : retourner le numéro brut trouvé dans le message client précédent.\n"
        "- Dans TOUS les autres cas : retourner null.\n"
        "- JSON null uniquement (pas la string 'null').\n"
    )
 
    doc_attendu     = "aucun"
    numero_recupere = None
 
    if dernier_msg_conseiller:
        try:
            passe_a_prompt = (
                f"Dernier message du conseiller : {dernier_msg_conseiller}\n\n"
                f"Message client précédent : {dernier_msg_client_precedent or 'aucun'}\n\n"
                f"Message actuel du client : {req.question}"
            )
            raw_da = _llm_invoke_with_retry([
                SystemMessage(content=SYSTEM_DOC_ATTENDU),
                HumanMessage(content=passe_a_prompt),
            ]).content.strip()
            if raw_da.startswith("```"):
                raw_da = raw_da.split("```")[1]
                if raw_da.startswith("json"):
                    raw_da = raw_da[4:]
            parsed_da       = json.loads(raw_da)
            doc_attendu     = parsed_da.get("doc_attendu", "aucun")
            numero_recupere = parsed_da.get("numero_recupere")
            if isinstance(numero_recupere, str) and numero_recupere.strip().lower() in ("null", "none", ""):
                numero_recupere = None
        except Exception:
            doc_attendu     = "aucun"
            numero_recupere = None
 
    # -- Passe B : extraction enrichie --
    #
    # RÈGLE FONDAMENTALE (corrige Bug 1 & 2) :
    # ─────────────────────────────────────────
    # Quand doc_attendu = "les_deux" ou "aucun" et que le client envoie un numéro
    # sans mot-clé explicite → on NE devine PAS, on NE assigne PAS.
    # On extrait juste le(s) numéro(s) brut(s) présents dans le message.
    # C'est Python qui décidera quoi faire selon doc_attendu (voir après).
    #
    # Quand doc_attendu = "numero_click" ou "numero_identite" (bot attendait UN seul) :
    # → le numéro fourni appartient à ce champ, valide ou invalide.
    # → invalide = on le signale, on ne l'assigne pas à l'autre champ.
 
    SYSTEM_EXTRACT = (
        "Tu es un extracteur d'informations bancaires.\n"
        "Analyse UNIQUEMENT le dernier message du client et retourne ce JSON strict :\n"
        "{\n"
        '  "numero_click": "<valeur brute ou null>",\n'
        '  "numero_identite": "<valeur brute ou null>",\n'
        '  "numeros_bruts": ["<num1>", "<num2>"]'
        "}\n\n"
 
        "Règles STRICTES selon doc_attendu fourni dans le prompt :\n\n"
 
        "CAS 1 — doc_attendu = 'numero_click' :\n"
        "  → Le numéro fourni par le client (même sans mot-clé) va dans numero_click.\n"
        "  → numero_identite = null.\n"
        "  → Ne jamais mettre ce numéro dans numero_identite même s'il a 10 chiffres.\n\n"
 
        "CAS 2 — doc_attendu = 'numero_identite' :\n"
        "  → Le numéro fourni par le client (même sans mot-clé) va dans numero_identite.\n"
        "  → numero_click = null.\n"
        "  → Ne jamais mettre ce numéro dans numero_click même s'il a 8 chiffres.\n\n"
 
        "CAS 3 — doc_attendu = 'les_deux' ou 'aucun' :\n"
        "  → NE PAS assigner de numéro à numero_click ni numero_identite.\n"
        "  → Mettre les deux à null.\n"
        "  → Mettre TOUS les numéros trouvés dans numeros_bruts (liste de strings).\n"
        "  → Si le client utilise un mot-clé explicite ('click', 'NNI', 'identité', etc.)\n"
        "    alors seulement tu peux assigner au bon champ.\n\n"
 
        "numeros_bruts : toujours lister tous les numéros trouvés dans le message,\n"
        "  qu'ils soient assignés ou non. Liste vide [] si aucun numéro.\n\n"
 
        "Règle null : JSON null uniquement (pas la string 'null').\n"
        "Ne retourne aucun texte en dehors du JSON."
    )
 
    extract_prompt = (
        f"doc_attendu (ce que le bot attendait) : {doc_attendu}\n\n"
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
        extracted        = json.loads(raw_extract)
        numero_click     = extracted.get("numero_click")
        numero_identite  = extracted.get("numero_identite")
        numeros_bruts    = extracted.get("numeros_bruts") or []
        # Nettoyer les faux "null" string
        if isinstance(numero_click, str) and numero_click.strip().lower() in ("null", "none", ""):
            numero_click = None
        if isinstance(numero_identite, str) and numero_identite.strip().lower() in ("null", "none", ""):
            numero_identite = None
        numeros_bruts = [str(n).strip() for n in numeros_bruts if str(n).strip()]
    except Exception:
        numero_click   = None
        numero_identite = None
        numeros_bruts  = []
 
    # ── Injection numero_recupere (Passe A) dans numeros_bruts ───────
    # Si le client a précisé "c'est mon click" sans renvoyer de numéro,
    # la Passe A a récupéré le numéro brut du message précédent.
    # On l'injecte ici pour que la validation Python puisse l'assigner.
    if numero_recupere is not None and not numeros_bruts and numero_click is None and numero_identite is None:
        nr = re.sub(r'\D', '', str(numero_recupere))
        if nr:
            numeros_bruts = [nr]
 
 
    # ── Validation stricte des formats côté Python ────────────────
    #
    # BUG 1 & 2 CORRIGÉS ICI :
    # Si doc_attendu est précis (un seul champ attendu) :
    #   → on valide le numéro pour CE champ uniquement
    #   → invalide = on signale UNIQUEMENT pour ce champ, jamais pour l'autre
    #
    # Si doc_attendu = "les_deux" ou "aucun" :
    #   → on ne peut pas déterminer le champ → on pose la question au client
    #   → on utilise numeros_bruts pour signaler qu'un numéro a été fourni
    #     mais qu'on ne sait pas à quoi il correspond
 
    click_invalide    = False
    identite_invalide = False
    numero_ambigu     = False   # True = numéro fourni mais champ inconnu → poser la question
 
    if doc_attendu == "numero_click":
        # Le numéro fourni appartient forcément au click
        if numero_click is not None:
            d = re.sub(r'\D', '', str(numero_click))
            if len(d) != 8:
                numero_click   = None
                click_invalide = True
        elif numeros_bruts:
            # LLM n'a pas assigné mais un numéro brut existe → on tente
            d = re.sub(r'\D', '', numeros_bruts[0])
            if len(d) == 8:
                numero_click = d
            else:
                click_invalide = True
 
    elif doc_attendu == "numero_identite":
        # Le numéro fourni appartient forcément à l'identité
        if numero_identite is not None:
            d = re.sub(r'\D', '', str(numero_identite))
            if len(d) != 10:
                numero_identite    = None
                identite_invalide  = True
        elif numeros_bruts:
            d = re.sub(r'\D', '', numeros_bruts[0])
            if len(d) == 10:
                numero_identite = d
            else:
                identite_invalide = True
 
    else:
        # doc_attendu = "les_deux" ou "aucun"
        # On accepte uniquement les numéros avec mot-clé explicite (déjà assignés par LLM)
        if numero_click is not None:
            d = re.sub(r'\D', '', str(numero_click))
            if len(d) != 8:
                numero_click   = None
                click_invalide = True
        if numero_identite is not None:
            d = re.sub(r'\D', '', str(numero_identite))
            if len(d) != 10:
                numero_identite    = None
                identite_invalide  = True
        # Si des numéros bruts existent sans avoir été assignés → ambiguïté
        if numeros_bruts and numero_click is None and numero_identite is None:
            numero_ambigu = True   # bot doit poser la question, pas deviner
 
    # -- Passe C : relecture cumulative de l'historique ─────────────
    #
    # BUG 3 CORRIGÉ :
    # Ancienne version cherchait les numéros "confirmés explicitement" par le conseiller.
    # Le conseiller ne répète jamais le numéro — il passe juste au document suivant.
    #
    # Nouvelle logique : on cherche les numéros fournis par le CLIENT dans l'historique
    # passé, pour lesquels le bot N'A PAS redemandé de correction dans sa réponse suivante.
    # = numéro fourni + bot a continué → numéro accepté implicitement.
 
    SYSTEM_HISTORIQUE = (
        "Tu es un extracteur d'informations bancaires.\n"
        "Analyse l'historique d'une conversation TOUR PAR TOUR.\n"
        "Identifie les numéros fournis par le CLIENT qui ont été ACCEPTÉS IMPLICITEMENT,\n"
        "c'est-à-dire : le client a donné un numéro ET le bot n'a PAS demandé de le corriger\n"
        "dans sa réponse immédiatement suivante (il a continué vers autre chose).\n\n"
        "Retourne UNIQUEMENT ce JSON strict :\n"
        '{"numero_click": "<8 chiffres valides ou null>", "numero_identite": "<10 chiffres valides ou null>"}\n\n'
        "Règles :\n"
        "- numero_click    : EXACTEMENT 8 chiffres, accepté implicitement par le bot.\n"
        "- numero_identite : EXACTEMENT 10 chiffres, accepté implicitement par le bot.\n"
        "- Si le bot a dit 'vérifiez', 'ressaisir', 'incorrect', 'invalide' après ce numéro → null.\n"
        "- Si le numéro n'a pas été fourni ou n'est pas valide → null.\n"
        "- JSON null uniquement (pas la string 'null').\n"
    )
 
    numero_click_hist    = None
    numero_identite_hist = None
 
    # On exclut le dernier message client (déjà traité par Passe B)
    historique_precedent = context_to_use[:-1] if context_to_use else []
    if historique_precedent:
        lines_hist = []
        for msg in historique_precedent:
            role = "Client" if msg.role == "client" else "Conseiller BNM"
            lines_hist.append(f"{role}: {msg.content}")
        historique_txt = "\n".join(lines_hist)
 
        try:
            raw_hist = _llm_invoke_with_retry([
                SystemMessage(content=SYSTEM_HISTORIQUE),
                HumanMessage(content=f"Historique :\n{historique_txt}"),
            ]).content.strip()
            if raw_hist.startswith("```"):
                raw_hist = raw_hist.split("```")[1]
                if raw_hist.startswith("json"):
                    raw_hist = raw_hist[4:]
            extracted_hist       = json.loads(raw_hist)
            numero_click_hist    = extracted_hist.get("numero_click")
            numero_identite_hist = extracted_hist.get("numero_identite")
            if isinstance(numero_click_hist, str) and numero_click_hist.strip().lower() in ("null", "none", ""):
                numero_click_hist = None
            if isinstance(numero_identite_hist, str) and numero_identite_hist.strip().lower() in ("null", "none", ""):
                numero_identite_hist = None
        except Exception:
            numero_click_hist    = None
            numero_identite_hist = None
 
        # Validation Python de ce qui vient de l'historique
        if numero_click_hist is not None:
            d = re.sub(r'\D', '', str(numero_click_hist))
            if len(d) != 8:
                numero_click_hist = None
        if numero_identite_hist is not None:
            d = re.sub(r'\D', '', str(numero_identite_hist))
            if len(d) != 10:
                numero_identite_hist = None
 
    # Fusion : tour actuel prioritaire, historique comble ce qui manque
    if numero_click is None and numero_click_hist is not None:
        numero_click   = numero_click_hist
        click_invalide = False
 
    if numero_identite is None and numero_identite_hist is not None:
        numero_identite    = numero_identite_hist
        identite_invalide  = False
 
    docs_deja_fournis = set()
    if numero_click:
        docs_deja_fournis.add("numero_click")
    if numero_identite:
        docs_deja_fournis.add("numero_identite")
 
    DOCS_REQUIS    = ["numero_click", "numero_identite"]
    docs_manquants = [doc for doc in DOCS_REQUIS if doc not in docs_deja_fournis]
 
    # ── Note d'invalidité / ambiguïté injectée dans le prompt ────────
    invalidity_note = ""
    if numero_ambigu:
        if len(numeros_bruts) == 1:
            invalidity_note += (
                f"\n⚠️ NUMÉRO AMBIGU (1 seul numéro fourni : {numeros_bruts[0]}) : "
                "le client a fourni UN SEUL numéro sans préciser à quoi il correspond. "
                "Demande-lui simplement : est-ce son numéro Click ou son numéro d'identité ? "
                "Ne parle PAS de 'deux numéros'. Ne demande PAS 'lequel est lequel'. "
                "Il n'y a qu'un seul numéro — pose une question simple et claire.\n"
            )
        else:
            invalidity_note += (
                f"\n⚠️ NUMÉRO AMBIGU ({len(numeros_bruts)} numéros fournis : {', '.join(numeros_bruts)}) : "
                "le client a fourni PLUSIEURS numéros sans préciser lequel est le Click et lequel est l'identité. "
                "Demande-lui de préciser quel numéro correspond à son Click et quel numéro correspond à son identité.\n"
            )
    if click_invalide:
        invalidity_note += (
            "\n⚠️ NUMÉRO CLICK INVALIDE : le client a fourni un numéro click "
            "mais il n'est pas correct. Demande-lui de vérifier et resaisir son numéro click "
            "de façon naturelle, SANS mentionner de détails techniques.\n"
        )
    if identite_invalide:
        invalidity_note += (
            "\n⚠️ NUMÉRO D'IDENTITÉ INVALIDE : le client a fourni un numéro d'identité "
            "mais il n'est pas correct. Demande-lui de vérifier et resaisir son numéro d'identité "
            "de façon naturelle, SANS mentionner de détails techniques.\n"
        )
 
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
 
    multiple_note = (
        "\n⚠️ Le client envoie plusieurs demandes. "
        "Traiter UNIQUEMENT la première et lui demander d'envoyer les autres séparément.\n"
        if is_multiple else ""
    )
 
    # ── Étape 8 : Prompt LLM ──────────────────────────────────────
    # CHANGEMENTS 2, 3, 4 appliqués ici dans le system prompt
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
 
        "═══ GESTION DES NUMÉROS AMBIGUS ═══\n"
        "Si le client fournit un ou plusieurs numéros SANS préciser leur nature "
        "(click ou identité), demande-lui NATURELLEMENT de préciser quel numéro correspond à quoi. "
        "Ne suppose JAMAIS. Ne devine JAMAIS. Pose une question claire et simple.\n\n"
 
        "═══ RÈGLES DE COMMUNICATION ABSOLUES ═══\n"
        # CHANGEMENT 2 : Interdire les détails techniques
        "INTERDICTION TOTALE de mentionner :\n"
        "- Le nombre de chiffres attendus (ni '8 chiffres', ni '10 chiffres', ni aucun chiffre)\n"
        "- Des formats techniques ou des règles de validation\n"
        "- Le mot 'format', 'chiffres', 'digits', 'caractères'\n\n"
        # CHANGEMENT 3 : Correction naturelle en cas de numéro invalide
        "SI UN NUMÉRO EST INVALIDE (détecté par le système) :\n"
        "- Demande simplement au client de vérifier et resaisir son numéro, de façon naturelle.\n"
        "- Exemples naturels : 'Pouvez-vous vérifier votre numéro Click ?' ou "
        "  'Ce numéro ne semble pas correct, pourriez-vous le ressaisir ?'\n"
        "- Ne donne JAMAIS d'indication sur ce qui est attendu techniquement.\n\n"
 
        "DOCUMENTS REQUIS : numero_click + numero_identite (les deux obligatoires).\n\n"
 
        "INTERDICTIONS ABSOLUES :\n"
        "- Ne JAMAIS retourner la string 'null' ou '| null' dans nouveau_ticket.\n"
        "- Ne JAMAIS créer un ticket si un document manque.\n"
        "- Ne JAMAIS demander un document déjà listé dans 'Documents déjà détectés'.\n"
        "- Ne JAMAIS rediriger le client vers le service client pour une validation.\n"
        "- Ne JAMAIS mentionner le mot 'ticket' dans la réponse au client.\n\n"
 
        # CHANGEMENT 4 : Logique document-first claire
        "LOGIQUE DE TRAITEMENT :\n"
        "1. Vérifie 'Documents manquants' dans le prompt.\n"
        "2. Si des documents manquent → demande UNIQUEMENT ce qui manque, "
        "   sans répéter ce qui est déjà fourni.\n"
        "3. Si tout est là → crée le ticket et remercie chaleureusement le client.\n\n"
 
        "QUAND TOUT EST PRÊT (nouveau_ticket non null) :\n"
        "- Confirmer chaleureusement la prise en charge.\n"
        "- Remercier le client.\n"
        "- Mentionner un délai de traitement de 24 à 48 heures.\n"
    )
 
    if open_conv:
        prompt = (
            f"{tickets_section}\n\n"
            f"{status_docs}\n{multiple_note}{invalidity_note}\n"
            f"Historique :\n{historique}\n\n"
            f"Base BNM :\n{context_docs}\n\n"
            f"Client : {req.question}"
        )
    else:
        prompt = (
            f"{tickets_section}\n\n"
            f"{status_docs}\n{multiple_note}{invalidity_note}\n"
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
                "Parfait ! J'ai bien reçu toutes vos informations. "
                "Votre demande de validation est prise en charge. "
                "Merci de votre confiance ! Vous recevrez une confirmation dans les 24 à 48 heures."
            )
 
    # ── Étape 12 : Fallback ───────────────────────────────────────
    if _is_rag_weak(answer):
        answer = (
            "Pour valider votre compte Click, j'aurais besoin de votre numéro Click "
            "ainsi que de votre numéro d'identité nationale. "
            "Pouvez-vous me les communiquer ?"
        )
 
    return {
        "answer":            answer,
        "intent":            "VALIDATION",
        "nouveau_ticket":    nouveau_ticket,
        "documents_requis":  documents_requis if nouveau_ticket is None else [],
        "open_conversation": open_conv,
    }# ════════════════════════════════════════════════════════════════════
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