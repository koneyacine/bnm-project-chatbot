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


class IntentRequest(BaseModel):
    question: str


class IntentResponse(BaseModel):
    intent: str


class ContextMessage(BaseModel):
    role:    str
    # Valeurs : "client" ou "assistant"
    content: str


class AnswerRequest(BaseModel):
    question: str
    context: List[ContextMessage] = []


class AnswerResponse(BaseModel):
    answer:            str
    intent:            str
    open_conversation: bool
