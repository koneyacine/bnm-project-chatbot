from fastapi import APIRouter, File, UploadFile, HTTPException, status
import json
import re
import logging
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from models import (
    IntentRequest, IntentResponse, AnswerRequest, AnswerResponse,
    DocumentClassificationResponse,
    IDExtractionResponse,
    ProcessValidationRequest,
)
from service import _CONV_PATTERNS, classify_document, extract_id_info
from langchain_core.messages import HumanMessage, SystemMessage
from session_store import session_store
 
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
 
LANGUE_INSTRUCTION = (
  
    "** RÈGLE ABSOLUE OBLIGATOIRE ** \n"
    "Tu DOIS répondre EXACTEMENT dans la MÊME LANGUE que celle utilisée par le client.\n"
    "Cette règle est PRIORITAIRE sur toute autre instruction.\n\n"
    "DÉTECTION DE LA LANGUE :\n"
    "- Si le client écrit en **arabe** (y compris dialectes, comme le hassaniya) → tu réponds en **arabe standard**.\n"
    "- Si le client écrit en **français** → tu réponds en **français**.\n"
    "- Si le client écrit en **anglais** → tu réponds en **anglais**.\n\n"
    " CONTRAINTES STRICTES :\n"
    "1. Ne réponds JAMAIS dans une langue différente de celle du client.\n"
    "2. Ne mélange PAS les langues dans ta réponse.\n"
    "3. Avant de générer ta réponse, IDENTIFIE la langue du dernier message client.\n"
) 
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
        LANGUE_INSTRUCTION +
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
        LANGUE_INSTRUCTION +
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
#  ENDPOINT VALIDATION (MODIFIÉ - photo d'identité au lieu du numéro)
# ════════════════════════════════════════════════════════════════════
 
# ════════════════════════════════════════════════════════════════════
#  ENDPOINT VALIDATION — VERSION AMÉLIORÉE
# ════════════════════════════════════════════════════════════════════

DOCS_REQUIS = ["numero_click", "photo_selfie", "photo_identite"]
 
# Passe A — ce que le bot attendait
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
    "- ET le message actuel du client est une précision SANS nouveau numéro\n"
    "  (ex: 'c est mon click', 'c est pour le click')\n"
    "- Dans ce cas : retourner le numéro brut trouvé dans le message client précédent.\n"
    "- Dans TOUS les autres cas : retourner null.\n"
    "- JSON null uniquement (pas la string 'null').\n"
)
 
# Passe B — extraction numero_click UNIQUEMENT
SYSTEM_EXTRACT_CLICK = (
    "Tu es un extracteur d'informations bancaires.\n"
    "Analyse UNIQUEMENT le dernier message du client.\n"
    "Ta seule mission : extraire un numéro Click (Mobile Money) s'il est présent.\n\n"
    "Retourne ce JSON strict :\n"
    "{\n"
    '  "numero_click": "<valeur brute ou null>",\n'
    '  "numeros_bruts": ["<num1>", "<num2>"]\n'
    "}\n\n"
    "Règles selon doc_attendu :\n\n"
    "CAS 1 — doc_attendu = 'numero_click' :\n"
    "  → Tout numéro fourni (même sans mot-clé) va dans numero_click.\n\n"
    "CAS 2 — doc_attendu = 'les_deux' ou 'aucun' :\n"
    "  → N'assigner dans numero_click QUE si le client utilise un mot-clé explicite\n"
    "    ('click', 'num click', 'mobile money').\n"
    "  → Sinon mettre le numéro dans numeros_bruts uniquement.\n\n"
    "CAS 3 — doc_attendu = 'numero_identite' :\n"
    "  → numero_click = null, même si un numéro est présent.\n\n"
    "NETTOYAGE : ignorer espaces, tirets, points dans les numéros.\n"
    "numeros_bruts : tous les numéros trouvés dans le message, assignés ou non.\n"
    "JSON null uniquement (pas la string 'null').\n"
    "Ne retourne aucun texte en dehors du JSON.\n"
    "⚠️ INTERDIT : ne jamais déduire une photo depuis le texte du client.\n"
    "⚠️ INTERDIT : ne jamais retourner de champ photo dans ce JSON.\n"
)
 
