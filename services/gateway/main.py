"""
Gateway — port 8000
Point d'entrée unique pour le frontend.
Redirige transparemment vers les services appropriés.
"""
import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import httpx

load_dotenv()

app = FastAPI(title="BNM Gateway", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

AUTH_URL     = os.getenv("AUTH_SERVICE_URL",     "http://localhost:8001")
CHAT_URL     = os.getenv("CHAT_SERVICE_URL",     "http://localhost:8002")
TICKET_URL   = os.getenv("TICKET_SERVICE_URL",   "http://localhost:8003")
DOCUMENT_URL = os.getenv("DOCUMENT_SERVICE_URL", "http://localhost:8004")
ADMIN_URL    = os.getenv("ADMIN_SERVICE_URL",    "http://localhost:8005")

# Headers à ne pas transférer (gérés par httpx)
_SKIP_HEADERS = {"host", "content-length", "transfer-encoding", "connection"}


async def proxy(request: Request, target_base: str) -> Response:
    """Proxy générique — transfère la requête vers le service cible."""
    url = target_base + str(request.url.path)
    if request.url.query:
        url += "?" + request.url.query

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _SKIP_HEADERS
    }
    body = await request.body()

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=body,
        )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


# ── Auth ─────────────────────────────────────────────────────────────────────

@app.api_route("/auth/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def gateway_auth(request: Request, path: str):
    return await proxy(request, AUTH_URL)


# ── Chat / RAG ────────────────────────────────────────────────────────────────

@app.api_route("/ask", methods=["POST"])
async def gateway_ask(request: Request):
    return await proxy(request, CHAT_URL)


@app.api_route("/client/{path:path}", methods=["GET", "POST"])
async def gateway_client(request: Request, path: str):
    return await proxy(request, CHAT_URL)


@app.api_route("/history/{path:path}", methods=["GET"])
async def gateway_history(request: Request, path: str):
    return await proxy(request, CHAT_URL)


@app.api_route("/users/{path:path}", methods=["GET", "POST"])
async def gateway_users(request: Request, path: str):
    return await proxy(request, CHAT_URL)


@app.api_route("/sessions/{path:path}", methods=["GET", "POST"])
async def gateway_sessions(request: Request, path: str):
    return await proxy(request, TICKET_URL)


# ── Documents — avant /tickets/ pour la priorité de routage ──────────────────
# Les uploads/downloads de documents sont délégués au document-service

@app.api_route("/tickets/{ticket_id}/documents/{doc_id}", methods=["GET"])
async def gateway_doc_download(request: Request, ticket_id: str, doc_id: str):
    return await proxy(request, DOCUMENT_URL)


@app.api_route("/tickets/{ticket_id}/documents", methods=["GET", "POST"])
async def gateway_docs(request: Request, ticket_id: str):
    return await proxy(request, DOCUMENT_URL)


# ── Tickets ───────────────────────────────────────────────────────────────────

@app.api_route("/tickets", methods=["GET"])
async def gateway_tickets_list(request: Request):
    return await proxy(request, TICKET_URL)


@app.api_route("/tickets/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def gateway_tickets(request: Request, path: str):
    return await proxy(request, TICKET_URL)


@app.api_route("/conversations/{path:path}", methods=["GET"])
async def gateway_conversations(request: Request, path: str):
    return await proxy(request, TICKET_URL)


# ── Stats / Admin ─────────────────────────────────────────────────────────────

@app.api_route("/stats/{path:path}", methods=["GET"])
async def gateway_stats(request: Request, path: str):
    return await proxy(request, ADMIN_URL)


@app.api_route("/admin/{path:path}", methods=["GET", "POST"])
async def gateway_admin(request: Request, path: str):
    return await proxy(request, ADMIN_URL)


# ── Agents ────────────────────────────────────────────────────────────────────

@app.api_route("/agents", methods=["GET"])
async def gateway_agents(request: Request):
    return await proxy(request, TICKET_URL)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "gateway"}
