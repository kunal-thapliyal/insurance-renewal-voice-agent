import json
import re
import hashlib
from pathlib import Path

from sentence_transformers import SentenceTransformer


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

PDF_INPUT_JSONL = (
    BASE_DIR
    / "Data"
    / "processed"
    / "structured"
    / "page_records.jsonl"
)

WEB_INPUT_JSONL = (
    BASE_DIR
    / "Data"
    / "processed"
    / "structured"
    / "web"
    / "web_page_records.jsonl"
)

OUTPUT_DIR = (
    BASE_DIR
    / "Data"
    / "processed"
    / "chunks"
)

OUTPUT_JSONL = OUTPUT_DIR / "chunk_records.jsonl"


# ============================================================
# CHUNK SETTINGS
# ============================================================

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

TARGET_TOKENS = 200
OVERLAP_TOKENS = 50
MAX_TOKENS = 220

MIN_TOKENS = 20


# ============================================================
# TOKENIZER
# ============================================================

print("Loading tokenizer...")

model = SentenceTransformer(MODEL_NAME)
tokenizer = model.tokenizer

print(f"Embedding tokenizer: {MODEL_NAME}")
print(f"Target tokens:       {TARGET_TOKENS}")
print(f"Overlap tokens:      {OVERLAP_TOKENS}")
print(f"Maximum tokens:      {MAX_TOKENS}")


# ============================================================
# TOKEN HELPERS
# ============================================================

def token_count(text):
    """
    Count tokens using the exact tokenizer associated
    with all-MiniLM-L6-v2.
    """

    if not text:
        return 0

    token_ids = tokenizer.encode(
        text,
        add_special_tokens=True,
        truncation=False
    )

    return len(token_ids)


def encode_text(text):
    """
    Encode text without truncation.
    """

    return tokenizer.encode(
        text,
        add_special_tokens=False,
        truncation=False
    )


def decode_tokens(token_ids):
    """
    Convert tokenizer IDs back into text.
    """

    if not token_ids:
        return ""

    return tokenizer.decode(
        token_ids,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=True
    ).strip()


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_whitespace(text):
    """
    Normalize whitespace for chunking only.

    Original source text is not modified.
    """

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    text = re.sub(r"[ \t]+", " ", text)

    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def split_into_units(text):
    """
    Split text into semantic units.

    Priority:

        paragraphs
        -> lines
        -> sentences

    Content is not summarized or rewritten.
    """

    paragraphs = re.split(r"\n\s*\n", text)

    units = []

    for paragraph in paragraphs:

        paragraph = paragraph.strip()

        if not paragraph:
            continue

        paragraph_tokens = token_count(paragraph)

        if paragraph_tokens <= TARGET_TOKENS:
            units.append(paragraph)
            continue

        lines = [
            line.strip()
            for line in paragraph.split("\n")
            if line.strip()
        ]

        for line in lines:

            line_tokens = token_count(line)

            if line_tokens <= TARGET_TOKENS:
                units.append(line)
                continue

            sentences = re.split(
                r"(?<=[.!?।])\s+",
                line
            )

            for sentence in sentences:

                sentence = sentence.strip()

                if sentence:
                    units.append(sentence)

    return units


# ============================================================
# LONG UNIT SPLITTING
# ============================================================

def split_long_unit(text):
    """
    Split a semantic unit using token windows.

    Ensures final pieces stay below MAX_TOKENS.
    """

    token_ids = encode_text(text)

    body_limit = MAX_TOKENS - 2

    if len(token_ids) + 2 <= MAX_TOKENS:
        return [text.strip()]

    pieces = []

    start = 0

    while start < len(token_ids):

        end = min(
            start + body_limit,
            len(token_ids)
        )

        piece_ids = token_ids[start:end]

        piece = decode_tokens(piece_ids)

        if piece:
            pieces.append(piece)

        if end >= len(token_ids):
            break

        next_start = end - OVERLAP_TOKENS

        if next_start <= start:
            next_start = end

        start = next_start

    return pieces


# ============================================================
# CHUNK BUILDING
# ============================================================