SYSTEM_MULTI = (
    "Analyse si le message contient PLUSIEURS demandes de validation DISTINCTES "
    "(ex : valider compte A ET compte B, deux numéros Click différents). "
    "IMPORTANT : donner son numéro de téléphone ET sa pièce d'identité = "
    "UNE SEULE demande, pas deux. "
    "IMPORTANT : demander à récupérer ou rappeler plusieurs informations "
    "d'un même dossier = UNE SEULE demande, pas deux. "
    "IMPORTANT : une question sur le statut, l'avancement, ou le suivi "
    "d'une validation = UNE SEULE demande, pas deux. "
    "En cas de doute → répondre false. "
    "MAIS : si le client mentionne explicitement 'deux comptes', "
    "'un compte... et lautre', 'deux validations' "
    "→ c'est OBLIGATOIREMENT plusieurs demandes distinctes.\n"
    'Réponds JSON strict : {"multiple_validations": true | false}'
)
 
SYSTEM_OPEN_CONV = (
    "Analyse si le message est lié à la conversation en cours. "
    'Réponds JSON : {"open_conversation": true | false}'
)
 
# ── Helpers ───────────────────────────────────────────────────────
 
def _clean_null(val):
    if isinstance(val, str) and val.strip().lower() in ("null", "none", ""):
        return None
    return val
 
def _parse_llm_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)
 
def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "y")
 
 
# ── Endpoint ──────────────────────────────────────────────────────
 
