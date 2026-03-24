"""
Module back-office BNM v2.
Sauvegarde les conversations et gère le cycle de vie des tickets.

Machine d'états v2 :
  NOUVEAU            → EN_COURS, CLOTURE
  EN_COURS           → COMPLEMENT_REQUIS, VALIDE, REJETE,
                        EN_ATTENTE_CLIENT, CLOTURE
  COMPLEMENT_REQUIS  → EN_COURS
  EN_ATTENTE_CLIENT  → EN_COURS
  VALIDE             → CLOTURE
  REJETE             → CLOTURE
  CLOTURE            → (terminal)

Rétrocompatibilité :
  - Anciens états (EN_ATTENTE, HUMAN_TAKEOVER, BOT_RESUMED) mappés
  - Champs manquants ajoutés à la volée
"""

import json
import os
import uuid
from datetime import datetime

_BASE_DIR = os.getenv("BNM_DATA_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
CONVERSATIONS_DIR = os.path.join(_BASE_DIR, "conversations")
UPLOADS_DIR = os.path.join(_BASE_DIR, "uploads")

# ── Mapping rétrocompat anciens états ──────────────────────────────────────────
_STATE_COMPAT = {
    "EN_ATTENTE":     "NOUVEAU",
    "HUMAN_TAKEOVER": "EN_COURS",
    "BOT_RESUMED":    "EN_COURS",
}

# Transitions autorisées (matrice)
_TRANSITIONS = {
    "NOUVEAU":            {"EN_COURS", "CLOTURE"},
    "EN_COURS":           {"COMPLEMENT_REQUIS", "VALIDE", "REJETE",
                           "EN_ATTENTE_CLIENT", "CLOTURE"},
    "COMPLEMENT_REQUIS":  {"EN_COURS"},
    "EN_ATTENTE_CLIENT":  {"EN_COURS"},
    "VALIDE":             {"CLOTURE"},
    "REJETE":             {"CLOTURE"},
    "CLOTURE":            set(),
    # Legacy — acceptés mais normalisés
    "EN_ATTENTE":         {"EN_COURS", "CLOTURE"},
    "HUMAN_TAKEOVER":     {"COMPLEMENT_REQUIS", "VALIDE", "REJETE",
                           "EN_ATTENTE_CLIENT", "CLOTURE", "EN_COURS"},
    "BOT_RESUMED":        {"EN_COURS", "CLOTURE"},
}


# ── Helpers internes ───────────────────────────────────────────────────────────

def _ticket_path(ticket_id: str) -> str:
    return os.path.join(CONVERSATIONS_DIR, f"{ticket_id}.json")


def _ts() -> str:
    return datetime.now().isoformat()


def _defaults(data: dict) -> dict:
    """Applique tous les defaults rétrocompat sur un ticket chargé."""
    # Champs v1 → v2
    data.setdefault("state",          data.get("status", "NOUVEAU"))
    data.setdefault("status",         data["state"])
    data.setdefault("fallback_reason", None)
    data.setdefault("history",        [])
    data.setdefault("agent_assigned", None)

    # Nouveaux champs v2
    data.setdefault("created_at",  data.get("timestamp", _ts()))
    data.setdefault("updated_at",  data.get("timestamp", _ts()))
    data.setdefault("assigned_at", None)
    data.setdefault("due_at",      None)

    # client block (rétrocompat : anciens tickets ont client_request)
    if "client" not in data:
        data["client"] = {
            "session_id":  data.get("session_id", ""),
            "channel":     "web",
            "question":    data.get("client_request", {}).get("question", ""),
            "attachments": [],
        }

    # messages (nouveau) — initialisé à partir de history si absent
    if "messages" not in data:
        data["messages"] = _history_to_messages(data.get("history", []))

    # state_history
    data.setdefault("state_history", [])

    # documents
    data.setdefault("documents", [])

    # resolution
    data.setdefault("resolution", {
        "decision":      None,
        "decision_at":   None,
        "decision_by":   None,
        "client_message": None,
        "internal_note": None,
    })

    # rag_context
    if "rag_context" not in data:
        ctx_provided = data.get("context_provided", {})
        data["rag_context"] = {
            "response": ctx_provided.get("rag_response", ""),
            "sources":  ctx_provided.get("sources", []),
            "neo4j_enrichment": False,
        }

    # priority — normalise LOW/NORMAL/HIGH/URGENT
    if data.get("priority") not in ("LOW", "NORMAL", "HIGH", "URGENT"):
        data["priority"] = "NORMAL"

    return data


def _history_to_messages(history: list) -> list:
    """Convertit l'ancien format history[] en messages[]."""
    msgs = []
    for e in history:
        role = e.get("role", "system")
        msgs.append({
            "id":               str(uuid.uuid4()),
            "role":             role,
            "content":          e.get("message", ""),
            "timestamp":        e.get("timestamp", _ts()),
            "visible_to_client": role in ("agent", "bot"),
        })
    return msgs


def _load_ticket(ticket_id: str) -> dict:
    path = _ticket_path(ticket_id)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Ticket {ticket_id} introuvable")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return _defaults(data)


def _save(data: dict) -> None:
    os.makedirs(CONVERSATIONS_DIR, exist_ok=True)
    data["updated_at"] = _ts()
    # Sync status pour rétrocompat frontend
    data["status"] = data["state"]
    path = _ticket_path(data["ticket_id"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _transition(data: dict, new_state: str, actor: str,
                action: str, agent_id: str = None, comment: str = None) -> dict:
    """Effectue une transition d'état et enregistre dans state_history."""
    old_state = data["state"]
    data["state"] = new_state
    data["status"] = new_state

    entry = {
        "from_state": old_state,
        "to_state":   new_state,
        "action":     action,
        "actor":      actor,
        "agent_id":   agent_id,
        "comment":    comment,
        "timestamp":  _ts(),
    }
    data.setdefault("state_history", []).append(entry)

    # Ajoute aussi dans history (rétrocompat) et messages
    msg_text = comment or action
    now = entry["timestamp"]
    data.setdefault("history", []).append({
        "role":      "system" if actor in ("system", "bot") else actor,
        "message":   msg_text,
        "timestamp": now,
    })
    data.setdefault("messages", []).append({
        "id":               str(uuid.uuid4()),
        "role":             "system",
        "content":          msg_text,
        "timestamp":        now,
        "visible_to_client": False,
    })
    return data


def _add_message(data: dict, role: str, content: str,
                 visible_to_client: bool = True,
                 agent_id: str = None) -> dict:
    """Ajoute un message dans messages[] ET history[] (rétrocompat)."""
    now = _ts()
    data.setdefault("messages", []).append({
        "id":               str(uuid.uuid4()),
        "role":             role,
        "content":          content,
        "timestamp":        now,
        "visible_to_client": visible_to_client,
    })
    # rétrocompat history
    entry = {"role": role, "message": content, "timestamp": now}
    if agent_id:
        entry["agent"] = agent_id
    data.setdefault("history", []).append(entry)
    return data


# ── API publique ───────────────────────────────────────────────────────────────

def load_ticket(ticket_id: str) -> dict:
    return _load_ticket(ticket_id)


def save_ticket(
    question: str,
    intent: str,
    confidence: str,
    reason_classification: str,
    rag_response: str,
    routing_reason: str,
    priority: str,
    fallback_reason: str = None,
    session_id: str = "",
    channel: str = "web",
    sources: list = None,
    assigned_role: str = None,
    assigned_agent: str = None,
) -> tuple:
    """Crée et sauvegarde un nouveau ticket. Retourne (ticket_id, filepath)."""
    os.makedirs(CONVERSATIONS_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ticket_id = f"BNM-{timestamp}"
    now = _ts()

    initial_msg = f"Ticket créé. Motif routage : {routing_reason}"
    if fallback_reason:
        initial_msg += f" | Fallback : {fallback_reason}"

    ticket = {
        # ── Identité ────────────────────────────────────────────
        "ticket_id":   ticket_id,
        "timestamp":   now,         # rétrocompat
        "created_at":  now,
        "updated_at":  now,

        # ── Demande client ──────────────────────────────────────
        "client": {
            "session_id":  session_id,
            "channel":     channel,
            "question":    question,
            "attachments": [],
        },
        # rétrocompat
        "client_request": {"question": question},

        # ── Classification ──────────────────────────────────────
        "classification": {
            "intent":     intent,
            "confidence": confidence,
            "reason":     reason_classification,
            "source":     "llm",
        },

        # ── Routage ─────────────────────────────────────────────
        "routing": {
            "channel":  "BACKOFFICE",
            "reason":   routing_reason,
            "priority": priority,
        },

        # ── Cycle de vie ────────────────────────────────────────
        "priority":      priority,
        "state":         "NOUVEAU",
        "status":        "NOUVEAU",      # rétrocompat
        "fallback_reason": fallback_reason,
        "agent_assigned":  None,
        "assigned_at":     None,
        "due_at":          None,

        # ── Affectation automatique ──────────────────────────────
        "assigned_role":     assigned_role or _intent_to_role(intent),
        "assigned_agent":    assigned_agent,
        "assignment_status": "AFFECTE" if assigned_agent else "EN_ATTENTE_AFFECTATION",
        "assigned_at":       now if assigned_agent else None,

        # ── Historique ──────────────────────────────────────────
        "state_history": [
            {
                "from_state": None,
                "to_state":   "NOUVEAU",
                "action":     "creation",
                "actor":      "system",
                "agent_id":   None,
                "comment":    initial_msg,
                "timestamp":  now,
            },
            {
                "from_state": None,
                "to_state":   "NOUVEAU",
                "action":     "AFFECTATION_AUTOMATIQUE",
                "actor":      "system",
                "to":         assigned_agent or "file d'attente",
                "comment":    f"Affecté à {assigned_agent}" if assigned_agent else "En attente d'affectation",
                "timestamp":  now,
            },
        ],
        "history": [{"role": "system", "message": initial_msg, "timestamp": now}],
        "messages": [{
            "id":               str(uuid.uuid4()),
            "role":             "system",
            "content":          initial_msg,
            "timestamp":        now,
            "visible_to_client": False,
        }],

        # ── Documents ───────────────────────────────────────────
        "documents": [],

        # ── Résolution ──────────────────────────────────────────
        "resolution": {
            "decision":      None,
            "decision_at":   None,
            "decision_by":   None,
            "client_message": None,
            "internal_note": None,
        },

        # ── Contexte RAG ────────────────────────────────────────
        "rag_context": {
            "response": rag_response,
            "sources":  sources or [],
            "neo4j_enrichment": False,
        },
        # rétrocompat
        "context_provided": {
            "rag_response": rag_response,
            "note": "Réponse RAG fournie à titre informatif pour l'agent",
        },
    }

    filepath = _ticket_path(ticket_id)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(ticket, f, ensure_ascii=False, indent=2)

    return ticket_id, filepath


# ── Transitions d'état ────────────────────────────────────────────────────────

def assign_ticket(ticket_id: str, agent_name: str) -> dict:
    """NOUVEAU / EN_COURS → EN_COURS (avec assignation agent)."""
    data = _load_ticket(ticket_id)
    data = _transition(data, "EN_COURS", "agent", f"Prise en charge par {agent_name}",
                       agent_id=agent_name)
    data["agent_assigned"] = agent_name
    data["assigned_at"] = _ts()
    _save(data)
    return data


def reply_ticket(ticket_id: str, agent_name: str, message: str) -> dict:
    """Ajoute un message agent (visible client). Reste EN_COURS."""
    data = _load_ticket(ticket_id)
    data = _add_message(data, "agent", message,
                        visible_to_client=True, agent_id=agent_name)
    # Assure l'état EN_COURS si pas déjà
    if data["state"] not in ("EN_COURS", "HUMAN_TAKEOVER"):
        data = _transition(data, "EN_COURS", "agent",
                           f"Prise en charge par {agent_name}", agent_id=agent_name)
        data["agent_assigned"] = agent_name
    _save(data)
    return data


def return_to_bot(ticket_id: str) -> dict:
    """EN_COURS → EN_COURS (marquage retour bot, legacy BOT_RESUMED)."""
    data = _load_ticket(ticket_id)
    data["state"] = "EN_COURS"
    data["status"] = "EN_COURS"
    data = _add_message(data, "system", "Conversation rendue au chatbot",
                        visible_to_client=False)
    _save(data)
    return data


def close_ticket(ticket_id: str) -> dict:
    """Tout état → CLOTURE."""
    data = _load_ticket(ticket_id)
    data = _transition(data, "CLOTURE", "agent", "Ticket clôturé")
    _save(data)
    return data


def reopen_ticket(ticket_id: str, agent_id: str = "admin") -> dict:
    """CLOTURE → EN_COURS (admin uniquement). Rouvre un ticket clôturé par erreur."""
    data = _load_ticket(ticket_id)
    data = _transition(
        data, "EN_COURS", "agent",
        "Ticket rouvert par l'administrateur",
        agent_id=agent_id,
        comment="Rouvert par l'administrateur",
    )
    _save(data)
    return data


def request_complement(ticket_id: str, message: str, agent_name: str = "agent") -> dict:
    """EN_COURS → COMPLEMENT_REQUIS. Génère message client."""
    from message_generator import generate_client_message
    data = _load_ticket(ticket_id)
    client_msg = generate_client_message(
        data, "COMPLEMENT_REQUIS", message=message)
    data = _transition(data, "COMPLEMENT_REQUIS", "agent",
                       f"Complément requis : {message}", agent_id=agent_name)
    data = _add_message(data, "agent", client_msg,
                        visible_to_client=True, agent_id=agent_name)
    data["resolution"]["client_message"] = client_msg
    _save(data)
    return data


def validate_ticket(ticket_id: str, agent_name: str, note: str = "") -> dict:
    """EN_COURS → VALIDE. Génère message client."""
    from message_generator import generate_client_message
    data = _load_ticket(ticket_id)
    client_msg = generate_client_message(data, "VALIDATION", note=note)
    data = _transition(data, "VALIDE", "agent",
                       "Ticket validé", agent_id=agent_name, comment=note or None)
    data = _add_message(data, "agent", client_msg,
                        visible_to_client=True, agent_id=agent_name)
    data["resolution"].update({
        "decision":       "validated",
        "decision_at":    _ts(),
        "decision_by":    agent_name,
        "client_message": client_msg,
        "internal_note":  note or None,
    })
    _save(data)
    return data


def reject_ticket(ticket_id: str, agent_name: str, reason: str) -> dict:
    """EN_COURS → REJETE. Génère message client."""
    from message_generator import generate_client_message
    data = _load_ticket(ticket_id)
    client_msg = generate_client_message(data, "REJET", reason=reason)
    data = _transition(data, "REJETE", "agent",
                       f"Ticket rejeté : {reason}", agent_id=agent_name)
    data = _add_message(data, "agent", client_msg,
                        visible_to_client=True, agent_id=agent_name)
    data["resolution"].update({
        "decision":       "rejected",
        "decision_at":    _ts(),
        "decision_by":    agent_name,
        "client_message": client_msg,
        "internal_note":  reason,
    })
    _save(data)
    return data


def ask_client(ticket_id: str, question: str, agent_name: str = "agent") -> dict:
    """EN_COURS → EN_ATTENTE_CLIENT."""
    from message_generator import generate_client_message
    data = _load_ticket(ticket_id)
    client_msg = generate_client_message(
        data, "EN_ATTENTE_CLIENT", question=question)
    data = _transition(data, "EN_ATTENTE_CLIENT", "agent",
                       f"Question posée au client : {question}", agent_id=agent_name)
    data = _add_message(data, "agent", client_msg,
                        visible_to_client=True, agent_id=agent_name)
    data["resolution"]["client_message"] = client_msg
    _save(data)
    return data


def add_comment(ticket_id: str, comment: str,
                visible_to_client: bool = False,
                agent_name: str = "agent") -> dict:
    """Ajoute un commentaire (interne ou visible)."""
    data = _load_ticket(ticket_id)
    data = _add_message(data, "agent", comment,
                        visible_to_client=visible_to_client, agent_id=agent_name)
    _save(data)
    return data


def set_priority(ticket_id: str, priority: str) -> dict:
    """Met à jour la priorité."""
    valid = {"LOW", "NORMAL", "HIGH", "URGENT"}
    if priority not in valid:
        raise ValueError(f"Priorité invalide : {priority}")
    data = _load_ticket(ticket_id)
    old = data.get("priority", "NORMAL")
    data["priority"] = priority
    data["routing"]["priority"] = priority
    data = _add_message(data, "system",
                        f"Priorité changée : {old} → {priority}",
                        visible_to_client=False)
    _save(data)
    return data


def client_responds(ticket_id: str, message: str) -> dict:
    """Client répond → EN_ATTENTE_CLIENT → EN_COURS."""
    data = _load_ticket(ticket_id)
    data = _add_message(data, "client", message, visible_to_client=True)
    if data["state"] == "EN_ATTENTE_CLIENT":
        data = _transition(data, "EN_COURS", "system",
                           "Client a répondu — retour EN_COURS")
    _save(data)
    return data


# ── Requêtes utilitaires ──────────────────────────────────────────────────────

def find_by_session(session_id: str) -> dict | None:
    """Retourne le ticket le plus récent pour une session_id."""
    if not session_id:
        return None
    conv_dir = CONVERSATIONS_DIR
    if not os.path.exists(conv_dir):
        return None
    found = []
    for f in os.listdir(conv_dir):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(conv_dir, f), encoding="utf-8") as fp:
                t = json.load(fp)
            t = _defaults(t)
            sid = t.get("client", {}).get(
                "session_id", "") or t.get("session_id", "")
            if sid == session_id:
                found.append(t)
        except Exception:
            pass
    if not found:
        return None
    found.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return found[0]


def ticket_stats() -> dict:
    """Stats agrégées des tickets."""
    stats = {
        "total":        0,
        "par_state":    {},
        "par_intent":   {},
        "par_priority": {},
        "par_agent":    {},
    }
    conv_dir = CONVERSATIONS_DIR
    if not os.path.exists(conv_dir):
        return stats
    for f in os.listdir(conv_dir):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(conv_dir, f), encoding="utf-8") as fp:
                t = json.load(fp)
            stats["total"] += 1
            state = t.get("state", "NOUVEAU")
            intent = t.get("classification", {}).get("intent", "?")
            prio = t.get("priority", "NORMAL")
            agent = t.get("agent_assigned") or "non assigné"
            stats["par_state"][state] = stats["par_state"].get(state, 0) + 1
            stats["par_intent"][intent] = stats["par_intent"].get(
                intent, 0) + 1
            stats["par_priority"][prio] = stats["par_priority"].get(
                prio, 0) + 1
            stats["par_agent"][agent] = stats["par_agent"].get(agent, 0) + 1
        except Exception:
            pass
    return stats


# ── Formatage message client (rétrocompat) ────────────────────────────────────

def format_backoffice_message(ticket_id: str, intent: str,
                              priority: str, routing_reason: str) -> str:
    """Formate le message affiché au client lors du transfert (rétrocompat v1)."""
    priority_label = "🔴 URGENT" if priority in (
        "HIGH", "URGENT") else "🟡 NORMAL"
    sep = "══" * 21

    if intent == "RECLAMATION":
        msg = (
            f"\n{sep}\n TRANSFERT VERS BACK-OFFICE\n{sep}\n"
            f" Ticket     : {ticket_id}\n"
            f" Priorité   : {priority_label}\n"
            f" Motif      : {routing_reason}\n{sep}\n"
            f" Votre réclamation a été enregistrée.\n"
            f" Un agent BNM va traiter votre demande dans les plus brefs délais.\n"
            f" Référence ticket : {ticket_id}\n{sep}\n"
        )
    elif intent == "VALIDATION":
        msg = (
            f"\n{sep}\n TRANSFERT VERS BACK-OFFICE\n{sep}\n"
            f" Ticket     : {ticket_id}\n"
            f" Priorité   : {priority_label}\n"
            f" Motif      : {routing_reason}\n{sep}\n"
            f" Votre demande de validation a été transmise à notre équipe.\n"
            f" Un conseiller vous contactera pour confirmer votre demande.\n"
            f" Référence ticket : {ticket_id}\n{sep}\n"
        )
    else:
        msg = (
            f"\n{sep}\n MISE EN RELATION AVEC UN AGENT\n{sep}\n"
            f" Ticket     : {ticket_id}\n"
            f" Priorité   : {priority_label}\n"
            f" Motif      : {routing_reason}\n{sep}\n"
            f" Votre demande de contact humain a été enregistrée.\n"
            f" Un agent BNM vous prendra en charge très prochainement.\n"
            f" Référence ticket : {ticket_id}\n{sep}\n"
        )
    return msg


# ── Affectation automatique ────────────────────────────────────────────────────

def _intent_to_role(intent: str) -> str:
    """Mappe l'intent vers le rôle agent correspondant."""
    return {"VALIDATION": "VALIDATION", "RECLAMATION": "RECLAMATION"}.get(
        intent, "INFORMATION"
    )


def pick_agent_for_role(role: str, db_params: dict) -> str | None:
    """
    Round-robin simple : sélectionne l'agent du rôle
    avec le moins de tickets NOUVEAU+EN_COURS.
    Retourne username ou None.
    """
    try:
        import psycopg2 as _psycopg2
        conn = _psycopg2.connect(**db_params)
        cur  = conn.cursor()
        cur.execute(
            "SELECT username FROM users WHERE agent_role = %s ORDER BY username",
            (role,)
        )
        agents = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        if not agents:
            return None
        charges = {a: 0 for a in agents}
        if os.path.exists(CONVERSATIONS_DIR):
            for f in os.listdir(CONVERSATIONS_DIR):
                if not f.endswith(".json"):
                    continue
                try:
                    with open(
                        os.path.join(CONVERSATIONS_DIR, f), encoding="utf-8"
                    ) as fp:
                        t = json.load(fp)
                    agent = t.get("assigned_agent")
                    state = t.get("state", "NOUVEAU")
                    if agent in charges and state in ("NOUVEAU", "EN_COURS"):
                        charges[agent] += 1
                except Exception:
                    pass
        return min(charges, key=charges.get)
    except Exception:
        return None
