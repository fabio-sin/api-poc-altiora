# app/main.py
import os
import json
import logging
import hashlib
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from redis.asyncio import Redis
from app.session import get_history, append_to_history, clear_history
from prometheus_fastapi_instrumentator import Instrumentator
from fastapi.middleware.cors import CORSMiddleware

from app.models import (
    User,
    SearchRequest, SearchResponse,
    ChatRequest, ChatResponse,
    get_effective_classification,
)
from app.search import search_cvs
from app.router import call_litellm

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CACHE_TTL = int(os.getenv("CACHE_TTL", 3600))  # 1h par défaut

app = FastAPI(title="Altiora AI Orchestrator", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
Instrumentator().instrument(app).expose(app)
redis: Redis = None


@app.on_event("startup")
async def startup():
    global redis
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    logger.info("Connexion Redis établie.")


@app.on_event("shutdown")
async def shutdown():
    await redis.aclose()
    logger.info("Connexion Redis fermée.")


def parse_user_headers(
    x_user_name: str = Header(...),
    x_user_email: str = Header(...),
    x_user_department: str = Header(...),
    x_user_max_classification: str = Header(...),
) -> User:
    return User(
        name=x_user_name,
        email=x_user_email,
        department=x_user_department,
        max_classification=x_user_max_classification,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/search", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    x_user_name: str = Header(...),
    x_user_email: str = Header(...),
    x_user_department: str = Header(...),
    x_user_max_classification: str = Header(...),
):
    user = parse_user_headers(
        x_user_name, x_user_email, x_user_department, x_user_max_classification)
    effective_classification = get_effective_classification(user)

    logger.info(
        f"/search — user: {user.email}, query: '{request.query}', classification: {effective_classification}")

    results = search_cvs(
        query=request.query,
        top_k=request.top_k,
        classification_filter=effective_classification,
    )

    return SearchResponse(
        query=request.query,
        results=results,
        applied_classification=effective_classification,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    x_user_name: str = Header(...),
    x_user_email: str = Header(...),
    x_user_department: str = Header(...),
    x_user_max_classification: str = Header(...),
):
    user = parse_user_headers(
        x_user_name, x_user_email, x_user_department, x_user_max_classification)
    effective_classification = get_effective_classification(user)

    logger.info(
        f"/chat — user: {user.email}, query: '{request.query}', classification: {effective_classification}")

    results = search_cvs(
        query=request.query,
        top_k=request.top_k,
        classification_filter=effective_classification,
    )

    if not results:
        raise HTTPException(
            status_code=404, detail="Aucun document pertinent trouvé.")

    # Récupère l'historique de session
    history = await get_history(redis, user.email)

    answer = await call_litellm(
        query=request.query,
        results=results,
        user=user,
        history=history,
    )

    # Met à jour l'historique
    await append_to_history(redis, user.email, request.query, answer)

    return ChatResponse(
        query=request.query,
        answer=answer,
        sources=results,
        applied_classification=effective_classification,
    )


@app.delete("/session")
async def delete_session(
    x_user_email: str = Header(...),
):
    await clear_history(redis, x_user_email)
    return {"status": "session effacée", "email": x_user_email}


@app.get("/session")
async def get_session(
    x_user_email: str = Header(...),
):
    history = await get_history(redis, x_user_email)
    return {
        "email": x_user_email,
        "exchanges": len(history) // 2,
        "history": history,
    }