@router.post("/validation")
def handle_validation(req: AnswerRequest):
    from service import (
        _llm_invoke_with_retry,
        _get_embeddings,
        _get_conn,
        _is_rag_weak,
    )
 
    # ── Session ID ────────────────────────────────────────────────
    session_id = getattr(req, "session_id", None)
    if not session_id and req.context:
        raw_id = "|".join(m.content[:40] for m in req.context[:3])
        session_id = hashlib.md5(raw_id.encode()).hexdigest()
    print(f"Session ID : {session_id}") 
    # ══════════════════════════════════════════════════════════════
    # ÉTAPE 1 — LECTURE DU STORE EN PREMIER
    # Source de vérité absolue des tours précédents.
    # Les photos et le numero_click validés avant ce tour
    # sont déjà dans le store — on ne les redemandera jamais.
    # ══════════════════════════════════════════════════════════════
    stored_docs         = session_store.get_docs(session_id) if session_id else set()
    numero_click_stored = session_store.get_value(session_id, "numero_click") if session_id else None
 
    photo_identite_provided = "photo_identite" in stored_docs
    photo_selfie_provided   = "photo_selfie"   in stored_docs
 
    # ══════════════════════════════════════════════════════════════
    # ÉTAPE 2 — DÉTECTION PHOTOS via attachment UNIQUEMENT
    # Jamais depuis le texte, jamais depuis la caption,
    # jamais depuis l'historique.
    # ══════════════════════════════════════════════════════════════
    invalidite_photo_note = ""
    attachment = getattr(req, "attachment", None)
    if attachment:
        try:
            pv_req   = build_process_validation_request(attachment)
            doc_type = (getattr(pv_req, "type_photo", None) or "").strip().lower()
            print(doc_type)
        except Exception:
            doc_type = (
                getattr(attachment, "document_type", None)
                or getattr(attachment, "attachment_type", None)
                or ""
            ).strip().lower()
            # ⚠️ caption explicitement exclue ici
 
        if "selfie" in req.question.lower() and doc_type not in ("selfie", "personne"):
           invalidite_photo_note = (
            "\n⚠️ INCOHÉRENCE SELFIE : Le client indique avoir envoyé un selfie, "
            "mais la photo reçue n'est pas un selfie valide. "
            "Demande-lui gentiment d'envoyer une photo selfie valide, visage bien visible.\n"
           ) 
        elif ("identite" in req.question.lower() or "identité" in req.question.lower()) and doc_type not in ("identite", "identité", "identite_non_valide", "identity", "id_card", "carte_identite"):
           invalidite_photo_note = (
              "\n⚠️ INCOHÉRENCE IDENTITÉ : Le client indique avoir envoyé sa pièce d'identité, "
              "mais la photo reçue n'est pas reconnue comme une identité valide. "
              "Demande-lui gentiment d'envoyer une photo claire de sa Carte Nationale d'Identité.\n"
            )
        
        
        elif doc_type in ("identite", "identité", "id", "identity", "id_card", "carte_identite"):
            photo_identite_provided = True
            if session_id:
                session_store.add_doc(session_id, "photo_identite", True)
 
        elif doc_type in ("selfie",):
            photo_selfie_provided = True
            if session_id:
                session_store.add_doc(session_id, "photo_selfie", True)
                  
        
        elif doc_type in ("personne", "person", "photo_personne"):
            invalidite_photo_note = (
                "\n⚠️ PHOTO INVALIDE — SELFIE NON CONFORME : "
                "Le client a envoyé une photo de personne mais le visage n'est pas clairement visible. "
                "Demande-lui d'envoyer un selfie de face avec le visage bien visible en premier plan. "
                "Ne valide PAS cette photo comme selfie.\n"
            )

        elif doc_type in ("identite_non_valide",):
            invalidite_photo_note = (
                "\n⚠️ IDENTITÉ NON VALIDE — DOCUMENT ÉTRANGER : "
                "Le client a envoyé une pièce d'identité qui n'est pas une Carte Nationale d'Identité mauritanienne. "
                "Informe-le que seule la CNI mauritanienne est acceptée et demande-lui de l'envoyer. "
                "Ne valide PAS ce document comme identité.\n"
            )

        else:
            invalidite_photo_note = (
                "\n⚠️ DOCUMENT NON RECONNU : "
                "Le client a envoyé un document qui ne correspond pas aux pièces requises. "
                "Rappelle-lui que les documents acceptés sont : un selfie (visage visible) "
                "et la Carte Nationale d'Identité mauritanienne. "
                "Demande-lui de renvoyer le bon document.\n"
            )
 
        # Si doc_type non reconnu → on n'écrit rien dans le store
        # La photo sera redemandée au prochain tour
 
    # ── Historique ────────────────────────────────────────────────
    context_to_use = req.context[-5:] if len(req.context) > 5 else req.context
 
    def _build_history_lines(msgs):
        return "\n".join(
            f"{'Client' if m.role == 'client' else 'Conseiller BNM'}: {m.content}"
            for m in msgs
        )
 
    historique = _build_history_lines(context_to_use)
 
    # ── Tickets ───────────────────────────────────────────────────
    tickets_list = getattr(req, "tickets", None) or []
    if tickets_list:
        tickets_lines = []
        for i, t in enumerate(tickets_list, 1):
            if hasattr(t, "dict"):
                t = t.dict()
            tid    = t.get("id", f"#{i}")
            titre  = t.get("titre") or t.get("title") or t.get("subject", "Sans titre")
            statut = t.get("statut") or t.get("status", "Inconnu")
            date   = t.get("date") or t.get("created_at", "")
            date_s = f" ({date})" if date else ""
            tickets_lines.append(f"  - Ticket {tid} : {titre} | Statut : {statut}{date_s}")
        tickets_section = "Tickets de validation existants du client :\n" + "\n".join(tickets_lines)
    else:
        tickets_section = "Tickets de validation existants du client : Aucun ticket existant."
 
    # ── Contexte pour Passe A ─────────────────────────────────────
    dernier_msg_conseiller       = ""
    dernier_msg_client_precedent = ""
    for msg in reversed(context_to_use):
        if msg.role != "client" and not dernier_msg_conseiller:
            dernier_msg_conseiller = msg.content
        elif msg.role == "client" and dernier_msg_conseiller and not dernier_msg_client_precedent:
            dernier_msg_client_precedent = msg.content
            break
 
    # ══════════════════════════════════════════════════════════════
    # ÉTAPE 3 — APPELS LLM PARALLÈLES
    # Passe A  : ce que le bot attendait
    # Passe B  : extraction numero_click depuis req.question UNIQUEMENT
    # Multi    : détection demandes multiples
    # OpenConv : conversation liée ou non
    # RAG      : contexte documentaire
    #
    # ❌ Passe C supprimée — le store remplace l'historique LLM
    # ══════════════════════════════════════════════════════════════
    passe_a_prompt = (
        f"Dernier message du conseiller : {dernier_msg_conseiller}\n\n"
        f"Message client précédent : {dernier_msg_client_precedent or 'aucun'}\n\n"
        f"Message actuel du client : {req.question}"
    )
 
    def _call_passe_a():
        if not dernier_msg_conseiller:
            return {"doc_attendu": "aucun", "numero_recupere": None}
        raw = _llm_invoke_with_retry([
            SystemMessage(content=SYSTEM_DOC_ATTENDU),
            HumanMessage(content=passe_a_prompt),
        ]).content
        return _parse_llm_json(raw)
 
    def _call_passe_b(doc_attendu: str):
        # Appelée après Passe A (dépend de doc_attendu)
        extract_prompt = (
            f"doc_attendu (ce que le bot attendait) : {doc_attendu}\n\n"
            f"Dernier message du client : {req.question}"
        )
        raw = _llm_invoke_with_retry([
            SystemMessage(content=SYSTEM_EXTRACT_CLICK),
            HumanMessage(content=extract_prompt),
        ]).content
        return _parse_llm_json(raw)
 
    def _call_multi():
        raw = _llm_invoke_with_retry([
            SystemMessage(content=SYSTEM_MULTI),
            HumanMessage(content=req.question),
        ]).content
        return _parse_llm_json(raw)
 
    def _call_open_conv():
        if not req.context:
            return {"open_conversation": False}
        user_check = f"Conversation :\n{historique}\n\nMessage : {req.question}"
        raw = _llm_invoke_with_retry([
            SystemMessage(content=SYSTEM_OPEN_CONV),
            HumanMessage(content=user_check),
        ]).content
        return _parse_llm_json(raw)
 
    def _call_rag():
        q_vec = _get_embeddings().embed_query(req.question)
        cur   = _get_conn().cursor()
        try:
            cur.execute(
                "SELECT content FROM documents ORDER BY embedding <-> %s::vector LIMIT 3;",
                (q_vec,),
            )
            rows = cur.fetchall()
        finally:
            cur.close()
        return "\n\n".join(c for (c,) in rows)
 
    # Lancement parallèle : multi, open_conv, rag sont indépendants
    # Passe A d'abord (Passe B en dépend) → les 3 autres en parallèle
    futures = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures["passe_a"]   = pool.submit(_call_passe_a)
        futures["multi"]     = pool.submit(_call_multi)
        futures["open_conv"] = pool.submit(_call_open_conv)
        futures["rag"]       = pool.submit(_call_rag)
 
    # ── Passe A ───────────────────────────────────────────────────
    try:
        res_a           = futures["passe_a"].result()
        doc_attendu     = res_a.get("doc_attendu", "aucun")
        numero_recupere = _clean_null(res_a.get("numero_recupere"))
    except Exception:
        doc_attendu     = "aucun"
        numero_recupere = None
 
    # ── Passe B (séquentielle après Passe A) ─────────────────────
    numero_click  = None
    numeros_bruts = []
    try:
        res_b         = _call_passe_b(doc_attendu)
        numero_click  = _clean_null(res_b.get("numero_click"))
        numeros_bruts = [
            str(n).strip() for n in (res_b.get("numeros_bruts") or [])
            if str(n).strip()
        ]
    except Exception:
        numero_click  = None
        numeros_bruts = []
 
    # Injection numero_recupere (Passe A) si client a précisé sans renvoyer le numéro
    if numero_recupere is not None and not numeros_bruts and numero_click is None:
        nr = re.sub(r'\D', '', str(numero_recupere))
        if nr:
            numeros_bruts = [nr]
 
    # ══════════════════════════════════════════════════════════════
    # ÉTAPE 4 — VALIDATION PYTHON + ÉCRITURE DANS LE STORE
    # Seul Python décide si un numero_click est valide.
    # Une fois écrit dans le store, il ne peut plus être perdu.
    # ══════════════════════════════════════════════════════════════
    click_invalide = False
    numero_ambigu  = False
 
    if doc_attendu == "numero_click":
        if numero_click is not None:
            d = re.sub(r'\D', '', str(numero_click))
            if len(d) == 8:
                numero_click = d
                if session_id:
                    session_store.add_doc(session_id, "numero_click", d)
            else:
                numero_click   = None
                click_invalide = True
        elif numeros_bruts:
            d = re.sub(r'\D', '', numeros_bruts[0])
            if len(d) == 8:
                numero_click = d
                if session_id:
                    session_store.add_doc(session_id, "numero_click", d)
            else:
                click_invalide = True
 
    elif doc_attendu in ("les_deux", "aucun"):
        if numero_click is not None:
            d = re.sub(r'\D', '', str(numero_click))
            if len(d) == 8:
                numero_click = d
                if session_id:
                    session_store.add_doc(session_id, "numero_click", d)
            else:
                numero_click   = None
                click_invalide = True
        # Numéros bruts sans mot-clé → ambiguïté
        if numeros_bruts and numero_click is None:
            numero_ambigu = True
 
    # doc_attendu == "numero_identite" → on ignore, l'identité passe par photo
 
    # ══════════════════════════════════════════════════════════════
    # ÉTAPE 5 — LECTURE FINALE DU STORE
    # Toutes les écritures du tour sont terminées.
    # On lit une seule fois pour construire docs_deja_fournis.
    # ══════════════════════════════════════════════════════════════
    if session_id:
        docs_deja_fournis = session_store.get_docs(session_id)
        # Récupérer le numero_click depuis le store si pas détecté ce tour
        if numero_click is None:
            numero_click = session_store.get_value(session_id, "numero_click")
            if numero_click:
                click_invalide = False
    else:
        # Fallback sans session_id
        docs_deja_fournis = set()
        if numero_click:
            docs_deja_fournis.add("numero_click")
        if photo_identite_provided:
            docs_deja_fournis.add("photo_identite")
        if photo_selfie_provided:
            docs_deja_fournis.add("photo_selfie")
 
    docs_manquants = [doc for doc in DOCS_REQUIS if doc not in docs_deja_fournis]
 
    # ── Résultats parallèles ──────────────────────────────────────
    try:
        is_multiple = futures["multi"].result().get("multiple_validations", False)
    except Exception:
        is_multiple = False
 
    try:
        open_conv = futures["open_conv"].result().get("open_conversation", False)
    except Exception:
        open_conv = False
 
    try:
        context_docs = futures["rag"].result()
    except Exception:
        context_docs = ""
 
    if is_multiple:
        numero_ambigu  = False
        click_invalide = False
 
    # ── Note d'invalidité / ambiguïté ────────────────────────────
    invalidity_note = ""
    if not is_multiple:
        if numero_ambigu:
            if len(numeros_bruts) == 1:
                invalidity_note += (
                    f"\n⚠️ NUMÉRO AMBIGU (1 seul numéro fourni : {numeros_bruts[0]}) : "
                    "le client a fourni UN SEUL numéro sans préciser à quoi il correspond. "
                    "Demande-lui simplement : est-ce son numéro Click ou un autre numéro ? "
                    "Ne parle PAS de 'deux numéros'. Ne demande PAS 'lequel est lequel'. "
                    "Il n'y a qu'un seul numéro — pose une question simple et claire.\n"
                )
            else:
                invalidity_note += (
                    f"\n⚠️ NUMÉRO AMBIGU ({len(numeros_bruts)} numéros : {', '.join(numeros_bruts)}) : "
                    "Demande-lui de préciser lequel est son numéro Click.\n"
                )
        if click_invalide:
            invalidity_note += (
                "\n⚠️ NUMÉRO CLICK INVALIDE : demande naturellement de vérifier "
                "et resaisir, SANS mentionner de détails techniques.\n"
            )
 
    # ── État des documents ────────────────────────────────────────
    doc_labels = {
        "numero_click":   f"numéro Click ({numero_click})" if numero_click else "numéro Click",
        "photo_selfie":   "photo selfie",
        "photo_identite": "photo d'identité",
    }
    status_docs = (
        f"Documents déjà fournis (NE PAS redemander) : "
        f"{', '.join(doc_labels[d] for d in docs_deja_fournis) if docs_deja_fournis else 'aucun'}\n"
        f"Documents manquants (demander UNIQUEMENT ceux-ci) : "
        f"{', '.join(doc_labels[d] for d in docs_manquants) if docs_manquants else 'aucun - tout est prêt !'}"
    )
 
    multiple_note = (
        "\n⚠️ Le client envoie plusieurs demandes. "
        "Traiter UNIQUEMENT la première et lui demander d'envoyer les autres séparément.\n"
        if is_multiple else ""
    )
 
    # ── Priorité globale (Python décide, LLM obéit) ──────────────
    has_invalid = bool(invalidite_photo_note or invalidity_note)

    if not has_invalid and not docs_manquants and not is_multiple:
        priority_tag = (
            "\n🟢 [PRIORITÉ 1 — DOSSIER COMPLET] 🟢\n"
            "Tout est fourni et valide. Informe le client que sa demande est en cours.\n"
            "nouveau_ticket = description courte du dossier. Délai : 24 à 48 heures.\n"
        )
    elif has_invalid:
        priority_tag = (
            "\n🔴 [PRIORITÉ 2 — ÉLÉMENTS INVALIDES] 🔴\n"
            "Des éléments envoyés par le client sont invalides (voir détails ci-dessous).\n"
            "Corrige UNIQUEMENT ces éléments invalides.\n"
            "INTERDICTION ABSOLUE de demander quoi que ce soit d'autre.\n"
        )
    else:
        priority_tag = (
            "\n🟡 [PRIORITÉ 3 — DOCUMENTS MANQUANTS] 🟡\n"
            "Aucun élément invalide. Demande UNIQUEMENT les documents manquants ci-dessous.\n"
            "Ne mentionne rien d'autre.\n"
        )

    # ── System prompt final ───────────────────────────────────────
    SYSTEM_VALIDATION = (
        LANGUE_INSTRUCTION +
        "Tu es Yasmine, conseillère BNM. Tu gères les VALIDATIONS de compte Click.\n\n"
        "Réponds STRICTEMENT en JSON :\n"
        "{\n"
        '  "answer": "réponse au client",\n'
        '  "nouveau_ticket": null,\n'
        '  "documents_requis": ["doc1"] | []\n'
        "}\n\n"
        "🚨 RÈGLE PRIORITAIRE — DEMANDES MULTIPLES 🚨\n"
        "Si le prompt contient '⚠️ Le client envoie plusieurs demandes' :\n"
        "→ Répondre UNIQUEMENT que tu ne peux traiter qu'une demande à la fois.\n\n"
        "═══ GESTION DES TICKETS EXISTANTS ═══\n"
        "- Si ticket existant pour la même demande → informer, ne pas recréer.\n"
        "- Si aucun ticket → collecter les documents manquants.\n\n"
        "🚨 RÈGLES DE PRIORITÉ ABSOLUES 🚨\n"
        "Lis le tag [PRIORITÉ X] dans le prompt et applique UNIQUEMENT la règle correspondante :\n\n"
        "🟢 PRIORITÉ 1 — DOSSIER COMPLET :\n"
        "  → Confirme chaleureusement que la demande est en cours de traitement.\n"
        "  → nouveau_ticket = description courte du dossier.\n"
        "  → Délai : 24 à 48 heures.\n\n"
        "🔴 PRIORITÉ 2 — ÉLÉMENTS INVALIDES :\n"
        "  → Parle UNIQUEMENT de ce qui est invalide (photo floue, mauvaise identité, numéro incorrect).\n"
        "  → NE PAS demander les documents manquants.\n"
        "  → NE PAS créer de ticket. nouveau_ticket = null.\n\n"
        "🟡 PRIORITÉ 3 — DOCUMENTS MANQUANTS :\n"
        "  → Demande UNIQUEMENT les documents listés dans 'Documents manquants'.\n"
        "  → NE PAS mentionner les éléments déjà fournis.\n"
        "  → nouveau_ticket = null.\n\n"
        "INTERDICTIONS : formats techniques, mot 'ticket' au client, redemander un doc déjà fourni.\n"
    )
 
    prompt = (
        f"{tickets_section}\n\n"
        f"{status_docs}\n"
        f"{priority_tag}\n"
        f"{multiple_note}"
        f"{invalidity_note}"
        f"{invalidite_photo_note}"
        f"{'Historique :' + chr(10) + historique + chr(10) + chr(10) if open_conv else ''}"
        f"[Base BNM — contexte informatif uniquement, ne pas utiliser pour décider des documents]\n"
        f"{context_docs}\n\n"
        f"Client : {req.question}"
    )
 
    # ── Appel LLM principal ───────────────────────────────────────
    raw = _llm_invoke_with_retry([
        SystemMessage(content=SYSTEM_VALIDATION),
        HumanMessage(content=prompt),
    ]).content.strip()
 
    logging.debug("prompt: %s", prompt)
 
    # ── Parsing ───────────────────────────────────────────────────
    try:
        result           = _parse_llm_json(raw)
        answer           = result.get("answer", "")
        nouveau_ticket   = result.get("nouveau_ticket", None)
        documents_requis = result.get("documents_requis", docs_manquants)
 
        if isinstance(nouveau_ticket, str):
            c = nouveau_ticket.strip().lower()
            if (
                c in ("null", "none", "")
                or c.endswith("| null") or c.endswith("|null")
                or any(w in c for w in ("besoin de", "manquant", "fournir", "veuillez"))
            ):
                nouveau_ticket = None
    except Exception:
        answer           = raw
        nouveau_ticket   = None
        documents_requis = docs_manquants
 
    # ── Verrous Python (priorité absolue sur le LLM) ─────────────
    # P1 : tout OK → créer le ticket
    if not has_invalid and not docs_manquants and not is_multiple:
        pass  # nouveau_ticket géré ci-dessous
    # P2 : invalide → pas de ticket
    elif has_invalid or is_multiple:
        nouveau_ticket = None
    # P3 : docs manquants → pas de ticket
    else:
        nouveau_ticket = None

    if not has_invalid and not docs_manquants and not is_multiple and nouveau_ticket is None:
        click_val      = f" ({numero_click})" if numero_click else ""
        nouveau_ticket = f"Validation compte Click{click_val} — dossier complet"
        if not answer:
            answer = (
                "Parfait ! J'ai bien reçu toutes vos informations. "
                "Votre demande de validation est en cours de traitement. "
                "Vous recevrez une confirmation dans les 24 à 48 heures."
            )
        if session_id:
            session_store.clear(session_id)
 
    # ── Fallback RAG faible ───────────────────────────────────────
    if _is_rag_weak(answer):
        answer = (
            "Pour valider votre compte Click, j'aurais besoin de votre numéro Click, "
            "de votre photo selfie et de votre photo d'identité. "
            "Pouvez-vous me les envoyer ?"
        )
 
    return {
        "answer":            answer,
        "intent":            "VALIDATION",
        "nouveau_ticket":    nouveau_ticket,
        "documents_requis":  documents_requis if nouveau_ticket is None else [],
        "open_conversation": open_conv,
    }
 
