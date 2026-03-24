"""
Admin Service — port 8005
Statistiques et supervision des tickets et agents.

Endpoints :
  GET /stats/tickets
  GET /admin/stats
  GET /admin/agents/{username}/tickets
"""
import json
import os
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from auth import get_current_user
from backoffice import CONVERSATIONS_DIR, ticket_stats

load_dotenv()

app = FastAPI(title="BNM Admin Service", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/stats/tickets")
def stats_tickets():
    """Stats agrégées des tickets."""
    return ticket_stats()


@app.get("/admin/stats")
def admin_stats(_user=Depends(get_current_user)):
    if _user.get("agent_role") != "ADMIN":
        raise HTTPException(403, "Accès ADMIN requis")

    stats = {
        "total": 0, "par_state": {}, "par_role": {},
        "par_agent": {}, "par_jour": {},
    }
    today = datetime.now().date()
    days  = {str(today - timedelta(days=i)): 0 for i in range(6, -1, -1)}

    if os.path.exists(CONVERSATIONS_DIR):
        for f in os.listdir(CONVERSATIONS_DIR):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(CONVERSATIONS_DIR, f), encoding="utf-8") as fp:
                    t = json.load(fp)
                stats["total"] += 1
                state   = t.get("state", "NOUVEAU")
                role_t  = t.get("assigned_role", "?")
                agent   = t.get("assigned_agent") or "non_affecte"
                created = t.get("created_at", "")[:10]
                stats["par_state"][state] = stats["par_state"].get(state, 0) + 1
                stats["par_role"][role_t] = stats["par_role"].get(role_t, 0) + 1
                if created in days:
                    days[created] += 1
                if agent not in stats["par_agent"]:
                    stats["par_agent"][agent] = {
                        "username": agent, "total": 0, "traites": 0, "en_cours": 0,
                    }
                stats["par_agent"][agent]["total"] += 1
                if state in ("VALIDE", "REJETE", "CLOTURE"):
                    stats["par_agent"][agent]["traites"] += 1
                elif state in ("NOUVEAU", "EN_COURS"):
                    stats["par_agent"][agent]["en_cours"] += 1
            except Exception:
                pass

    stats["par_jour"]  = days
    stats["par_agent"] = list(stats["par_agent"].values())
    return stats


@app.get("/admin/agents/{username}/tickets")
def admin_agent_tickets(username: str, _user=Depends(get_current_user)):
    if _user.get("agent_role") != "ADMIN":
        raise HTTPException(403, "Accès ADMIN requis")

    result = []
    if os.path.exists(CONVERSATIONS_DIR):
        for f in sorted(os.listdir(CONVERSATIONS_DIR), reverse=True):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(CONVERSATIONS_DIR, f), encoding="utf-8") as fp:
                    t = json.load(fp)
                if t.get("assigned_agent") == username:
                    result.append(t)
            except Exception:
                pass
    return result


@app.get("/health")
def health():
    return {"status": "ok", "service": "admin-service"}
