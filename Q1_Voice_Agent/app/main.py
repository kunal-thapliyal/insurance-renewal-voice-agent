import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer


# Load environment variables
load_dotenv()

QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

COLLECTION_NAME = "insurance_renewal_kb"
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_TOP_K = 5
MAX_TOP_K = 10


# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# Global clients
embedding_model: SentenceTransformer | None = None
qdrant_client: QdrantClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize the embedding model and Qdrant client once
    when the FastAPI application starts.
    """
    global embedding_model, qdrant_client

    if not QDRANT_URL:
        raise RuntimeError("QDRANT_URL is missing from the .env file.")

    if not QDRANT_API_KEY:
        raise RuntimeError("QDRANT_API_KEY is missing from the .env file.")

    logger.info("Loading embedding model...")
    embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    logger.info("Connecting to Qdrant...")
    qdrant_client = QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
    )

    # Verify that the existing collection is accessible.
    try:
        qdrant_client.get_collection(COLLECTION_NAME)
        logger.info(
            "Connected to Qdrant collection: %s",
            COLLECTION_NAME,
        )
    except Exception as exc:
        logger.exception("Could not access Qdrant collection.")
        raise RuntimeError(
            f"Could not access Qdrant collection '{COLLECTION_NAME}'."
        ) from exc

    yield

    logger.info("Shutting down Q1 backend...")


app = FastAPI(
    title="Insurance Renewal Knowledge Base API",
    description="Retrieval API for the insurance renewal voice assistant.",
    version="1.0.0",
    lifespan=lifespan,
)


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(
        default=DEFAULT_TOP_K,
        ge=1,
        le=MAX_TOP_K,
    )


def clean_value(value: Any) -> Any:
    """Convert Qdrant payload values into JSON-friendly values."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, list):
        return [clean_value(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): clean_value(val)
            for key, val in value.items()
        }

    return str(value)


def build_result(payload: dict[str, Any], score: float) -> dict[str, Any]:
    """
    Convert a Qdrant payload into a clean Retell-friendly result.

    Metadata is only returned when it exists in the indexed payload.
    """
    result = {
        "text": payload.get("text", ""),
        "score": round(float(score), 4),
    }

    metadata_fields = [
        "source_id",
        "source",
        "citation",
        "title",
        "url",
        "page",
        "page_number",
        "document_type",
        "authority",
        "product",
        "plan_number",
        "uin",
        "version",
        "effective_date",
        "language",
        "content_type",
    ]

    for field in metadata_fields:
        if field in payload and payload[field] is not None:
            result[field] = clean_value(payload[field])

    return result


@app.get("/health")
def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "insurance-renewal-knowledge-base",
        "collection": COLLECTION_NAME,
    }


@app.post("/search")
def search_knowledge_base(request: SearchRequest):
    """
    Search the existing insurance renewal knowledge base.

    This endpoint performs retrieval only.
    It does not generate an answer and does not modify Qdrant.
    """
    global embedding_model, qdrant_client

    if embedding_model is None or qdrant_client is None:
        raise HTTPException(
            status_code=503,
            detail="Knowledge base service is not ready.",
        )

    query = request.query.strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Query cannot be empty.",
        )

    start_time = time.perf_counter()

    logger.info("Incoming retrieval query: %s", query)

    try:
        # Generate the query embedding using the same model
        # used during Q2 indexing.
        query_vector = embedding_model.encode(
            query,
            normalize_embeddings=True,
        ).tolist()

        # Search the existing Qdrant collection.
        search_result = qdrant_client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=request.top_k,
            with_payload=True,
            with_vectors=False,
        )

        results = []

        for point in search_result.points:
            payload = point.payload or {}

            results.append(
                build_result(
                    payload=payload,
                    score=point.score,
                )
            )

        latency_ms = round(
            (time.perf_counter() - start_time) * 1000,
            2,
        )

        logger.info(
            "Retrieved %d results in %.2f ms",
            len(results),
            latency_ms,
        )

        response = {
            "query": query,
            "results": results,
            "result_count": len(results),
            "latency_ms": latency_ms,
        }

        if not results:
            response["message"] = (
                "No relevant information was found in the knowledge base."
            )

        return response

    except Exception as exc:
        logger.exception("Knowledge base retrieval failed.")

        raise HTTPException(
            status_code=500,
            detail="Knowledge base retrieval failed.",
        ) from exc