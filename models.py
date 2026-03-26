from pydantic import BaseModel
from typing import Optional, List


class RAGRequest(BaseModel):
    question:   str
    session_id: Optional[str] = None
    phone:      Optional[str] = None


class RAGResponse(BaseModel):
    question:   str
    answer:     str
    intent:     str
    confidence: str
    sources:    List[str]
    pipeline:   List[str]
    session_id: str


class ClassifyRequest(BaseModel):
    message: str


class ClassifyResponse(BaseModel):
    intent: str


class ContextMessage(BaseModel):
    role:    str
    # Valeurs : "client" ou "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    context: List[ContextMessage] = []


class ChatResponse(BaseModel):
    answer:            str
    open_conversation: bool
    intent:            str
    # VALIDATION | RECLAMATION | INFORMATION
