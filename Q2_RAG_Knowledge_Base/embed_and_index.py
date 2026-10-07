
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
 
# Quiet two harmless warnings (Windows symlinks, tokenizer threads)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
 
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
 
try:
    import numpy as np
except ImportError:
    print("ERROR: numpy is missing. Run:  pip install sentence-transformers qdrant-client")
    sys.exit(1)
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("ERROR: sentence-transformers is not installed. Run:  pip install sentence-transformers")
    sys.exit(1)
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PayloadSchemaType, PointStruct, VectorParams
except ImportError:
    print("ERROR: qdrant-client is not installed. Run:  pip install qdrant-client")
    sys.exit(1)
 
 
# ---------------------------------------------------------------------------
# 1. Settings
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
CHUNKS_PATH = BASE_DIR / "Data" / "processed" / "chunks" / "chunk_records.jsonl"
ENV_PATH = BASE_DIR / ".env"
 
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EXPECTED_DIM = 384
COLLECTION = "insurance_renewal_kb"
EMBED_BATCH = 64        # chunks embedded per step
UPLOAD_BATCH = 128      # points uploaded per request (smaller = safer over the network)
CLIENT_TIMEOUT = 60     # seconds per Qdrant request
 
# Fields you will filter on during retrieval -> indexed so filtered search stays fast
KEYWORD_FIELDS = ["source_id", "authority", "document_type", "product", "content_type",
                  "language", "status", "pii_status", "section"]
BOOL_FIELDS = ["contains_table", "contains_form", "review_required"]
INTEGER_FIELDS = ["page_number"]
 
 
class PipelineError(Exception):
    """A problem we can explain to the user in plain words."""
 
 