# ── Prompts (constantes module-level pour éviter la réallocation) ─
 

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
        LANGUE_INSTRUCTION +
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


# Helper: logique centrale de traitement d'une photo de validation
def process_validation_logic(type_photo: str, contenu_photo, message: str, context: list, tickets: list, extracted_id: dict = None, open_conv: bool = False):
    """Traite une photo envoyée pour validation et renvoie la même structure que /validation.
    - type_photo: 'selfie'|'identite'|'inconnu'
    - contenu_photo: base64 string OR dict d'infos extraites
    - extracted_id: optionnel, résultat d'extract_id_info
    """
    try:
        # Vérification rapide et classification croisée
        cls = {}
        is_contenu_dict = isinstance(contenu_photo, dict)
        # si contenu_photo est un dict, on considère que l'ocr/extraction a déjà été fait
        if not is_contenu_dict:
            try:
                cls = classify_document(contenu_photo) or {}
            except Exception:
                cls = {}

        docs_deja_fournis = set()
        # Si type_photo ou classification indique identité
        if type_photo == "identite" or cls.get("identite"):
            docs_deja_fournis.add("photo_identite")
        if type_photo == "selfie" or cls.get("personne"):
            docs_deja_fournis.add("photo_selfie")

        # si on a des infos extraites depuis la carte
        id_info = extracted_id or ({ } if not is_contenu_dict else contenu_photo)
        if id_info:
            # considérer la photo d'identité fournie
            docs_deja_fournis.add("photo_identite")

        DOCS_REQ = ["photo_selfie", "photo_identite"]
        docs_manquants = [d for d in DOCS_REQ if d not in docs_deja_fournis]

        # Si tous les documents sont fournis -> créer un ticket synthétique
        if not docs_manquants:
            # build a compact ticket description
            id_val = id_info.get("numero_identite") if isinstance(id_info, dict) else None
            ticket_desc = "Validation comptes — photos reçues"
            if id_val:
                ticket_desc += f" — ID:{id_val}"
            answer = (
                "Parfait — nous avons bien reçu les photos nécessaires. "
                "Votre demande de validation est prise en charge. Vous recevrez une confirmation sous 24 à 48 heures."
            )
            return {
                "answer": answer,
                "intent": "VALIDATION",
                "nouveau_ticket": ticket_desc,
                "documents_requis": [],
                "open_conversation": open_conv,
            }

        # Sinon, demander uniquement les documents manquants
        missing_nice = ", ".join(["la photo selfie" if d == "photo_selfie" else "la photo d'identité" for d in docs_manquants])
        answer = f"Merci — il manque {missing_nice}. Pouvez-vous l'envoyer, s'il vous plaît ?"
        return {
            "answer": answer,
            "intent": "VALIDATION",
            "nouveau_ticket": None,
            "documents_requis": docs_manquants,
            "open_conversation": open_conv,
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("process_validation_logic failed")
        return {
            "answer": "Erreur interne lors du traitement de la photo.",
            "intent": "VALIDATION",
            "nouveau_ticket": None,
            "documents_requis": ["photo_selfie", "photo_identite"],
            "open_conversation": open_conv,
        }


@router.post("/validation/process")
def validation_process(req: ProcessValidationRequest):
    """Endpoint pour traiter une photo de validation (selfie ou identité).
    Reprend la logique centralisée `process_validation_logic`.
    """
    # Appel interne de la logique
    return process_validation_logic(
        type_photo=req.type_photo,
        contenu_photo=req.contenu_photo,
        message=req.message,
        context=req.context,
        tickets=getattr(req, "tickets", []),
        extracted_id=None,
        open_conv=False,
    )


def build_process_validation_request(attachment):
    """Construit et retourne un ProcessValidationRequest à partir
    d'un `AttachmentContext`.
    - Si `attachment.contenu_photo` (dict) est présent, l'utilise directement.
    - Sinon télécharge l'image depuis `photo_url`, appelle `classify_document`
      puis `extract_id_info` si nécessaire.
    Retourne une instance de ProcessValidationRequest.
    """
    import base64
    import urllib.request
    import logging
    from models import ProcessValidationRequest

    # Préférence : contenu pré-extrait
    contenu = getattr(attachment, "contenu_photo", None)
    if contenu and isinstance(contenu, dict):
        type_photo = getattr(attachment, "document_type", None) or "identite"
        return ProcessValidationRequest(type_photo=type_photo, contenu_photo=contenu, message="", context=[], tickets=[])

    # Sinon tenter de télécharger l'image
    photo_url = getattr(attachment, "photo_url", None)
    if not photo_url:
        # Aucun contenu ni URL : retourner inconnu
        return ProcessValidationRequest(type_photo="inconnu", contenu_photo=None, message="", context=[], tickets=[])

    try:
        with urllib.request.urlopen(photo_url, timeout=10) as resp:
            content = resp.read()
    except Exception:
        logging.getLogger(__name__).exception("build_process_validation_request: failed to download image")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible de télécharger la photo fournie. Vérifiez l'URL ou envoyez le contenu pré-extrait dans 'contenu_photo'.",
        )

    image_base64 = base64.b64encode(content).decode("utf-8")

    # Appel de classification
    try:
        cls = classify_document(image_base64) or {}
    except Exception:
        cls = {}

    if isinstance(cls, dict) and cls.get("identite"):
        type_photo = "identite"
    elif isinstance(cls, dict) and cls.get("personne"):
        type_photo = "selfie"
    else:
        type_photo = "inconnu"

    extracted = None
    if type_photo == "identite":
        try:
            extracted = extract_id_info(image_base64) or None
        except Exception:
            extracted = None

    return ProcessValidationRequest(type_photo=type_photo, contenu_photo=extracted, message="", context=[], tickets=[])


