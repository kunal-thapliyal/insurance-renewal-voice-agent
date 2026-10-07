import json
import re
from datetime import datetime, timezone
from pathlib import Path


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

INPUT_DIR = (
    BASE_DIR
    / "Data"
    / "raw"
    / "WEB"
)

OUTPUT_DIR = (
    BASE_DIR
    / "Data"
    / "processed"
    / "structured"
    / "web"
)

OUTPUT_JSONL = OUTPUT_DIR / "web_page_records.jsonl"


# ============================================================
# WEB SOURCE METADATA
# ============================================================

WEB_SOURCES = {
    "LIC-001": {
        "title": "Payment at Cash Counter",
        "url": "https://licindia.in/en/web/guest/payment-at-cash-counter",
        "content_type": "payment",
    },
    "LIC-003": {
        "title": "Payment through alternate channels",
        "url": "https://licindia.in/web/guest/payment-through-alternate-channels#main-title",
        "content_type": "payment",
    },
    "LIC-004": {
        "title": "LIC Portal",
        "url": "https://licindia.in/web/guest/lic-portal",
        "content_type": "portal",
    },
    "LIC-005": {
        "title": "Policy Guidelines & Helpline",
        "url": "https://licindia.in/web/guest/policy-guidelines-helpline",
        "content_type": "policy_guidelines",
    },
    "LIC-006": {
        "title": "Policy Status",
        "url": "https://licindia.in/web/guest/policy-status",
        "content_type": "policy_status",
    },
    "LIC-007": {
        "title": "Customers Corner",
        "url": "https://licindia.in/web/guest/customers-corner",
        "content_type": "customer_service",
    },
    "LIC-008": {
        "title": "Grievance Redressal",
        "url": "https://licindia.in/grievances",
        "content_type": "grievance",
    },
}


# ============================================================
# HELPERS
# ============================================================

def detect_language(text):
    """
    Simple language detection based on Devanagari characters.
    """

    devanagari = len(
        re.findall(r"[\u0900-\u097F]", text)
    )

    latin = len(
        re.findall(r"[A-Za-z]", text)
    )

    if devanagari == 0:
        return "English"

    if latin == 0:
        return "Hindi"

    return "Mixed"


def detect_pii_status(text):
    """
    Conservative classification.

    We do not attempt to identify actual personal information
    in these public webpages. We only flag obvious template
    or personal-data fields if present.
    """

    pii_patterns = [
        r"\bPAN\b",
        r"\bAadhaar\b",
        r"\bKYC\b",
        r"\bdate of birth\b",
        r"\bDOB\b",
        r"\bmobile number\b",
        r"\bphone number\b",
        r"\bemail address\b",
        r"\baccount number\b",
    ]

    signals = []

    for pattern in pii_patterns:

        if re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        ):
            signals.append(pattern)

    if signals:
        return "template_fields", signals

    return "none", []


def detect_section(text):
    """
    Use the first meaningful heading-like line as a section.
    """

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    if not lines:
        return None

    first_line = lines[0]

    if len(first_line) <= 150:
        return first_line

    return None


# ============================================================
# MAIN
# ============================================================

def main():

    if not INPUT_DIR.exists():
        raise FileNotFoundError(
            f"Web input directory not found:\n{INPUT_DIR}"
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    records = []

    print("=" * 70)
    print("STRUCTURING LIC WEBPAGES")
    print("=" * 70)

    for source_id, metadata in WEB_SOURCES.items():

        input_file = (
            INPUT_DIR
            / f"{source_id}.txt"
        )

        print()
        print("-" * 70)
        print(f"{source_id}: {metadata['title']}")

        if not input_file.exists():

            print(
                f"SKIPPED - file not found: {input_file}"
            )

            continue

        text = input_file.read_text(
            encoding="utf-8"
        ).strip()

        if not text:

            print("SKIPPED - empty text")
            continue

        pii_status, pii_signals = (
            detect_pii_status(text)
        )

        record = {
            "page_id": f"{source_id}-web",
            "source_id": source_id,

            # Web provenance
            "citation": (
                f"{source_id}, "
                f"{metadata['title']} "
                f"(web page)"
            ),
            "url": metadata["url"],

            # Source metadata
            "filename": input_file.name,
            "text_filename": input_file.name,
            "title": metadata["title"],
            "authority": "LIC",
            "document_type": "Web Page",
            "product": None,
            "plan_number": None,
            "uin": None,
            "version": None,
            "effective_date": None,
            "status": "active_source",

            # Web-page specific
            "language": detect_language(text),
            "section": detect_section(text),
            "section_confidence": "low",
            "content_type": metadata["content_type"],
            "content_type_confidence": "high",

            # Safety
            "pii_status": pii_status,
            "pii_signals": pii_signals,

            # Structure
            "contains_table": bool(
                re.search(
                    r"\btable\b",
                    text,
                    re.IGNORECASE
                )
            ),
            "contains_form": bool(
                re.search(
                    r"\b(form|application form)\b",
                    text,
                    re.IGNORECASE
                )
            ),
            "review_required": True,

            # Web provenance
            "retrieved_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),

            # Full extracted content
            "text": text,
        }

        records.append(record)

        print(
            f"SUCCESS - {len(text):,} characters"
        )
        print(
            f"Language: {record['language']}"
        )
        print(
            f"PII status: {record['pii_status']}"
        )

    # --------------------------------------------------------
    # Write JSONL
    # --------------------------------------------------------

    with OUTPUT_JSONL.open(
        "w",
        encoding="utf-8"
    ) as f:

        for record in records:

            f.write(
                json.dumps(
                    record,
                    ensure_ascii=False
                )
                + "\n"
            )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("WEBPAGE STRUCTURING COMPLETE")
    print("=" * 70)

    print(
        f"Web sources structured: {len(records)}"
    )

    print()
    print("Output:")
    print(OUTPUT_JSONL)

    print()
    print(
        "Original webpage text files were NOT modified."
    )

    print("=" * 70)


if __name__ == "__main__":
    main()