import json
import os
import sys
from pathlib import Path

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient


# ============================================================
# PROJECT PATHS
# ============================================================

# test_retrieval.py is inside:
# RAG_Knowledge_Base/test/
#
# Therefore parent.parent = RAG_Knowledge_Base/

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
OUTPUT_DIR = BASE_DIR / "Data" / "processed" / "retrieval_tests"

OUTPUT_JSON = OUTPUT_DIR / "retrieval_results.json"


# ============================================================
# SETTINGS
# ============================================================

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

COLLECTION = "insurance_renewal_kb"

TOP_K = 5


# ============================================================
# TEST QUESTIONS
# ============================================================

TEST_QUERIES = [
    {
        "test_id": "Q1",
        "category": "Payment",
        "question": "What payment channels are available for paying an LIC policy premium?"
    },
    {
        "test_id": "Q2",
        "category": "Grace Period",
        "question": "What is the grace period for paying an LIC life insurance premium?"
    },
    {
        "test_id": "Q3",
        "category": "Lapsed Policy / Revival",
        "question": "What options are available if an LIC policy has lapsed?"
    },
    {
        "test_id": "Q4",
        "category": "Grievance",
        "question": "How can an LIC policyholder register a grievance?"
    },
    {
        "test_id": "Q5",
        "category": "Product / Qualification",
        "question": "What are the eligibility and premium payment conditions for New Tech-Term?"
    }
]


# ============================================================
# LOAD .ENV
# ============================================================

def load_env_file(path):
    """
    Simple .env loader.
    Environment variables already set take priority.
    """

    if not path.exists():
        return

    for line in path.read_text(
        encoding="utf-8-sig"
    ).splitlines():

        line = line.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        key, _, value = line.partition("=")

        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key:
            os.environ.setdefault(
                key,
                value
            )


# ============================================================
# QDRANT CONNECTION
# ============================================================

def get_qdrant_client():

    load_env_file(ENV_PATH)

    url = os.environ.get(
        "QDRANT_URL",
        ""
    ).strip().rstrip("/")

    api_key = os.environ.get(
        "QDRANT_API_KEY",
        ""
    ).strip()

    if not url:
        raise RuntimeError(
            "QDRANT_URL is missing from .env"
        )

    if not api_key:
        raise RuntimeError(
            "QDRANT_API_KEY is missing from .env"
        )

    return QdrantClient(
        url=url,
        api_key=api_key,
        timeout=60
    )


# ============================================================
# RETRIEVAL
# ============================================================

def retrieve(
    client,
    model,
    question
):

    query_vector = model.encode(
        question,
        normalize_embeddings=True
    ).tolist()

    results = client.query_points(
        collection_name=COLLECTION,
        query=query_vector,
        limit=TOP_K,
        with_payload=True,
        with_vectors=False
    ).points

    return results


# ============================================================
# MAIN
# ============================================================

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print("=" * 75)
    print("Q2 RETRIEVAL EVALUATION")
    print("=" * 75)

    print()
    print(f"Collection: {COLLECTION}")
    print(f"Model:      {MODEL_NAME}")
    print(f"Top K:      {TOP_K}")
    print(f"Tests:      {len(TEST_QUERIES)}")

    print()
    print("Loading embedding model...")

    model = SentenceTransformer(
        MODEL_NAME
    )

    print("Connecting to Qdrant...")

    client = get_qdrant_client()

    all_results = []

    try:

        for test in TEST_QUERIES:

            test_id = test["test_id"]
            category = test["category"]
            question = test["question"]

            print()
            print("=" * 75)
            print(f"{test_id} — {category}")
            print("=" * 75)

            print()
            print("QUESTION:")
            print(question)

            results = retrieve(
                client,
                model,
                question
            )

            test_results = []

            print()
            print("TOP RESULTS:")
            print("-" * 75)

            for rank, result in enumerate(
                results,
                start=1
            ):

                payload = result.payload or {}

                item = {
                    "rank": rank,
                    "score": float(result.score),
                    "chunk_id": payload.get(
                        "chunk_id"
                    ),
                    "source_id": payload.get(
                        "source_id"
                    ),
                    "citation": payload.get(
                        "citation"
                    ),
                    "title": payload.get(
                        "title"
                    ),
                    "authority": payload.get(
                        "authority"
                    ),
                    "document_type": payload.get(
                        "document_type"
                    ),
                    "product": payload.get(
                        "product"
                    ),
                    "section": payload.get(
                        "section"
                    ),
                    "content_type": payload.get(
                        "content_type"
                    ),
                    "source_type": payload.get(
                        "source_type"
                    ),
                    "url": payload.get(
                        "url"
                    ),
                    "text": payload.get(
                        "text"
                    )
                }

                test_results.append(
                    item
                )

                print()
                print(
                    f"Rank:       {rank}"
                )

                print(
                    f"Score:      {result.score:.4f}"
                )

                print(
                    f"Source ID:  {item['source_id']}"
                )

                print(
                    f"Chunk ID:   {item['chunk_id']}"
                )

                print(
                    f"Citation:   {item['citation']}"
                )

                print(
                    f"Title:      {item['title']}"
                )

                print(
                    f"Source:     {item['source_type']}"
                )

                if item["url"]:
                    print(
                        f"URL:        {item['url']}"
                    )

                print()
                print("TEXT:")
                print(
                    item["text"]
                )

            all_results.append(
                {
                    "test_id": test_id,
                    "category": category,
                    "question": question,
                    "results": test_results
                }
            )

    finally:

        client.close()

    # ========================================================
    # SAVE RESULTS
    # ========================================================

    output = {
        "collection": COLLECTION,
        "embedding_model": MODEL_NAME,
        "top_k": TOP_K,
        "tests": all_results
    }

    with OUTPUT_JSON.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False
        )

    print()
    print("=" * 75)
    print("RETRIEVAL TESTING COMPLETE")
    print("=" * 75)

    print()
    print(
        f"Tests completed: {len(all_results)}"
    )

    print(
        f"Results saved to:"
    )

    print(
        OUTPUT_JSON
    )

    print()
    print(
        "No Qdrant data was modified."
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print()
        print("=" * 75)
        print("ERROR")
        print("=" * 75)

        print(error)

        sys.exit(1)