def build_chunks(text):
    """
    Build token-aware overlapping chunks.

    Rules:

    - Never cross source/page boundaries.
    - Target approximately 200 tokens.
    - Maximum 220 tokens.
    - Approximately 50-token overlap.
    - Preserve semantic units where possible.
    """

    text = normalize_whitespace(text)

    if not text:
        return []

    raw_units = split_into_units(text)

    units = []

    for unit in raw_units:

        if token_count(unit) <= MAX_TOKENS:
            units.append(unit)

        else:
            units.extend(
                split_long_unit(unit)
            )

    chunks = []

    current_units = []
    current_text = ""

    for unit in units:

        if not unit.strip():
            continue

        # ----------------------------------------------------
        # Empty current chunk
        # ----------------------------------------------------

        if not current_units:

            current_units = [unit]
            current_text = unit

            continue

        # ----------------------------------------------------
        # Try adding the next semantic unit
        # ----------------------------------------------------

        candidate = (
            current_text
            + "\n\n"
            + unit
        )

        candidate_tokens = token_count(candidate)

        if candidate_tokens <= TARGET_TOKENS:

            current_units.append(unit)
            current_text = candidate

            continue

        # ----------------------------------------------------
        # Current chunk is complete
        # ----------------------------------------------------

        chunks.append(current_text.strip())

        # ----------------------------------------------------
        # Build semantic overlap
        # ----------------------------------------------------

        overlap_text = ""
        overlap_units = []
        accumulated_tokens = 0

        for previous_unit in reversed(current_units):

            previous_tokens = token_count(
                previous_unit
            )

            if (
                accumulated_tokens
                + previous_tokens
                > OVERLAP_TOKENS
            ):
                break

            overlap_units.insert(
                0,
                previous_unit
            )

            accumulated_tokens += previous_tokens

        if overlap_units:

            overlap_text = "\n\n".join(
                overlap_units
            )

        # ----------------------------------------------------
        # Start next chunk
        # ----------------------------------------------------

        if overlap_text:

            new_text = (
                overlap_text
                + "\n\n"
                + unit
            )

            # If semantic overlap makes the chunk too large,
            # use an exact token-level overlap.

            if token_count(new_text) > TARGET_TOKENS:

                previous_tokens = encode_text(
                    current_text
                )

                overlap_ids = previous_tokens[
                    -OVERLAP_TOKENS:
                ]

                overlap_text = decode_tokens(
                    overlap_ids
                )

                new_text = (
                    overlap_text
                    + "\n\n"
                    + unit
                )

        else:

            new_text = unit

        # ----------------------------------------------------
        # If overlap + unit is still too large,
        # start with unit alone.
        # ----------------------------------------------------

        if token_count(new_text) > TARGET_TOKENS:
            new_text = unit

        # ----------------------------------------------------
        # Absolute safety for oversized units
        # ----------------------------------------------------

        if token_count(new_text) > MAX_TOKENS:

            split_pieces = split_long_unit(
                new_text
            )

            if len(split_pieces) > 1:

                chunks.extend(
                    split_pieces[:-1]
                )

                current_text = split_pieces[-1]

                current_units = [
                    split_pieces[-1]
                ]

            else:

                current_text = split_pieces[0]

                current_units = [
                    split_pieces[0]
                ]

        else:

            current_text = new_text

            current_units = [unit]

    # --------------------------------------------------------
    # Final chunk
    # --------------------------------------------------------

    if current_text.strip():
        chunks.append(
            current_text.strip()
        )

    # --------------------------------------------------------
    # Final safety enforcement
    # --------------------------------------------------------

    final_chunks = []

    for chunk in chunks:

        if not chunk.strip():
            continue

        count = token_count(chunk)

        if count <= MAX_TOKENS:

            final_chunks.append(chunk)

        else:

            final_chunks.extend(
                split_long_unit(chunk)
            )

    return final_chunks


# ============================================================
# DUPLICATE HANDLING
# ============================================================

def text_hash(text):

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


# ============================================================
# RECORD CREATION
# ============================================================

