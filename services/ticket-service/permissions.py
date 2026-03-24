"""
permissions.py — Matrice des droits BNM Chatbot.
"""

ROLE_MATRIX = {
    None: {"allow": ["/ask", "/client/session", "/history/phone/"]},
    "VALIDATION":  {"tickets_role": "VALIDATION"},
    "RECLAMATION": {"tickets_role": "RECLAMATION"},
    "INFORMATION": {"tickets_role": "INFORMATION"},
    "ADMIN":       {"tickets_role": None},
}


def can_access_ticket(user_payload: dict, ticket: dict) -> bool:
    """Vérifie que l'agent a le droit d'accéder à ce ticket."""
    agent_role = user_payload.get("agent_role")
    if not agent_role or agent_role == "ADMIN":
        return True
    assigned_role = ticket.get("assigned_role")
    # Rétrocompatibilité : si le ticket n'a pas de assigned_role, accès permis
    if not assigned_role:
        return True
    return agent_role == assigned_role
