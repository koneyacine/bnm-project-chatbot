"""
Ticket Service — port 8003
Gestion du cycle de vie des tickets (workflow métier).

Endpoints :
  GET  /tickets
  GET  /tickets/{id}
  GET  /tickets/by-session/{session_id}
  GET  /tickets/{id}/client-message
  POST /tickets/{id}/assign
  POST /tickets/{id}/reply
  POST /tickets/{id}/return-to-bot
  POST /tickets/{id}/close
  POST /tickets/{id}/reopen
  POST /tickets/{id}/request-complement
  POST /tickets/{id}/validate
  POST /tickets/{id}/reject
  POST /tickets/{id}/ask-client
  POST /tickets/{id}/add-comment
  POST /tickets/{id}/set-priority
  POST /tickets/{id}/client-response
  GET  /conversations/{id}
  GET  /agents
  POST /sessions/{session_id}/link
"""
import json
import os
from typing import Optional

import psycopg2
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from auth import get_current_user, verify_token
from backoffice import (
    CONVERSATIONS_DIR,
    add_comment,
    ask_client,
    assign_ticket,
    client_responds,
    close_ticket,
    find_by_session,
    load_ticket,
    reject_ticket,
    reopen_ticket,
    reply_ticket,
    request_complement,
    return_to_bot,
    set_priority,
    ticket_stats,
    validate_ticket,
)
from conversation_store import link_session_to_user, save_message
from permissions import can_access_ticket

load_dotenv()

app = FastAPI(title="BNM Ticket Service", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_DB_PARAMS = dict(
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
)
_conn_global = None


def get_conn():
    global _conn_global
    if _conn_global is None:
        _conn_global = psycopg2.connect(**_DB_PARAMS)
    try:
        _conn_global.cursor().execute("SELECT 1")
    except Exception:
        _conn_global = psycopg2.connect(**_DB_PARAMS)
    return _conn_global


# ── Pydantic models ───────────────────────────────────────────────────────────

class AssignBody(BaseModel):
    agent: str

class ReplyBody(BaseModel):
    agent: str
    message: str

class ComplementBody(BaseModel):
    message: str
    agent: Optional[str] = "agent"

class ValidateBody(BaseModel):
    note: Optional[str] = ""
    agent: Optional[str] = "agent"

class RejectBody(BaseModel):
    reason: str
    agent: Optional[str] = "agent"

class AskClientBody(BaseModel):
    question: str
    agent: Optional[str] = "agent"

class CommentBody(BaseModel):
    comment: str
    visible_to_client: Optional[bool] = False
    agent: Optional[str] = "agent"

class PriorityBody(BaseModel):
    priority: str

class ClientResponseBody(BaseModel):
    message: str

class LinkSessionBody(BaseModel):
    user_id: str


# ── Helper ────────────────────────────────────────────────────────────────────

def _normalize_ticket(t: dict) -> dict:
    t.setdefault("state", t.get("status", "NOUVEAU"))
    t.setdefault("history", [])
    t.setdefault("fallback_reason", None)
    t.setdefault("messages", [])
    t.setdefault("documents", [])
    t.setdefault("resolution", {
        "decision": None, "decision_at": None,
        "decision_by": None, "client_message": None, "internal_note": None,
    })
    return t


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/tickets")
def list_tickets(
    state:    Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    intent:   Optional[str] = Query(None),
    role:     Optional[str] = Query(None),
    creds: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
):
    user_payload = None
    if creds and creds.credentials:
        user_payload = verify_token(creds.credentials)
    if user_payload:
        agent_role_from_token = user_payload.get("agent_role")
        if agent_role_from_token and agent_role_from_token != "ADMIN" and not role:
            role = agent_role_from_token

    tickets = []
    if os.path.exists(CONVERSATIONS_DIR):
        for f in sorted(os.listdir(CONVERSATIONS_DIR), reverse=True):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(CONVERSATIONS_DIR, f), encoding="utf-8") as fp:
                    t = json.load(fp)
                t = _normalize_ticket(t)
                if state    and t.get("state") != state: continue
                if priority and t.get("priority") != priority: continue
                if intent   and t.get("classification", {}).get("intent") != intent: continue
                if role:
                    if role == "VALIDATION":
                        if t.get("classification", {}).get("intent") != "VALIDATION": continue
                    elif role == "RECLAMATION":
                        if t.get("classification", {}).get("intent") != "RECLAMATION": continue
                    elif role == "INFORMATION":
                        if not (t.get("classification", {}).get("intent") == "INFORMATION"
                                and t.get("routing", {}).get("channel") == "BACKOFFICE"):
                            continue
                tickets.append(t)
            except Exception:
                pass
    _prio_order = {"URGENT": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
    tickets.sort(key=lambda x: (
        _prio_order.get(x.get("priority", "NORMAL"), 2),
        x.get("created_at", x.get("timestamp", "")),
    ))
    return tickets


@app.get("/tickets/by-session/{session_id}")
def ticket_by_session(session_id: str):
    t = find_by_session(session_id)
    if not t:
        raise HTTPException(404, "Aucun ticket pour cette session")
    return t


@app.get("/tickets/{ticket_id}/client-message")
def get_client_message(ticket_id: str):
    try:
        t = load_ticket(ticket_id)
        msg = t.get("resolution", {}).get("client_message")
        return {"ticket_id": ticket_id, "state": t.get("state"), "client_message": msg}
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str):
    try:
        return load_ticket(ticket_id)
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")