def create_chunk_record(
    source_record,
    chunk_text,
    chunk_index,
    source_type
):
    """
    Create one unified chunk record.

    Handles both PDF page records and web-page records.
    """

    source_id = source_record["source_id"]

    # --------------------------------------------------------
    # PDF
    # --------------------------------------------------------

    if source_type == "pdf":

        page_id = source_record["page_id"]
        page_number = source_record.get(
            "page_number"
        )

        chunk_id = (
            f"{source_id}-p{page_number}-c{chunk_index}"
        )

    # --------------------------------------------------------
    # WEB
    # --------------------------------------------------------

    else:

        page_id = source_record["page_id"]
        page_number = None

        chunk_id = (
            f"{source_id}-web-c{chunk_index}"
        )

    # --------------------------------------------------------
    # Base record
    # --------------------------------------------------------

    record = {

        "chunk_id": chunk_id,

        # Provenance
        "source_id": source_id,
        "page_id": page_id,
        "page_number": page_number,
        "citation": source_record.get(
            "citation"
        ),

        # Source type
        "source_type": source_type,

        # Web provenance
        "url": source_record.get(
            "url"
        ),
        "retrieved_at_utc": source_record.get(
            "retrieved_at_utc"
        ),

        # Document metadata
        "filename": source_record.get(
            "filename"
        ),
        "text_filename": source_record.get(
            "text_filename"
        ),
        "title": source_record.get(
            "title"
        ),
        "authority": source_record.get(
            "authority"
        ),
        "document_type": source_record.get(
            "document_type"
        ),
        "product": source_record.get(
            "product"
        ),
        "plan_number": source_record.get(
            "plan_number"
        ),
        "uin": source_record.get(
            "uin"
        ),
        "version": source_record.get(
            "version"
        ),
        "effective_date": source_record.get(
            "effective_date"
        ),
        "status": source_record.get(
            "status"
        ),

        # Page/chunk metadata
        "language": source_record.get(
            "language"
        ),
        "section": source_record.get(
            "section"
        ),
        "section_confidence": source_record.get(
            "section_confidence"
        ),
        "content_type": source_record.get(
            "content_type"
        ),
        "content_type_confidence": source_record.get(
            "content_type_confidence"
        ),

        # Safety/document structure
        "pii_status": source_record.get(
            "pii_status"
        ),
        "pii_signals": source_record.get(
            "pii_signals"
        ),
        "contains_table": source_record.get(
            "contains_table",
            False
        ),
        "contains_form": source_record.get(
            "contains_form",
            False
        ),
        "review_required": source_record.get(
            "review_required",
            False
        ),

        # Chunk metadata
        "chunk_index": chunk_index,
        "chunk_length": len(chunk_text),
        "chunk_token_count": token_count(
            chunk_text
        ),
        "text_hash": text_hash(
            chunk_text
        ),

        # Searchable content
        "text": chunk_text,
    }

    return record


# ============================================================
# LOAD JSONL
# ============================================================

def load_jsonl(path):

    records = []

    if not path.exists():
        return records

    with path.open(
        "r",
        encoding="utf-8"
    ) as f:

        for line_number, line in enumerate(
            f,
            start=1
        ):

            line = line.strip()

            if not line:
                continue

            try:

                records.append(
                    json.loads(line)
                )

            except json.JSONDecodeError as e:

                raise ValueError(
                    f"Invalid JSON in {path} "
                    f"on line {line_number}: {e}"
                )

    return records


# ============================================================
# PROCESS SOURCE
# ============================================================

def process_source(
    records,
    source_type,
    chunks,
    seen_hashes
):
    """
    Process either PDF or web records.
    """

    skipped_empty = 0
    records_without_chunks = 0
    duplicate_chunks = 0

    for source_record in records:

        text = source_record.get(
            "text",
            ""
        ).strip()

        if not text:

            skipped_empty += 1

            continue

        page_chunks = build_chunks(
            text
        )

        if not page_chunks:

            records_without_chunks += 1

            continue

        page_added = 0

        for index, chunk_text in enumerate(
            page_chunks,
            start=1
        ):

            chunk_hash = text_hash(
                chunk_text
            )

            if chunk_hash in seen_hashes:

                duplicate_chunks += 1

                continue

            seen_hashes.add(
                chunk_hash
            )

            record = create_chunk_record(
                source_record,
                chunk_text,
                index,
                source_type
            )

            chunks.append(
                record
            )

            page_added += 1

    return (
        skipped_empty,
        records_without_chunks,
        duplicate_chunks
    )