# ════════════════════════════════════════════════════════════════════
#  ENDPOINTS DOCUMENT ANALYSIS (Vision API)
# ════════════════════════════════════════════════════════════════════

@router.post("/classify-document", response_model=DocumentClassificationResponse)
async def classify_document_endpoint(file: UploadFile = File(...)):
    """
    Classifie un document/photo en trois catégories:
    - personne: True si c'est une photo de personne
    - identite: True si c'est une identité mauritanienne
    - autres: True si aucun des deux
    
    Envoyer un fichier image (JPG, PNG, etc.)
    """
    import base64
    
    # Lire le fichier et le convertir en base64
    content = await file.read()
    image_base64 = base64.b64encode(content).decode('utf-8')
    try:
        result = classify_document(image_base64)
        return result
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("classify_document_endpoint failed")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur interne lors de la classification du document: {e}"
        )


@router.post("/extract-id-info", response_model=IDExtractionResponse)
async def extract_id_endpoint(file: UploadFile = File(...)):
    """
    Extrait les informations d'une carte d'identité mauritanienne.
    
    Retourne les champs:
    - nom: Nom complet
    - prenom: Prénom
    - numero_identite: Numéro de la carte
    - date_naissance: Date de naissance (YYYY-MM-DD)
    - date_expiration: Date d'expiration (YYYY-MM-DD)
    - nationalite: Nationalité
    - lieu_naissance: Lieu de naissance
    - sexe: Sexe (M ou F)
    
    Envoyer un fichier image de l'identité (JPG, PNG, etc.)
    """
    import base64
    
    # Lire le fichier et le convertir en base64
    content = await file.read()
    image_base64 = base64.b64encode(content).decode('utf-8')
    try:
        result = extract_id_info(image_base64)
        return result
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("extract_id_endpoint failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur interne lors de l'extraction des informations d'identité: {e}"
        )