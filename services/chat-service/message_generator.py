"""
message_generator.py — Génération automatique des messages client BNM.

Fonction principale :
  generate_client_message(ticket, action) → str

Actions supportées :
  VALIDATION, REJET, COMPLEMENT_REQUIS, EN_ATTENTE_CLIENT
"""

import os
import logging

logger = logging.getLogger(__name__)

_INTENT_LABELS = {
    "RECLAMATION": "réclamation",
    "VALIDATION":  "demande de validation",
    "INFORMATION": "demande d'information",
}


def _intent_label(ticket: dict) -> str:
    intent = ticket.get("classification", {}).get("intent", "demande")
    return _INTENT_LABELS.get(intent, "demande")


def generate_client_message(ticket: dict, action: str, **kwargs) -> str:
    """
    Génère un message destiné au client selon l'action effectuée.

    Args:
        ticket  : dict ticket complet
        action  : VALIDATION | REJET | COMPLEMENT_REQUIS | EN_ATTENTE_CLIENT
        **kwargs: paramètres spécifiques à l'action
            - note     (VALIDATION) : note interne optionnelle
            - reason   (REJET)      : motif du rejet
            - message  (COMPLEMENT_REQUIS) : liste des docs requis
            - question (EN_ATTENTE_CLIENT) : question posée au client

    Returns:
        str — message formaté en français
    """
    tid = ticket.get("ticket_id", "N/A")
    intent_lb = _intent_label(ticket)

    # ── Tenter d'enrichir avec le LLM si disponible ───────────────────────────
    llm_msg = _try_llm_message(ticket, action, **kwargs)
    if llm_msg:
        return llm_msg

    # ── Templates statiques ───────────────────────────────────────────────────
    if action == "VALIDATION":
        note = kwargs.get("note", "")
        note_part = f"\n{note}" if note else ""
        return (
            f"Bonjour,\n\n"
            f"Nous avons le plaisir de vous informer que votre {intent_lb} "
            f"(réf. {tid}) a été validée par notre équipe.{note_part}\n\n"
            f"Vous serez contacté prochainement pour la suite.\n\n"
            f"Cordialement,\nL'équipe BNM"
        )

    if action == "REJET":
        reason = kwargs.get("reason", "raison non précisée")
        return (
            f"Bonjour,\n\n"
            f"Après examen de votre {intent_lb} (réf. {tid}), "
            f"nous ne sommes pas en mesure de la traiter pour la raison suivante :\n"
            f"{reason}\n\n"
            f"N'hésitez pas à nous contacter pour plus d'informations.\n\n"
            f"Cordialement,\nL'équipe BNM"
        )

    if action == "COMPLEMENT_REQUIS":
        message = kwargs.get("message", "documents complémentaires")
        return (
            f"Bonjour,\n\n"
            f"Afin de traiter votre demande (réf. {tid}), "
            f"nous avons besoin des éléments suivants :\n{message}\n\n"
            f"Merci de nous les fournir dès que possible.\n\n"
            f"Cordialement,\nL'équipe BNM"
        )

    if action == "EN_ATTENTE_CLIENT":
        question = kwargs.get("question", "")
        return (
            f"Bonjour,\n\n"
            f"Concernant votre demande (réf. {tid}), "
            f"notre équipe a une question pour vous :\n{question}\n\n"
            f"Merci de nous répondre dès que possible.\n\n"
            f"Cordialement,\nL'équipe BNM"
        )

    return f"Votre demande (réf. {tid}) a été mise à jour. Merci de votre confiance."


def _try_llm_message(ticket: dict, action: str, **kwargs) -> str | None:
    """
    Tente d'enrichir le message template via gpt-4o-mini.
    Retourne None si le LLM est indisponible ou si la génération échoue.
    """
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage
        from dotenv import load_dotenv
        load_dotenv()

        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key or api_key.startswith("sk-proj-VOTRE"):
            return None

        llm = ChatOpenAI(model=os.getenv(
            "OPENAI_MODEL", "gpt-4o-mini"), timeout=15)

        tid = ticket.get("ticket_id", "N/A")
        intent_lb = _intent_label(ticket)
        question = ticket.get("client_request", {}).get("question", "")

        action_ctx = {
            "VALIDATION":       f"La demande a été validée. Note agent: {kwargs.get('note', '')}",
            "REJET":            f"La demande a été rejetée. Motif: {kwargs.get('reason', '')}",
            "COMPLEMENT_REQUIS": f"Documents requis: {kwargs.get('message', '')}",
            "EN_ATTENTE_CLIENT": f"Question posée: {kwargs.get('question', '')}",
        }.get(action, action)

        system = (
            "Tu es le service client de la Banque Nationale de Mauritanie (BNM). "
            "Rédige un message professionnel, chaleureux et concis en français "
            "destiné au client. Maximum 5 phrases. Signe 'L'équipe BNM'."
        )
        user = (
            f"Ticket: {tid}\n"
            f"Type de demande: {intent_lb}\n"
            f"Question client: {question}\n"
            f"Action effectuée: {action_ctx}\n\n"
            f"Rédige le message client."
        )

        resp = llm.invoke([SystemMessage(content=system),
                          HumanMessage(content=user)])
        msg = resp.content.strip()
        return msg if len(msg) > 20 else None

    except Exception as exc:
        logger.debug("LLM message generation skipped: %s", exc)
        return None
