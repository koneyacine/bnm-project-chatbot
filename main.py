"""
BNM RAG Service — port 8020
Service RAG isolé et indépendant.

Démarrage :
  python main.py
  uvicorn main:app --port 8020 --reload
"""
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import router
# Ingestion initiale des documents dans pgvector au démarrage du service

app = FastAPI(
    title="BNM RAG Service",
    description="Pipeline RAG isolé — BNM Chatbot",
    version="1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root():
    return {
        "service": "BNM RAG Service",
        "version": "1.0",
        "endpoints": [
            "POST /rag/ask      — pipeline RAG complet",
            "GET  /rag/health   — santé du service",
            "GET  /rag/patterns — patterns conversationnels",
            "GET  /docs         — documentation Swagger",
        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8021)