# ---------------------------------------------------------------------------
# 2. Qdrant Cloud credentials (from .env or environment variables)
# ---------------------------------------------------------------------------
def load_env_file(path):
    """Tiny .env reader (no extra package). Real environment variables take priority."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)
 
 
def get_qdrant_settings():
    load_env_file(ENV_PATH)
    url = os.environ.get("QDRANT_URL", "").strip().rstrip("/")
    api_key = os.environ.get("QDRANT_API_KEY", "").strip()
    problems = []
    if not url:
        problems.append("QDRANT_URL is not set")
    elif not url.lower().startswith(("https://", "http://")):
        problems.append("QDRANT_URL must start with https:// "
                        "(example: https://xxxx.region.cloud.qdrant.io:6333)")
    if not api_key:
        problems.append("QDRANT_API_KEY is not set")
    if problems:
        raise PipelineError("Qdrant Cloud settings are missing:\n   " + "\n   ".join(problems) +
                            f"\nCreate a file named .env next to this script ({ENV_PATH.name}) with:\n"
                            "   QDRANT_URL=https://your-cluster-url:6333\n"
                            "   QDRANT_API_KEY=your-api-key\n"
                            "and make sure .env is listed in .gitignore.")
    return url, api_key
 
 
# ---------------------------------------------------------------------------
# 3. Load and validate the chunk file
# ---------------------------------------------------------------------------
def load_chunks(path):
    """Read the JSONL. Anything malformed stops the run (nothing is silently dropped)."""
    if not path.exists():
        raise PipelineError(f"chunk file not found: {path}\nRun the chunking stage first.")
    chunks, problems, first_seen = [], [], {}
    with open(path, "rb") as f:
        for line_no, raw in enumerate(f, start=1):
            if not raw.strip():
                continue                                   # blank lines are harmless
            try:
                record = json.loads(raw.decode("utf-8-sig" if line_no == 1 else "utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                problems.append(f"line {line_no}: invalid JSON ({error})")
                continue
            if not isinstance(record, dict):
                problems.append(f"line {line_no}: not a JSON object")
                continue
            chunk_id, text = record.get("chunk_id"), record.get("text")
            if not isinstance(chunk_id, str) or not chunk_id.strip():
                problems.append(f"line {line_no}: missing chunk_id")
            elif not isinstance(text, str) or not text.strip():
                problems.append(f"line {line_no}: chunk {chunk_id} has empty or missing text")
            elif chunk_id in first_seen:
                problems.append(f"line {line_no}: duplicate chunk_id {chunk_id} "
                                f"(first on line {first_seen[chunk_id]})")
            else:
                first_seen[chunk_id] = line_no
                chunks.append(record)
 
    if problems:
        shown = "\n   ".join(problems[:10])
        more = f"\n   ... and {len(problems) - 10} more" if len(problems) > 10 else ""
        raise PipelineError(f"{len(problems)} problem(s) in {path.name}:\n   {shown}{more}\n"
                            "Fix the chunk file (nothing was indexed).")
    if not chunks:
        raise PipelineError(f"{path.name} is empty - there is nothing to index.")
    return chunks
 
 
# ---------------------------------------------------------------------------
# 4. Embeddings
# ---------------------------------------------------------------------------
def load_model():
    try:
        model = SentenceTransformer(MODEL_NAME)
    except Exception as error:
        raise PipelineError(f"could not load the embedding model '{MODEL_NAME}': {error}\n"
                            "On the first run this needs internet access to download the model.")
    dim = model.get_sentence_embedding_dimension()
    if dim != EXPECTED_DIM:
        raise PipelineError(f"the model produces {dim}-dimensional vectors, expected {EXPECTED_DIM}")
    return model
 
 
def count_long_chunks(model, texts):
    """Informational only: the model reads at most max_seq_length tokens per chunk."""
    try:
        limit = model.max_seq_length
        lengths = [len(ids) for ids in model.tokenizer(texts, add_special_tokens=True,
                                                       truncation=False)["input_ids"]]
        return sum(1 for n in lengths if n > limit), limit, max(lengths)
    except Exception:
        return None
 
 
def embed_texts(model, texts):
    """Embed in batches. All embedding happens BEFORE the cloud collection is touched."""
    batches = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]
        try:
            vectors = model.encode(batch, batch_size=EMBED_BATCH, normalize_embeddings=True,
                                   show_progress_bar=False, convert_to_numpy=True)
        except Exception as error:
            raise PipelineError(f"embedding failed for chunks {start}-{start + len(batch) - 1}: {error}")
        if vectors.ndim != 2 or vectors.shape[1] != EXPECTED_DIM or len(vectors) != len(batch):
            raise PipelineError(f"unexpected embedding shape {vectors.shape} for chunks starting at {start}")
        batches.append(vectors.astype("float32"))
        done = min(start + EMBED_BATCH, len(texts))
        print(f"   embedded {done}/{len(texts)} chunks", end="\r", flush=True)
    print()
    matrix = np.vstack(batches)
    norms = np.linalg.norm(matrix, axis=1)
    if not np.allclose(norms, 1.0, atol=1e-3):
        raise PipelineError("embeddings are not unit length (normalisation failed)")
    return matrix
 
 
# ---------------------------------------------------------------------------
# 5. Qdrant Cloud: connect, (re)create the collection, upload, index
# ---------------------------------------------------------------------------
def explain_qdrant_error(error):
    """Turn a raw network/API error into a hint a person can act on."""
    text = str(error)
    lowered = text.lower()
    if "401" in text or "403" in text or "forbidden" in lowered or "unauthorized" in lowered:
        hint = "The API key was rejected. Check QDRANT_API_KEY (and that the key belongs to this cluster)."
    elif "timed out" in lowered or "timeout" in lowered:
        hint = "The request timed out. Check your internet connection and that the cluster is running."
    elif "name or service not known" in lowered or "getaddrinfo" in lowered or "connection" in lowered:
        hint = "Could not reach the cluster. Check QDRANT_URL (include https:// and the port, e.g. :6333)."
    else:
        hint = "See the message above."
    return f"{text}\n   Hint: {hint}"
 
 
def connect(url, api_key):
    """Open the cloud client and make one read-only call, so a wrong URL/key fails fast."""
    try:
        client = QdrantClient(url=url, api_key=api_key, timeout=CLIENT_TIMEOUT)
        client.get_collections()
        return client
    except Exception as error:
        raise PipelineError("could not connect to Qdrant Cloud:\n   " + explain_qdrant_error(error))
 
 
def with_retries(action, what, attempts=3):
    """Network calls can fail briefly; retry a few times (upserts are safe to repeat)."""
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except Exception as error:
            if attempt == attempts:
                raise
            wait = 2 * attempt
            print(f"\n   {what} failed ({str(error)[:80]}); retrying in {wait}s ...")
            time.sleep(wait)
 
 
def collection_names(client):
    return {c.name for c in client.get_collections().collections}
 
 
def build_index(client, chunks, matrix):
    """Recreate the collection so every run gives a clean index, then upload in batches."""
    try:
        if COLLECTION in collection_names(client):
            client.delete_collection(COLLECTION)
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=EXPECTED_DIM, distance=Distance.COSINE),
        )
        total = len(chunks)
        for start in range(0, total, UPLOAD_BATCH):
            end = min(start + UPLOAD_BATCH, total)
            points = [
                PointStruct(id=i, vector=matrix[i].tolist(), payload=chunks[i])  # payload = COMPLETE chunk
                for i in range(start, end)
            ]
            with_retries(lambda p=points: client.upsert(collection_name=COLLECTION, points=p, wait=True),
                         f"upload of points {start}-{end - 1}")
            print(f"   uploaded {end}/{total} points", end="\r", flush=True)
        print()
    except Exception as error:
        raise PipelineError("Qdrant Cloud error while indexing:\n   " + explain_qdrant_error(error) +
                            "\n   The collection may be incomplete - fix the problem and run the script again "
                            "(it recreates the collection).")
 
 
def create_indexes(client):
    """Payload indexes make filtered retrieval (by source, product, type ...) fast. Non-fatal."""
    schemas = [(f, PayloadSchemaType.KEYWORD) for f in KEYWORD_FIELDS]
    bool_type = getattr(PayloadSchemaType, "BOOL", None)
    if bool_type is not None:
        schemas += [(f, bool_type) for f in BOOL_FIELDS]
    schemas += [(f, PayloadSchemaType.INTEGER) for f in INTEGER_FIELDS]
    created, failed = [], []
    for field, schema in schemas:
        try:
            client.create_payload_index(collection_name=COLLECTION, field_name=field,
                                        field_schema=schema, wait=True)
            created.append(field)
        except Exception as error:
            failed.append(f"{field} ({str(error)[:60]})")
    return created, failed
 
 
def verify_index(client, chunks):
    """Check the collection exists, the counts and settings are right, and payloads survived."""
    problems = []
    try:
        if COLLECTION not in collection_names(client):
            raise PipelineError(f"collection '{COLLECTION}' does not exist after indexing")
        count = client.count(collection_name=COLLECTION, exact=True).count
        config = client.get_collection(COLLECTION).config.params.vectors
        if isinstance(config, dict):                   # named vectors (not used here)
            config = next(iter(config.values()))
        size = config.size
        distance = str(getattr(config.distance, "name", config.distance)).split(".")[-1].upper()
 
        if count != len(chunks):
            problems.append(f"vector count is {count}, expected {len(chunks)}")
        if size != EXPECTED_DIM:
            problems.append(f"vector dimension is {size}, expected {EXPECTED_DIM}")
        if distance != "COSINE":
            problems.append(f"distance is {distance}, expected COSINE")
 
        # Payload spot-check: first, middle and last point must equal the source record
        ids = sorted({0, len(chunks) // 2, len(chunks) - 1})
        points = client.retrieve(collection_name=COLLECTION, ids=ids,
                                 with_payload=True, with_vectors=False)
        if len(points) != len(ids):
            problems.append("could not read back the sample points")
        for point in points:
            if point.payload != chunks[point.id]:
                problems.append(f"payload of point {point.id} differs from chunk "
                                f"{chunks[point.id]['chunk_id']}")
    except PipelineError:
        raise
    except Exception as error:
        raise PipelineError("Qdrant Cloud error during verification:\n   " + explain_qdrant_error(error))
 
    if problems:
        raise PipelineError("verification failed:\n   " + "\n   ".join(problems))
    return count, size, distance
 
 
# ---------------------------------------------------------------------------
# 6. Main program
# ---------------------------------------------------------------------------
def main():
    started = time.time()
    url, api_key = get_qdrant_settings()
    chunks = load_chunks(CHUNKS_PATH)
    print(f"Loaded {len(chunks)} chunks from {CHUNKS_PATH.relative_to(BASE_DIR).as_posix()}")
 
    # Fail fast on a wrong URL / key, before the slow embedding step (read-only call)
    host = urlparse(url).netloc or url
    print(f"Connecting to Qdrant Cloud ({host}) ...")
    client = connect(url, api_key)
 
    try:
        print(f"Loading embedding model {MODEL_NAME} ...")
        model = load_model()
        texts = [c["text"] for c in chunks]
 
        long_info = count_long_chunks(model, texts)
        if long_info and long_info[0]:
            print(f"NOTE: {long_info[0]} chunk(s) exceed the model's {long_info[1]}-token limit "
                  f"(longest: {long_info[2]} tokens). Only the first {long_info[1]} tokens of those are "
                  "embedded; the full text is still stored in the payload.")
 
        print("Embedding chunks ...")
        matrix = embed_texts(model, texts)
 
        print(f"Indexing into collection '{COLLECTION}' ...")
        build_index(client, chunks, matrix)
        created, failed = create_indexes(client)
        count, size, distance = verify_index(client, chunks)
    finally:
        try:
            client.close()
        except Exception:
            pass
 
    line = "=" * 60
    print(f"\n{line}\nEMBEDDING + QDRANT INDEXING COMPLETE\n{line}")
    print(f"Chunks loaded:       {len(chunks)}")
    print(f"Vectors indexed:     {count}")
    print(f"Embedding model:     {MODEL_NAME}")
    print(f"Vector dimension:    {size}")
    print(f"Distance:            {distance}")
    print(f"Collection:          {COLLECTION}")
    print(f"Qdrant endpoint:     {host} (Qdrant Cloud)")
    print(f"Payload indexes:     {len(created)} created" + (f", {len(failed)} failed" if failed else ""))
    print(f"Payload spot-check:  passed (first, middle, last point match their chunks)")
    print(f"Time taken:          {time.time() - started:.1f} s")
    print(line)
    for item in failed:
        print(f"WARNING: payload index not created for {item} (search still works, filters may be slower)")
 
 
if __name__ == "__main__":
    try:
        main()
    except PipelineError as error:
        print(f"\nERROR: {error}")
        sys.exit(1)