# ============================================================
# MAIN
# ============================================================

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print("=" * 70)
    print("TOKEN-AWARE UNIFIED KNOWLEDGE BASE CHUNKING")
    print("=" * 70)

    # --------------------------------------------------------
    # Load PDF records
    # --------------------------------------------------------

    pdf_records = load_jsonl(
        PDF_INPUT_JSONL
    )

    # --------------------------------------------------------
    # Load web records
    # --------------------------------------------------------

    web_records = load_jsonl(
        WEB_INPUT_JSONL
    )

    print()
    print(
        f"PDF page records:  {len(pdf_records)}"
    )

    print(
        f"Web page records:  {len(web_records)}"
    )

    print()

    if not pdf_records:
        raise FileNotFoundError(
            f"No PDF records found:\n{PDF_INPUT_JSONL}"
        )

    if not web_records:
        raise FileNotFoundError(
            f"No web records found:\n{WEB_INPUT_JSONL}"
        )

    # --------------------------------------------------------
    # Build chunks
    # --------------------------------------------------------

    chunks = []

    seen_hashes = set()

    (
        pdf_skipped,
        pdf_without_chunks,
        pdf_duplicates
    ) = process_source(
        pdf_records,
        "pdf",
        chunks,
        seen_hashes
    )

    (
        web_skipped,
        web_without_chunks,
        web_duplicates
    ) = process_source(
        web_records,
        "web",
        chunks,
        seen_hashes
    )

    # --------------------------------------------------------
    # Write JSONL
    # --------------------------------------------------------

    with OUTPUT_JSONL.open(
        "w",
        encoding="utf-8"
    ) as f:

        for record in chunks:

            f.write(
                json.dumps(
                    record,
                    ensure_ascii=False
                )
                + "\n"
            )

    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    token_counts = [
        c["chunk_token_count"]
        for c in chunks
    ]

    if token_counts:

        average_tokens = (
            sum(token_counts)
            / len(token_counts)
        )

        minimum_tokens = min(
            token_counts
        )

        maximum_tokens = max(
            token_counts
        )

        over_220 = sum(
            1
            for n in token_counts
            if n > MAX_TOKENS
        )

        over_256 = sum(
            1
            for n in token_counts
            if n > 256
        )

    else:

        average_tokens = 0
        minimum_tokens = 0
        maximum_tokens = 0
        over_220 = 0
        over_256 = 0

    # --------------------------------------------------------
    # Source/page statistics
    # --------------------------------------------------------

    sources = len(
        set(
            c["source_id"]
            for c in chunks
        )
    )

    pdf_chunks = sum(
        1
        for c in chunks
        if c["source_type"] == "pdf"
    )

    web_chunks = sum(
        1
        for c in chunks
        if c["source_type"] == "web"
    )

    pdf_pages_with_chunks = len(
        set(
            c["page_id"]
            for c in chunks
            if c["source_type"] == "pdf"
        )
    )

    web_pages_with_chunks = len(
        set(
            c["page_id"]
            for c in chunks
            if c["source_type"] == "web"
        )
    )

    # --------------------------------------------------------
    # Results
    # --------------------------------------------------------

    print()
    print("RESULT")
    print("-" * 70)

    print(
        f"PDF records processed:     {len(pdf_records)}"
    )

    print(
        f"Web records processed:     {len(web_records)}"
    )

    print(
        f"PDF pages with chunks:     {pdf_pages_with_chunks}"
    )

    print(
        f"Web pages with chunks:     {web_pages_with_chunks}"
    )

    print(
        f"Sources represented:       {sources}"
    )

    print(
        f"PDF chunks created:        {pdf_chunks}"
    )

    print(
        f"Web chunks created:        {web_chunks}"
    )

    print(
        f"TOTAL chunks created:      {len(chunks)}"
    )

    print(
        f"PDF empty records skipped: {pdf_skipped}"
    )

    print(
        f"Web empty records skipped: {web_skipped}"
    )

    print(
        f"PDF duplicates:            {pdf_duplicates}"
    )

    print(
        f"Web duplicates:            {web_duplicates}"
    )

    print(
        f"Average token count:       {average_tokens:.1f}"
    )

    print(
        f"Minimum token count:       {minimum_tokens}"
    )

    print(
        f"Maximum token count:       {maximum_tokens}"
    )

    print(
        f"Chunks > 220 tokens:       {over_220}"
    )

    print(
        f"Chunks > 256 tokens:       {over_256}"
    )

    # --------------------------------------------------------
    # Validation
    # --------------------------------------------------------

    print()
    print("VALIDATION")
    print("-" * 70)

    if over_220 == 0:

        print(
            "PASS: No chunks exceed 220 tokens."
        )

    else:

        print(
            "FAIL: Some chunks exceed 220 tokens."
        )

    if over_256 == 0:

        print(
            "PASS: No chunks exceed the model's 256-token limit."
        )

    else:

        print(
            "FAIL: Some chunks exceed the model's 256-token limit."
        )

    # --------------------------------------------------------
    # Check both source types exist
    # --------------------------------------------------------

    if pdf_chunks > 0:

        print(
            "PASS: PDF chunks are present."
        )

    else:

        print(
            "FAIL: No PDF chunks found."
        )

    if web_chunks > 0:

        print(
            "PASS: Web chunks are present."
        )

    else:

        print(
            "FAIL: No web chunks found."
        )

    print()
    print("Output:")
    print(OUTPUT_JSONL)

    print()
    print(
        "Original PDF and web source files were NOT modified."
    )

    print("=" * 70)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()