@app.get("/conversations/{ticket_id}")
def get_conversation(ticket_id: str):
    try:
        ticket = load_ticket(ticket_id)
        return {
            "ticket_id": ticket["ticket_id"],
            "state": ticket.get("state", "NOUVEAU"),
            "agent_assigned": ticket.get("agent_assigned"),
            "fallback_reason": ticket.get("fallback_reason"),
            "history": ticket.get("history", []),
        }
    except FileNotFoundError:
        raise HTTPException(404, "Conversation introuvable")


@app.post("/tickets/{ticket_id}/assign")
def ticket_assign(ticket_id: str, body: AssignBody, _user=Depends(get_current_user)):
    try:
        _td = load_ticket(ticket_id)
        if not can_access_ticket(_user, _td):
            raise HTTPException(403, "Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")
    data = assign_ticket(ticket_id, body.agent)
    return {"status": "ok", "state": data["state"], "agent_assigned": data["agent_assigned"]}


@app.post("/tickets/{ticket_id}/reply")
def ticket_reply(ticket_id: str, body: ReplyBody, _user=Depends(get_current_user)):
    try:
        _td = load_ticket(ticket_id)
        if not can_access_ticket(_user, _td):
            raise HTTPException(403, "Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")
    data = reply_ticket(ticket_id, body.agent, body.message)
    session_id = _td.get("client", {}).get("session_id", "")
    if session_id:
        save_message(session_id=session_id, role="agent", content=body.message,
                     intent=_td.get("classification", {}).get("intent"),
                     meta={"agent": body.agent, "ticket_id": ticket_id,
                           "action": "reply", "role_display": f"Conseiller BNM ({body.agent})"})
    return {"status": "ok", "history_length": len(data["history"])}


@app.post("/tickets/{ticket_id}/return-to-bot")
def ticket_return_to_bot(ticket_id: str):
    try:
        data = return_to_bot(ticket_id)
        return {"status": "ok", "state": data["state"]}
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")


@app.post("/tickets/{ticket_id}/close")
def ticket_close(ticket_id: str, _user=Depends(get_current_user)):
    try:
        _td = load_ticket(ticket_id)
        if not can_access_ticket(_user, _td):
            raise HTTPException(403, "Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")
    data = close_ticket(ticket_id)
    return {"status": "ok", "state": data["state"]}


@app.post("/tickets/{ticket_id}/reopen")
def ticket_reopen(ticket_id: str, u=Depends(get_current_user)):
    if u.get("agent_role") != "ADMIN":
        raise HTTPException(403, "ADMIN uniquement")
    try:
        data = reopen_ticket(ticket_id, agent_id=u.get("username", "admin"))
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")
    return {"status": "ok", "state": data["state"], "ticket_id": ticket_id}


@app.post("/tickets/{ticket_id}/request-complement")
def ticket_request_complement(ticket_id: str, body: ComplementBody, _user=Depends(get_current_user)):
    try:
        _td = load_ticket(ticket_id)
        if not can_access_ticket(_user, _td):
            raise HTTPException(403, "Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")
    data = request_complement(ticket_id, body.message, body.agent or "agent")
    session_id = _td.get("client", {}).get("session_id", "")
    client_msg = data["resolution"].get("client_message") or body.message
    if session_id and client_msg:
        save_message(session_id=session_id, role="agent", content=client_msg,
                     intent=_td.get("classification", {}).get("intent"),
                     meta={"agent": body.agent or "BNM", "ticket_id": ticket_id,
                           "action": "request_complement", "role_display": "Conseiller BNM"})
    return {"status": "ok", "state": data["state"], "client_message": client_msg}


