# app/search.py
import os
import logging
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, QueryRequest
from sentence_transformers import SentenceTransformer
from app.models import CVResult

load_dotenv()

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "cvs")
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Chargement unique du modèle au démarrage du service
model = SentenceTransformer(EMBEDDING_MODEL)
client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)


def search_cvs(query: str, top_k: int = 5, classification_filter: str | None = None) -> list[CVResult]:
    logger.info(
        f"Recherche — query: '{query}', top_k: {top_k}, filter: {classification_filter}")

    query_vector = model.encode(query).tolist()

    qdrant_filter = None
    if classification_filter:
        qdrant_filter = Filter(
            must=[FieldCondition(key="classification", match=MatchValue(
                value=classification_filter))]
        )

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=qdrant_filter,
        limit=top_k,
        with_payload=True,
    ).points

    cv_results = []
    for hit in results:
        p = hit.payload
        cv_results.append(CVResult(
            filename=p.get("filename", ""),
            filepath=p.get("filepath", ""),
            text=p.get("text", ""),
            score=hit.score,
            classification=p.get("classification", ""),
            modified_by=p.get("modified_by", ""),
        ))
        logger.info(
            f"  → {p.get('filename')} (score: {hit.score:.3f}, classification: {p.get('classification')})")

    return cv_results
