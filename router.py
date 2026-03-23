"""
Module de routage des intentions client BNM.

Règles :
- INFORMATION  → CHATBOT  (réponse automatique)
- RECLAMATION  → BACKOFFICE (transfert humain)
- VALIDATION   → BACKOFFICE (transfert humain)
- Demande humain explicite → BACKOFFICE (priorité absolue)
"""

import re

# Mots-clés détectant une demande de contact humain
HUMAN_REQUEST_PATTERNS = [
    r"parler.*(humain|personne|conseiller|agent|quelqu.un)",
    r"contacter.*(humain|personne|conseiller|agent)",
    r"besoin.*(humain|personne|conseiller|agent)",
    r"transferr",
    r"mettr.*(en relation|en contact)",
    r"je veux.*(humain|personne|agent)",
    r"un agent",
    r"un conseiller",
    r"service client",
]


def detect_human_request(question: str) -> bool:
    """Détecte si le client demande explicitement à parler à un humain."""
    question_lower = question.lower()
    for pattern in HUMAN_REQUEST_PATTERNS:
        if re.search(pattern, question_lower):
            return True
    return False


def route(intent: str, question: str) -> dict:
    """
    Détermine le canal de traitement.

    Retourne :
    {
        "channel": "CHATBOT" | "BACKOFFICE",
        "reason": str,
        "priority": "NORMAL" | "HIGH"
    }
    """
    # Priorité absolue : demande humain explicite
    if detect_human_request(question):
        return {
            "channel": "BACKOFFICE",
            "reason": "Client demande explicitement un agent humain",
            "priority": "HIGH"
        }

    # Routage par intention
    if intent == "INFORMATION":
        return {
            "channel": "CHATBOT",
            "reason": "Demande d'information — réponse automatique",
            "priority": "NORMAL"
        }
    elif intent == "RECLAMATION":
        return {
            "channel": "BACKOFFICE",
            "reason": "Réclamation client — nécessite traitement humain",
            "priority": "HIGH"
        }
    elif intent == "VALIDATION":
        return {
            "channel": "BACKOFFICE",
            "reason": "Validation de demande — nécessite confirmation humaine",
            "priority": "NORMAL"
        }
    else:
        return {
            "channel": "CHATBOT",
            "reason": "Intention non reconnue — réponse automatique",
            "priority": "NORMAL"
        }
