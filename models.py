from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
 
 
# ── Message de contexte ──────────────────────────────────────────────
class ContextMessage(BaseModel):
    role: str       # "client" | "conseiller"
    content: str
 
 
# ── Ticket existant (réclamation ou validation) ──────────────────────
class TicketItem(BaseModel):
    id: Optional[str]             = None
    titre: Optional[str]          = None   # ou "title" / "subject"
    title: Optional[str]          = None
    subject: Optional[str]        = None
    statut: Optional[str]         = None   # ou "status"
    status: Optional[str]         = None
    date: Optional[str]           = None   # ou "created_at"
    created_at: Optional[str]     = None
    # champ spécifique validation : documents déjà fournis
    documents_fournis: Optional[List[str]] = Field(default_factory=list)
    documents: Optional[List[str]]         = Field(default_factory=list)
    # champs libres supplémentaires
    extra: Optional[Dict[str, Any]] = None
 
 
# ── Requête principale ───────────────────────────────────────────────
class AnswerRequest(BaseModel):
    question: str
    context: List[ContextMessage] = Field(default_factory=list)
    intent: Optional[str]         = None
    # ← NOUVEAU : liste des tickets existants du client
    tickets: Optional[List[TicketItem]] = Field(
        default_factory=list,
        description="Liste des tickets existants du client (réclamations ou validations)."
    )
 
 
# ── Autres modèles ───────────────────────────────────────────────────
class IntentRequest(BaseModel):
    question: str
 
 
class IntentResponse(BaseModel):
    intent: str
 
 
class AnswerResponse(BaseModel):
    answer: str
    intent: str
    open_conversation: bool
 