# app/models.py
from pydantic import BaseModel
from typing import Optional

# Hiérarchie de classification — ordre important
CLASSIFICATION_LEVELS = ["public", "restricted", "confidential", "secret"]


class User(BaseModel):
    name: str
    email: str
    department: str          # "RH", "Finance", "Engineering"...
    max_classification: str  # "public" | "restricted" | "confidential" | "secret"


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class CVResult(BaseModel):
    filename: str
    filepath: str
    text: str
    score: float
    classification: str
    modified_by: str


class SearchResponse(BaseModel):
    query: str
    results: list[CVResult]
    applied_classification: str   # classification effectivement appliquée


class ChatRequest(BaseModel):
    query: str
    top_k: int = 5


class ChatResponse(BaseModel):
    query: str
    answer: str
    sources: list[CVResult]
    applied_classification: str


def get_effective_classification(user: User, requested: Optional[str] = None) -> str:
    """
    Retourne la classification effective à appliquer.
    Le max_classification de l'user plafonne toujours.
    Si requested est None ou dépasse le max, on retourne le max de l'user.
    """
    user_level = CLASSIFICATION_LEVELS.index(user.max_classification)

    if requested is None:
        return user.max_classification

    if requested not in CLASSIFICATION_LEVELS:
        return user.max_classification

    requested_level = CLASSIFICATION_LEVELS.index(requested)

    # On prend le plus restrictif des deux
    effective_index = min(user_level, requested_level)
    return CLASSIFICATION_LEVELS[effective_index]
