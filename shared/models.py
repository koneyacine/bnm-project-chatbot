"""
shared/models.py — Modèles Pydantic communs entre services.
"""
from typing import Optional
from pydantic import BaseModel


class QuestionRequest(BaseModel):
    question:   str
    session_id: Optional[str] = None
    user_id:    Optional[str] = None
    phone:      Optional[str] = None


class ClientSessionRequest(BaseModel):
    phone: str


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


class RegisterRequest(BaseModel):
    username: str
    email:    str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LinkSessionBody(BaseModel):
    user_id: str
