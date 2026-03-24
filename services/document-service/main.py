"""
Document Service — port 8004
Upload et téléchargement de documents liés aux tickets.

Endpoints :
  POST /tickets/{ticket_id}/documents
  GET  /tickets/{ticket_id}/documents
  GET  /tickets/{ticket_id}/documents/{doc_id}
"""
import time
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backoffice import UPLOADS_DIR, _add_message, _save, load_ticket
from conversation_store import save_message

load_dotenv()

app = FastAPI(title="BNM Document Service", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/tickets/{ticket_id}/documents")
async def upload_document(
    ticket_id: str,
    file: UploadFile = File(...),
    creds: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
):
    """Upload un document pour ce ticket (client ou agent)."""
    try:
        t = load_ticket(ticket_id)
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")

    uploaded_by = "agent" if (creds and creds.credentials) else "client"

    dest_dir = Path(UPLOADS_DIR) / ticket_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    doc_id   = str(uuid.uuid4())
    filename = file.filename or f"file_{doc_id}"
    safe_fn  = "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
    dest     = dest_dir / f"{doc_id}_{safe_fn}"

    content = await file.read()
    dest.write_bytes(content)

    doc_entry = {
        "doc_id":       doc_id,
        "filename":     safe_fn,
        "mime_type":    file.content_type or "application/octet-stream",
        "size_bytes":   len(content),
        "uploaded_at":  time.strftime("%Y-%m-%dT%H:%M:%S"),
        "uploaded_by":  uploaded_by,
        "storage_path": str(dest),
        "status":       "pending",
    }
    t.setdefault("documents", []).append(doc_entry)
    t = _add_message(t, "system", f"Document ajouté : {safe_fn}", visible_to_client=False)
    _save(t)

    if uploaded_by == "client":
        session_id = t.get("client", {}).get("session_id", "")
        if session_id:
            save_message(
                session_id=session_id,
                role="user",
                content=f"📎 Document envoyé : {safe_fn}",
                meta={
                    "doc_id": doc_id, "filename": safe_fn,
                    "mime_type": file.content_type or "application/octet-stream",
                    "ticket_id": ticket_id, "isFile": True, "size_bytes": len(content),
                },
            )

    return {"status": "ok", "doc_id": doc_id, "filename": safe_fn}


@app.get("/tickets/{ticket_id}/documents")
def list_documents(ticket_id: str):
    try:
        t = load_ticket(ticket_id)
        return t.get("documents", [])
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")


@app.get("/tickets/{ticket_id}/documents/{doc_id}")
def download_document(ticket_id: str, doc_id: str):
    try:
        t = load_ticket(ticket_id)
    except FileNotFoundError:
        raise HTTPException(404, "Ticket introuvable")

    docs = t.get("documents", [])
    doc  = next((d for d in docs if d["doc_id"] == doc_id), None)
    if not doc:
        raise HTTPException(404, "Document introuvable")

    path = Path(doc["storage_path"])
    if not path.exists():
        raise HTTPException(404, "Fichier introuvable")

    return FileResponse(
        path=str(path),
        filename=doc["filename"],
        media_type=doc.get("mime_type", "application/octet-stream"),
        headers={"Content-Disposition": f'inline; filename="{doc["filename"]}"'},
    )


@app.get("/health")
def health():
    return {"status": "ok", "service": "document-service"}
