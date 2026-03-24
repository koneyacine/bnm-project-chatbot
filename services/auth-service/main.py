"""
Auth Service — port 8001
Gestion des comptes utilisateurs et tokens JWT.

Endpoints :
  POST /auth/register
  POST /auth/login
  GET  /auth/me
  POST /auth/logout
"""
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from typing import Optional

from auth import (
    authenticate_user,
    create_access_token,
    create_user,
    get_current_user,
)

load_dotenv()

app = FastAPI(title="BNM Auth Service", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_token_blacklist: set = set()
_auth_bearer = HTTPBearer()


class RegisterRequest(BaseModel):
    username: str
    email:    str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/register", status_code=201)
def auth_register(body: RegisterRequest):
    """Crée un nouveau compte utilisateur."""
    try:
        return create_user(body.username, body.email, body.password)
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail="Nom d'utilisateur ou email déjà utilisé",
        )


@app.post("/auth/login")
def auth_login(body: LoginRequest):
    """Authentifie et retourne un token JWT."""
    user = authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    token = create_access_token(
        user["user_id"], user["username"], user["role"],
        agent_role=user.get("agent_role"),
    )
    return {"access_token": token, "token_type": "bearer", "user": user}


@app.get("/auth/me")
def auth_me(u=Depends(get_current_user)):
    """Retourne les informations de l'utilisateur connecté."""
    return u


@app.post("/auth/logout")
def auth_logout(
    creds: HTTPAuthorizationCredentials = Depends(_auth_bearer),
):
    """Blackliste le token (logout côté serveur)."""
    _token_blacklist.add(creds.credentials)
    return {"message": "Déconnecté"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "auth-service"}
