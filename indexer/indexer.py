# indexer/indexer.py
import os
import json
import hashlib
import logging
import pdfplumber
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

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

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "cvs")
CVS_DIR = os.getenv("CVS_DIR", "/data/cvs")
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
VECTOR_SIZE = 384
METADATA_FILE = os.path.join(CVS_DIR, "metadata.json")


def load_metadata() -> dict:
    if not os.path.exists(METADATA_FILE):
        logger.warning(
            "Pas de metadata.json trouvé, métadonnées par défaut appliquées.")
        return {}
    with open(METADATA_FILE, "r") as f:
        return json.load(f)


def make_point_id(filename: str, chunk_index: int) -> str:
    """ID déterministe : même fichier + même chunk = même ID → pas de doublon."""
    key = f"{filename}_{chunk_index}"
    return hashlib.md5(key.encode()).hexdigest()


def extract_text_from_pdf(pdf_path: str) -> str:
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text


def get_pdf_files(directory: str) -> list[str]:
    pdf_files = []
    for root, _, files in os.walk(directory):
        for f in files:
            if f.endswith(".pdf"):
                pdf_files.append(os.path.join(root, f))
    return pdf_files


def ensure_collection(client: QdrantClient):
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        logger.info(f"Collection '{COLLECTION_NAME}' créée.")
    else:
        logger.info(f"Collection '{COLLECTION_NAME}' déjà existante.")


def get_indexed_filenames(client: QdrantClient) -> set[str]:
    """Retourne les filenames actuellement indexés dans Qdrant."""
    indexed = set()
    next_offset = None

    while True:
        results, next_offset = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=None,
            limit=100,
            offset=next_offset,
            with_payload=["filename"],
            with_vectors=False,
        )
        for point in results:
            if point.payload and "filename" in point.payload:
                indexed.add(point.payload["filename"])
        if next_offset is None:
            break

    return indexed


def delete_file_from_index(client: QdrantClient, filename: str):
    """Supprime tous les chunks d'un fichier de Qdrant."""
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[FieldCondition(
                key="filename", match=MatchValue(value=filename))]
        ),
    )
    logger.info(f"'{filename}' supprimé de l'index.")


def index_cvs():
    logger.info("Chargement du modèle d'embedding...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    logger.info(f"Connexion à Qdrant sur {QDRANT_HOST}:{QDRANT_PORT}...")
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    ensure_collection(client)

    metadata_map = load_metadata()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
    )

    # --- DELTA : calcul des fichiers à ajouter / supprimer ---
    pdf_files = get_pdf_files(CVS_DIR)
    current_filenames = {os.path.basename(p) for p in pdf_files}
    indexed_filenames = get_indexed_filenames(client)

    to_add = current_filenames - indexed_filenames
    to_remove = indexed_filenames - current_filenames
    already_indexed = current_filenames & indexed_filenames

    logger.info(
        f"Delta — à indexer: {len(to_add)}, à supprimer: {len(to_remove)}, déjà indexés: {len(already_indexed)}")

    # Suppressions
    for filename in to_remove:
        delete_file_from_index(client, filename)

    # Ajouts
    for pdf_path in pdf_files:
        filename = os.path.basename(pdf_path)
        if filename not in to_add:
            continue

        logger.info(f"Indexation de '{filename}'...")

        file_meta = metadata_map.get(filename, {})
        classification = file_meta.get("classification", "restricted")
        modified_by = file_meta.get("modified_by", "unknown")

        text = extract_text_from_pdf(pdf_path)
        if not text.strip():
            logger.warning(f"Aucun texte extrait de '{filename}', ignoré.")
            continue

        chunks = splitter.split_text(text)
        logger.info(f"'{filename}' — {len(chunks)} chunks générés.")

        embeddings = model.encode(chunks, show_progress_bar=False)

        points = [
            PointStruct(
                id=make_point_id(filename, i),
                vector=embeddings[i].tolist(),
                payload={
                    "filename": filename,
                    "filepath": pdf_path,
                    "chunk_index": i,
                    "text": chunks[i],
                    "classification": classification,
                    "modified_by": modified_by,
                },
            )
            for i in range(len(chunks))
        ]

        client.upsert(collection_name=COLLECTION_NAME, points=points)
        logger.info(
            f"'{filename}' indexé — {len(points)} vecteurs, classification: {classification}, modifié par: {modified_by}")

    logger.info("Indexation terminée.")


if __name__ == "__main__":
    index_cvs()
