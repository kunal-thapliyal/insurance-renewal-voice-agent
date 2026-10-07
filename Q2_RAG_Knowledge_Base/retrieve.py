import os
import json
from pathlib import Path

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

COLLECTION_NAME = "insurance_renewal_kb"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

TOP_K = 5


# ============================================================
# LOAD .ENV
# ============================================================

def load_env_file(path):
    if not path.exists():
        raise FileNotFoundError(
            f".env file not found: {path}"
        )

    values = {}

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)

            key = key.strip()
            value = value.strip().strip('"').strip("'")

            values[key] = value

    return values


env = load_env_file(ENV_FILE)

QDRANT_URL = env.get("QDRANT_URL")
QDRANT_API_KEY = env.get("QDRANT_API_KEY")

if not QDRANT_URL:
    raise ValueError("QDRANT_URL missing from .env")

if not QDRANT_API_KEY:
    raise ValueError("QDRANT_API_KEY missing from .env")


# ============================================================
# CONNECT TO QDRANT
# ============================================================

print("=" * 70)
print("INSURANCE RENEWAL RAG RETRIEVAL TEST")
print("=" * 70)

print("\nConnecting to Qdrant Cloud...")

client = QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
    timeout=60
)

print("Connected.")


# ============================================================
# LOAD EMBEDDING MODEL
# ============================================================

print(
    f"\nLoading embedding model: {MODEL_NAME}"
)

model = SentenceTransformer(MODEL_NAME)

print("Embedding model loaded.")


# ============================================================
# RETRIEVAL FUNCTION
# ============================================================

def retrieve(question, top_k=TOP_K):

    query_vector = model.encode(
        question,
        normalize_embeddings=True
    ).tolist()

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
        with_payload=True
    ).points

    return results


# ============================================================
# DISPLAY RESULTS
# ============================================================

def display_results(question, results):

    print("\n")
    print("=" * 70)
    print("QUESTION")
    print("=" * 70)
    print(question)

    print("\n")
    print("=" * 70)
    print(f"TOP {len(results)} RETRIEVED RESULTS")
    print("=" * 70)

    if not results:
        print("No results found.")
        return

    for rank, result in enumerate(results, start=1):

        payload = result.payload or {}

        print("\n" + "-" * 70)

        print(f"RANK:       {rank}")
        print(f"SCORE:      {result.score:.4f}")

        print(
            f"SOURCE ID:  {payload.get('source_id')}"
        )

        print(
            f"PAGE:       {payload.get('page_number')}"
        )

        print(
            f"CITATION:   {payload.get('citation')}"
        )

        print(
            f"TITLE:      {payload.get('title')}"
        )

        print(
            f"AUTHORITY:  {payload.get('authority')}"
        )

        print(
            f"DOC TYPE:   {payload.get('document_type')}"
        )

        print(
            f"PRODUCT:    {payload.get('product')}"
        )

        print(
            f"SECTION:    {payload.get('section')}"
        )

        print(
            f"CONTENT:    {payload.get('content_type')}"
        )

        print("\nTEXT:")
        print(payload.get("text", ""))


# ============================================================
# MAIN
# ============================================================

def main():

    question = input(
        "\nEnter your insurance question: "
    ).strip()

    if not question:
        print("No question entered.")
        return

    results = retrieve(question)

    display_results(
        question,
        results
    )


if __name__ == "__main__":
    main()