@app.post("/tickets/{ticket_id}/validate")
def ticket_validate(ticket_id: str, body: ValidateBody, _user=Depends(get_current_user)):
    try:
        _td = load_ticket(ticket_id)
        if not can_access_ticket(_user, _td):
            raise HTTPException(403, "Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")
    data = validate_ticket(ticket_id, body.agent or "agent", body.note or "")
    session_id = _td.get("client", {}).get("session_id", "")
    client_msg = data["resolution"].get("client_message")
    if session_id and client_msg:
        save_message(session_id=session_id, role="agent", content=client_msg,
                     intent="VALIDATION",
                     meta={"agent": body.agent or "agent", "ticket_id": ticket_id,
                           "action": "validate", "role_display": "✅ Conseiller BNM"})
    return {"status": "ok", "state": data["state"], "client_message": client_msg}


@app.post("/tickets/{ticket_id}/reject")
def ticket_reject(ticket_id: str, body: RejectBody, _user=Depends(get_current_user)):
    try:
        _td = load_ticket(ticket_id)
        if not can_access_ticket(_user, _td):
            raise HTTPException(403, "Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")
    data = reject_ticket(ticket_id, body.agent or "agent", body.reason)
    session_id = _td.get("client", {}).get("session_id", "")
    client_msg = data["resolution"].get("client_message")
    if session_id and client_msg:
        save_message(session_id=session_id, role="agent", content=client_msg,
                     intent=_td.get("classification", {}).get("intent"),
                     meta={"agent": body.agent or "agent", "ticket_id": ticket_id,
                           "action": "reject", "role_display": "❌ Conseiller BNM"})
    return {"status": "ok", "state": data["state"], "client_message": client_msg}


@app.post("/tickets/{ticket_id}/ask-client")
def ticket_ask_client(ticket_id: str, body: AskClientBody, _user=Depends(get_current_user)):
    try:
        _td = load_ticket(ticket_id)
        if not can_access_ticket(_user, _td):
            raise HTTPException(403, "Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")
    data = ask_client(ticket_id, body.question, body.agent or "agent")
    session_id = _td.get("client", {}).get("session_id", "")
    client_msg = data["resolution"].get("client_message") or body.question
    if session_id and client_msg:
        save_message(session_id=session_id, role="agent", content=client_msg,
                     intent=_td.get("classification", {}).get("intent"),
                     meta={"agent": body.agent or "agent", "ticket_id": ticket_id,
                           "action": "ask_client", "role_display": "👤 Conseiller BNM"})
    return {"status": "ok", "state": data["state"], "client_message": client_msg}


@app.post("/tickets/{ticket_id}/add-comment")
def ticket_add_comment(ticket_id: str, body: CommentBody, _user=Depends(get_current_user)):
    try:
        _td = load_ticket(ticket_id)
        if not can_access_ticket(_user, _td):
            raise HTTPException(403, "Accès refusé à ce ticket")
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")
    data = add_comment(ticket_id, body.comment, body.visible_to_client, body.agent or "agent")
    return {"status": "ok", "messages_count": len(data.get("messages", []))}


@app.post("/tickets/{ticket_id}/set-priority")
def ticket_set_priority(ticket_id: str, body: PriorityBody):
    try:
        data = set_priority(ticket_id, body.priority)
        return {"status": "ok", "priority": data["priority"]}
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/tickets/{ticket_id}/client-response")
def ticket_client_response(ticket_id: str, body: ClientResponseBody):
    try:
        data = client_responds(ticket_id, body.message)
        return {"status": "ok", "state": data["state"]}
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")


@app.get("/stats/tickets")
def stats_tickets():
    return ticket_stats()


@app.get("/agents")
def list_agents(role: Optional[str] = Query(None)):
    try:
        cur2 = get_conn().cursor()
        if role:
            cur2.execute("SELECT username, agent_role FROM users WHERE agent_role = %s ORDER BY username", (role,))
        else:
            cur2.execute("SELECT username, agent_role FROM users WHERE agent_role IS NOT NULL ORDER BY username")
        rows = cur2.fetchall()
        cur2.close()
    except Exception:
        rows = []

    result = []
    for username, agent_role_val in rows:
        total = en_cours = 0
        if os.path.exists(CONVERSATIONS_DIR):
            for f in os.listdir(CONVERSATIONS_DIR):
                if not f.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(CONVERSATIONS_DIR, f), encoding="utf-8") as fp:
                        t = json.load(fp)
                    if t.get("assigned_agent") == username:
                        total += 1
                        if t.get("state") in ("NOUVEAU", "EN_COURS"):
                            en_cours += 1
                except Exception:
                    pass
        result.append({"username": username, "agent_role": agent_role_val,
                        "total": total, "en_cours": en_cours})
    return result


@app.post("/sessions/{session_id}/link")
def link_session(session_id: str, body: LinkSessionBody, _user=Depends(get_current_user)):
    link_session_to_user(session_id, body.user_id)
    return {"status": "ok", "session_id": session_id, "user_id": body.user_id}


@app.get("/health")
def health():
    return {"status": "ok", "service": "ticket-service"}
