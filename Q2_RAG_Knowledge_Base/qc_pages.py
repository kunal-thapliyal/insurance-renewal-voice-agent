import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


# ============================================================================
# 1. PATHS AND SETTINGS
# ============================================================================

BASE_DIR = Path(__file__).resolve().parent

RECORDS_PATH = (
    BASE_DIR
    / "Data"
    / "processed"
    / "structured"
    / "page_records.jsonl"
)

META_PATH = (
    BASE_DIR
    / "Data"
    / "processed"
    / "metadata"
    / "document_metadata.csv"
)

REPORT_PATH = (
    BASE_DIR
    / "Data"
    / "processed"
    / "structured"
    / "qc_report.json"
)

SCHEMA_VERSION = "1.1"

PREVIEW_CHARS = 300

# Number of representative examples for large categories.
MAX_EXAMPLES = 10

# Maximum unknown-language pages listed in the report.
MAX_UNKNOWN_LANGUAGE = 60

# Maximum malformed JSONL records explicitly listed.
MAX_MALFORMED_LISTED = 50

# Pages below this number of non-whitespace characters are considered
# near-empty.
NEAR_EMPTY_CHARS = 20

# Used only to distinguish substantial unknown-language pages.
SUBSTANTIVE_CHARS = 300


# ============================================================================
# 2. METADATA FIELDS
# ============================================================================

CORE_FIELDS = (
    "title",
    "authority",
    "document_type",
)

DOC_FIELDS = (
    "title",
    "authority",
    "document_type",
    "product",
    "plan_number",
    "uin",
    "version",
    "effective_date",
    "status",
)

# These fields are more important when there is a genuine disagreement.
HIGH_FIELDS = {
    "plan_number",
    "uin",
}


# ============================================================================
# 3. PRIORITY RULES
# ============================================================================

PRIORITY_RANK = {
    "HIGH": 0,
    "MEDIUM": 1,
    "LOW": 2,
}


REASON_LEVELS = {
    # High
    "extraction_anomaly": "HIGH",
    "ocr_derived_verify_numbers": "HIGH",
    "possible_pii": "HIGH",
    "empty_page": "HIGH",
    "near_empty_page": "HIGH",
    "duplicate_page_number": "HIGH",

    # Medium
    "possible_table": "MEDIUM",
    "possible_form": "MEDIUM",
    "unknown_language": "MEDIUM",
    "mixed_content_types": "MEDIUM",
    "low_confidence_content_type": "MEDIUM",

    # Low
    "unknown_section": "LOW",
    "unknown_content_type": "LOW",
    "no_section_and_no_content_type": "LOW",
}


# ============================================================================
# 4. REGEX PATTERNS
# ============================================================================

PLAN_RE = re.compile(
    r"\bPlan\s*(?:No\.?|Number)\s*[:.\-]?\s*(\d{3})\b",
    re.IGNORECASE,
)

UIN_RE = re.compile(
    r"\b\d{3}[A-Z]\d{3}V\d{2}\b"
)

PRIVATE_USE_RE = re.compile(
    r"[\ue000-\uf8ff]"
)

CID_RE = re.compile(
    r"\(cid:\d+\)"
)


# ============================================================================
# 5. PII REDACTION
# ============================================================================

# These are ONLY used to redact report previews.
# They do not modify the source page records.

REDACTIONS = [

    # DOB
    (
        re.compile(
            r"((?:date\s+of\s+birth|d\.?o\.?b\.?)\s*[:\-]?\s*)"
            r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}",
            re.IGNORECASE,
        ),
        r"\1[REDACTED_DOB]",
    ),

    # Account number
    (
        re.compile(
            r"(account\s*(?:no\.?|number)\s*[:\-]?\s*)\d{6,18}",
            re.IGNORECASE,
        ),
        r"\1[REDACTED_ACCOUNT_NUMBER]",
    ),

    # Policy number
    (
        re.compile(
            r"(policy\s*(?:no\.?|number)\s*[:\-]?\s*)"
            r"\d[\d/-]{5,}",
            re.IGNORECASE,
        ),
        r"\1[REDACTED_POLICY_NUMBER]",
    ),

    # Aadhaar
    (
        re.compile(
            r"(?<!\d)\d{4}[\s-]\d{4}[\s-]\d{4}(?!\d)"
            r"|(?<!\d)\d{12}(?!\d)"
        ),
        "[REDACTED_AADHAAR]",
    ),

    # PAN
    (
        re.compile(
            r"\b[A-Z]{5}\d{4}[A-Z]\b"
        ),
        "[REDACTED_PAN]",
    ),

    # IFSC
    (
        re.compile(
            r"\b[A-Z]{4}0[A-Z0-9]{6}\b"
        ),
        "[REDACTED_IFSC]",
    ),

    # Email
    (
        re.compile(
            r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
        ),
        "[REDACTED_EMAIL]",
    ),

    # Toll-free phone
    (
        re.compile(
            r"(?<!\d)1800[\s-]?\d{3}[\s-]?\d{3,4}(?!\d)"
        ),
        "[REDACTED_PHONE]",
    ),

    # Indian mobile
    (
        re.compile(
            r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)"
        ),
        "[REDACTED_PHONE]",
    ),

    # Landline
    (
        re.compile(
            r"(?<!\d)"
            r"0\d{2,4}[\s-]?\d{6,8}"
            r"(?!\d)"
            r"|"
            r"(?<!\d)"
            r"0\d{2,4}[\s-]\d{3,4}[\s-]\d{3,4}"
            r"(?!\d)"
        ),
        "[REDACTED_PHONE]",
    ),

    # Long numeric values
    (
        re.compile(
            r"(?<!\d)\d{10,}(?!\d)"
        ),
        "[REDACTED_NUMBER]",
    ),
]


def redact(text):
    """
    Redact sensitive-looking values for QC report previews only.
    """
    text = text or ""

    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)

    return text


def preview(text):
    """
    Redact first, then normalize whitespace and truncate.
    This prevents accidentally exposing partial PII.
    """
    flat = " ".join(redact(text).split())

    if len(flat) <= PREVIEW_CHARS:
        return flat

    return flat[:PREVIEW_CHARS].rstrip() + "..."


# ============================================================================
# 6. GENERAL HELPERS
# ============================================================================

def nonspace_len(text):
    return len("".join((text or "").split()))


def sha256_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path):
    return path.relative_to(BASE_DIR).as_posix()


def as_list(value):
    return value if isinstance(value, list) else []


def as_str_or_none(value):
    if value is None:
        return None

    value = str(value).strip()

    return value or None


def spread(records, limit):
    """
    Deterministic representative examples.

    Distributes examples across different source documents rather than
    taking the first 10 pages from one large document.
    """

    groups = defaultdict(list)

    for rec in sorted(
        records,
        key=lambda r: (
            str(r.get("source_id", "")),
            r.get("page_number", 0),
        ),
    ):
        groups[rec["source_id"]].append(rec)

    sources = sorted(groups)

    picked = []

    while len(picked) < limit and any(groups[s] for s in sources):

        for source_id in sources:

            if groups[source_id] and len(picked) < limit:
                picked.append(groups[source_id].pop(0))

    return sorted(
        picked,
        key=lambda r: (
            str(r.get("source_id", "")),
            r.get("page_number", 0),
        ),
    )


def entry(rec, **extra):
    """
    Create a safe QC report entry.

    The full page text is NEVER placed in the QC report.
    Only a redacted preview is included.
    """

    base = {
        "source_id": rec.get("source_id"),
        "page_number": rec.get("page_number"),
        "page_id": rec.get("page_id"),
        "filename": rec.get("filename"),
        "document_type": rec.get("document_type"),
        "language": rec.get("language"),
        "content_type": rec.get("content_type"),
        "section": rec.get("section"),
        "review_required": rec.get("review_required"),
        "review_reasons": as_list(rec.get("review_reasons")),
    }

    base.update(extra)

    base["preview"] = preview(rec.get("text", ""))

    return base


def by_page(items):
    return sorted(
        items,
        key=lambda e: (
            str(e.get("source_id", "")),
            e.get("page_number", 0),
        ),
    )


# ============================================================================
# 7. JSONL VALIDATION
# ============================================================================

def validate_record(rec):

    if not isinstance(rec, dict):
        return ["not_a_json_object"]

    problems = []

    source_id = rec.get("source_id")

    if not isinstance(source_id, str) or not source_id.strip():
        problems.append("missing_source_id")

    page_number = rec.get("page_number")

    if not isinstance(page_number, int) or isinstance(page_number, bool):
        problems.append("page_number_not_an_integer")

    elif page_number < 1:
        problems.append("page_number_below_1")

    page_id = rec.get("page_id")

    if not isinstance(page_id, str) or not page_id.strip():
        problems.append("missing_page_id")

    if not isinstance(rec.get("text"), str):
        problems.append("missing_text")

    return problems


def load_records(path):

    valid = []
    malformed = []
    blank_lines = 0
    line_count = 0

    with open(path, "rb") as f:

        for line_no, raw in enumerate(f, start=1):

            line_count += 1

            if not raw.strip():
                blank_lines += 1
                continue

            try:

                encoding = (
                    "utf-8-sig"
                    if line_no == 1
                    else "utf-8"
                )

                rec = json.loads(
                    raw.decode(encoding)
                )

            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as error:

                malformed.append(
                    {
                        "line": line_no,
                        "problem": f"invalid_json: {error}",
                    }
                )

                continue

            problems = validate_record(rec)

            if problems:

                malformed.append(
                    {
                        "line": line_no,
                        "problem": ",".join(problems),
                    }
                )

            else:
                valid.append(rec)

    return (
        valid,
        malformed,
        blank_lines,
        line_count,
    )


# ============================================================================
# 8. METADATA LOADING
# ============================================================================

def load_metadata(path):

    rows = {}

    with open(
        path,
        newline="",
        encoding="utf-8-sig",
    ) as f:

        reader = csv.DictReader(f)

        for raw in reader:

            row = {
                (k or "").strip().lower():
                as_str_or_none(v)
                for k, v in raw.items()
                if k is not None
            }

            source_id = row.get("source_id")

            if source_id:
                rows.setdefault(
                    source_id,
                    row,
                )

    return rows


# ============================================================================
# 9. EXTRACTION ANOMALY CHECKS
# ============================================================================

def anomaly_details(rec):

    text = rec.get("text", "")

    details = []

    reasons = as_list(
        rec.get("review_reasons")
    )

    if "extraction_anomaly" in reasons:
        details.append(
            "flagged_extraction_anomaly"
        )

    replacement = text.count("\ufffd")

    if replacement:
        details.append(
            f"replacement_characters:{replacement}"
        )

    private_use = len(
        PRIVATE_USE_RE.findall(text)
    )

    if private_use:
        details.append(
            f"private_use_characters:{private_use}"
        )

    cid = len(
        CID_RE.findall(text)
    )

    if cid:
        details.append(
            f"cid_codes:{cid}"
        )

    chars = nonspace_len(text)

    if chars and not any(
        c.isalnum() for c in text
    ):
        details.append(
            "no_letters_or_digits"
        )

    return details


def empty_kind(rec):

    reasons = as_list(
        rec.get("review_reasons")
    )

    chars = nonspace_len(
        rec.get("text", "")
    )

    if chars == 0 or "empty_page" in reasons:
        return "empty_page"

    if (
        chars < NEAR_EMPTY_CHARS
        or "near_empty_page" in reasons
    ):
        return "near_empty_page"

    return None


# ============================================================================
# 10. METADATA QC
# ============================================================================

def check_metadata(by_source, meta_rows):

    issues = []

    page_reasons = defaultdict(list)

    def issue(
        source_id,
        kind,
        severity,
        detail,
    ):

        issues.append(
            {
                "source_id": source_id,
                "issue": kind,
                "severity": severity,
                "detail": detail,
            }
        )

    for sid in sorted(by_source):

        recs = by_source[sid]

        values = {
            field:
            {
                as_str_or_none(
                    r.get(field)
                )
                for r in recs
            }
            - {None}

            for field in DOC_FIELDS
        }

        csv_row = (
            meta_rows.get(sid)
            if meta_rows is not None
            else None
        )

        # ------------------------------------------------------------
        # 1. Source must exist in metadata
        # ------------------------------------------------------------

        if (
            meta_rows is not None
            and csv_row is None
        ):

            issue(
                sid,
                "source_id_not_in_document_metadata_csv",
                "HIGH",
                "page records exist for a source_id "
                "that has no metadata row",
            )

            for r in recs:

                page_reasons[
                    r["page_id"]
                ].append(
                    (
                        "HIGH",
                        "source_id_not_in_metadata",
                    )
                )

        # ------------------------------------------------------------
        # 2. Missing core metadata
        # ------------------------------------------------------------

        missing = [
            field
            for field in CORE_FIELDS
            if (
                not values[field]
                and not (
                    csv_row or {}
                ).get(field)
            )
        ]

        if missing:

            issue(
                sid,
                "missing_core_metadata",
                "MEDIUM",
                "missing: "
                + ", ".join(missing),
            )

            for r in recs:

                page_reasons[
                    r["page_id"]
                ].append(
                    (
                        "MEDIUM",
                        "missing_core_metadata",
                    )
                )

        # ------------------------------------------------------------
        # 3. Metadata should be consistent across pages
        # ------------------------------------------------------------

        for field in DOC_FIELDS:

            if len(values[field]) > 1:

                severity = (
                    "HIGH"
                    if field in HIGH_FIELDS
                    else "MEDIUM"
                )

                issue(
                    sid,
                    "metadata_differs_between_pages",
                    severity,
                    f"field '{field}' has "
                    f"{len(values[field])} different "
                    "values across pages",
                )

        # ------------------------------------------------------------
        # 4. Page records vs document_metadata.csv
        # ------------------------------------------------------------

        if csv_row:

            for field in DOC_FIELDS:

                record_value = (
                    next(iter(values[field]))
                    if len(values[field]) == 1
                    else None
                )

                csv_value = csv_row.get(field)

                # Both missing = no problem.
                if (
                    record_value is None
                    and csv_value is None
                ):
                    continue

                # One missing and the other populated is not
                # automatically a contradiction.
                if (
                    record_value is None
                    or csv_value is None
                ):
                    issue(
                        sid,
                        "metadata_completeness_difference",
                        "MEDIUM",
                        f"field '{field}': "
                        f"page records={record_value!r}, "
                        f"CSV={csv_value!r}",
                    )
                    continue

                # Actual disagreement.
                if record_value != csv_value:

                    severity = (
                        "HIGH"
                        if field in HIGH_FIELDS
                        else "MEDIUM"
                    )

                    issue(
                        sid,
                        "page_records_differ_from_metadata_csv",
                        severity,
                        f"field '{field}': "
                        f"page records={record_value!r}, "
                        f"CSV={csv_value!r}",
                    )

        # ------------------------------------------------------------
        # 5. Plan number / UIN vs text
        #
        # Important:
        # Additional plan/UIN values are NOT automatically conflicts.
        # They may be rider/reference values.
        # ------------------------------------------------------------

        meta_plan = (
            next(iter(values["plan_number"]))
            if len(values["plan_number"]) == 1
            else (csv_row or {}).get("plan_number")
        )

        meta_uin = (
            next(iter(values["uin"]))
            if len(values["uin"]) == 1
            else (csv_row or {}).get("uin")
        )

        plan_digits = (
            re.sub(r"\D", "", meta_plan)
            if meta_plan
            else None
        )

        uin_norm = (
            meta_uin.replace(" ", "").upper()
            if meta_uin
            else None
        )

        plan_counter = Counter()
        uin_counter = Counter()

        page_plan = {}
        page_uin = {}

        for r in recs:

            plans = PLAN_RE.findall(
                r.get("text", "")
            )

            uins = UIN_RE.findall(
                r.get("text", "")
            )

            plan_counter.update(plans)
            uin_counter.update(uins)

            page_plan[
                r["page_id"]
            ] = set(plans)

            page_uin[
                r["page_id"]
            ] = set(uins)

        # ------------------------------------------------------------
        # Plan number and UIN checks
        # ------------------------------------------------------------

        for (
            label,
            meta_value,
            counter,
            per_page,
        ) in (
            (
                "plan number",
                plan_digits,
                plan_counter,
                page_plan,
            ),
            (
                "UIN",
                uin_norm,
                uin_counter,
                page_uin,
            ),
        ):

            found = ", ".join(
                f"{value} (x{count})"
                for value, count
                in counter.most_common()
            )

            # Metadata absent but text contains value.
            if meta_value is None:

                if counter:

                    issue(
                        sid,
                        f"{label.replace(' ', '_')}_missing_in_metadata",
                        "MEDIUM",
                        f"metadata has no {label}, "
                        f"but the text shows: {found}",
                    )

                continue

            # Metadata exists but no evidence in text.
            if not counter:

                issue(
                    sid,
                    f"{label.replace(' ', '_')}_not_found_in_text",
                    "INFO",
                    f"metadata {label} {meta_value} "
                    "was not found in the text; "
                    "this is not automatically an error",
                )

                continue

            # Metadata value is absent from text.
            if meta_value not in counter:

                issue(
                    sid,
                    f"{label.replace(' ', '_')}_conflict",
                    "HIGH",
                    f"metadata {label} {meta_value} "
                    f"does not appear in the text. "
                    f"Text shows: {found}. "
                    "Verify against the original PDF; "
                    "do not auto-correct.",
                )

                for r in recs:

                    if per_page[
                        r["page_id"]
                    ]:

                        page_reasons[
                            r["page_id"]
                        ].append(
                            (
                                "HIGH",
                                f"{label.replace(' ', '_')}_metadata_not_found_in_text",
                            )
                        )

            # Additional values are possible references/riders.
            else:

                others = {
                    value
                    for value in counter
                    if value != meta_value
                }

                if others:

                    issue(
                        sid,
                        f"{label.replace(' ', '_')}_other_values_in_text",
                        "MEDIUM",
                        f"metadata {label} "
                        f"{meta_value} appears in text, "
                        f"but additional values were also found: "
                        f"{', '.join(sorted(others))}. "
                        "These may be rider/reference values; "
                        "verify only if needed.",
                    )

                    for r in recs:

                        extra_values = (
                            per_page[
                                r["page_id"]
                            ]
                            - {meta_value}
                        )

                        if extra_values:

                            page_reasons[
                                r["page_id"]
                            ].append(
                                (
                                    "MEDIUM",
                                    f"{label.replace(' ', '_')}_additional_values_in_text",
                                )
                            )

    # ------------------------------------------------------------
    # Metadata rows without page records
    # ------------------------------------------------------------

    if meta_rows is not None:

        for sid in sorted(
            set(meta_rows) - set(by_source)
        ):

            issue(
                sid,
                "metadata_row_without_page_records",
                "HIGH",
                "document exists in "
                "document_metadata.csv but has "
                "no page records",
            )

    return issues, page_reasons


# ============================================================================
# 11. MAIN
# ============================================================================

def main():

    # ------------------------------------------------------------
    # Validate input files
    # ------------------------------------------------------------

    if not RECORDS_PATH.exists():

        print(
            f"ERROR: page records not found:\n"
            f"{RECORDS_PATH}"
        )

        return 1

    if not META_PATH.exists():

        print(
            f"WARNING: document metadata not found:\n"
            f"{META_PATH}"
        )

    # ------------------------------------------------------------
    # Hash inputs before QC
    # ------------------------------------------------------------

    hashes_before = {
        RECORDS_PATH: sha256_of(
            RECORDS_PATH
        )
    }

    if META_PATH.exists():

        hashes_before[META_PATH] = sha256_of(
            META_PATH
        )

    # ------------------------------------------------------------
    # Load records
    # ------------------------------------------------------------

    (
        records,
        malformed,
        blank_lines,
        line_count,
    ) = load_records(
        RECORDS_PATH
    )

    meta_rows = (
        load_metadata(META_PATH)
        if META_PATH.exists()
        else None
    )

    # ------------------------------------------------------------
    # Group by source
    # ------------------------------------------------------------

    by_source = defaultdict(list)

    for rec in records:

        by_source[
            rec["source_id"]
        ].append(rec)

    # ------------------------------------------------------------
    # Duplicate page IDs
    # ------------------------------------------------------------

    id_counts = Counter(
        r["page_id"]
        for r in records
    )

    duplicate_ids = sorted(
        page_id
        for page_id, count
        in id_counts.items()
        if count > 1
    )

    # ------------------------------------------------------------
    # Metadata QC
    # ------------------------------------------------------------

    (
        meta_issues,
        meta_page_reasons,
    ) = check_metadata(
        by_source,
        meta_rows,
    )

    if duplicate_ids:

        meta_issues.append(
            {
                "source_id": None,
                "issue": "duplicate_page_ids",
                "severity": "HIGH",
                "detail": (
                    f"{len(duplicate_ids)} page_id "
                    "values are not unique"
                ),
            }
        )

    # ------------------------------------------------------------
    # Containers
    # ------------------------------------------------------------

    ocr_pages = []
    anomaly_pages = []
    pii_pages = []
    table_pages = []
    form_pages = []
    empty_pages = []

    unknown_section = []
    unknown_content = []
    mixed_content = []
    unknown_language = []

    language_counts = Counter()
    type_counts = Counter()
    pii_counts = Counter()

    priority_pages = []

    unmapped_reasons = Counter()

    review_required_count = 0

    # ------------------------------------------------------------
    # Page-level QC
    # ------------------------------------------------------------

    for rec in sorted(
        records,
        key=lambda r: (
            str(r.get("source_id", "")),
            r.get("page_number", 0),
        ),
    ):

        reasons = as_list(
            rec.get("review_reasons")
        )

        signals = (
            rec.get("signals")
            if isinstance(
                rec.get("signals"),
                dict,
            )
            else {}
        )

        levels = list(
            meta_page_reasons.get(
                rec["page_id"],
                [],
            )
        )

        pii_status = rec.get(
            "pii_status"
        )

        content_type = rec.get(
            "content_type"
        )

        language = rec.get(
            "language"
        )

        chars = nonspace_len(
            rec.get("text", "")
        )

        language_counts[
            language or "(missing)"
        ] += 1

        type_counts[
            content_type or "(missing)"
        ] += 1

        pii_counts[
            pii_status or "(missing)"
        ] += 1

        if rec.get(
            "review_required"
        ) is True:

            review_required_count += 1

        # --------------------------------------------------------
        # 1. OCR
        # --------------------------------------------------------

        if (
            signals.get(
                "ocr_derived"
            ) is True
            or
            "ocr_derived_verify_numbers"
            in reasons
        ):

            ocr_pages.append(
                entry(
                    rec,
                    ocr_derived=True,
                )
            )

        # --------------------------------------------------------
        # 2. Extraction anomalies
        # --------------------------------------------------------

        details = anomaly_details(
            rec
        )

        if details:

            anomaly_pages.append(
                entry(
                    rec,
                    anomaly=details,
                )
            )

            levels.append(
                (
                    "HIGH",
                    "extraction_anomaly",
                )
            )

        # --------------------------------------------------------
        # 3. PII
        # --------------------------------------------------------

        if pii_status in (
            "possible_pii",
            "public_contact_information",
            "template_fields",
        ):

            pii_pages.append(
                entry(
                    rec,
                    pii_status=pii_status,
                    pii_signals=as_list(
                        rec.get(
                            "pii_signals"
                        )
                    ),
                )
            )

        # --------------------------------------------------------
        # 4. Tables
        # --------------------------------------------------------

        possible_table = (
            "possible_table"
            in reasons
        )

        if (
            rec.get(
                "contains_table"
            ) is True
            or possible_table
        ):

            table_pages.append(
                entry(
                    rec,
                    contains_table=rec.get(
                        "contains_table"
                    ),
                    possible_table=possible_table,
                )
            )

            levels.append(
                (
                    "MEDIUM",
                    "possible_table"
                    if possible_table
                    else "table_detected",
                )
            )

        # --------------------------------------------------------
        # 5. Forms
        #
        # IMPORTANT:
        # Do not classify every page of a form document as a form.
        # Only use actual page-level evidence.
        # --------------------------------------------------------

        possible_form = (
            "possible_form"
            in reasons
        )

        contains_form = (
            rec.get(
                "contains_form"
            ) is True
        )

        if contains_form or possible_form:

            form_pages.append(
                entry(
                    rec,
                    contains_form=contains_form,
                    possible_form=possible_form,
                    form_evidence=(
                        signals.get(
                            "form_evidence"
                        )
                        or {}
                    ),
                )
            )

            levels.append(
                (
                    "MEDIUM",
                    "possible_form"
                    if possible_form
                    else "form_detected",
                )
            )

        # --------------------------------------------------------
        # 6. Unknown / mixed
        # --------------------------------------------------------

        if rec.get(
            "section"
        ) is None:

            unknown_section.append(
                rec
            )

        if content_type == "unknown":

            unknown_content.append(
                rec
            )

        if content_type == "mixed":

            mixed_content.append(
                rec
            )

        # --------------------------------------------------------
        # 7. Empty pages
        # --------------------------------------------------------

        kind = empty_kind(
            rec
        )

        if kind:

            empty_pages.append(
                entry(
                    rec,
                    empty_kind=kind,
                    non_space_chars=chars,
                )
            )

            levels.append(
                (
                    "HIGH",
                    kind,
                )
            )

        # --------------------------------------------------------
        # 8. Unknown language
        # --------------------------------------------------------

        if language == "Unknown":

            unknown_language.append(
                rec
            )

        # --------------------------------------------------------
        # 9. Existing review reasons
        # --------------------------------------------------------

        for reason in reasons:

            if reason.startswith(
                "doc_metadata_missing"
            ):

                levels.append(
                    (
                        "MEDIUM",
                        "missing_core_metadata",
                    )
                )

            elif reason in REASON_LEVELS:

                levels.append(
                    (
                        REASON_LEVELS[reason],
                        reason,
                    )
                )

            else:

                unmapped_reasons[
                    reason
                ] += 1

                levels.append(
                    (
                        "LOW",
                        reason,
                    )
                )

        # --------------------------------------------------------
        # Derived safety checks
        # --------------------------------------------------------

        if (
            pii_status == "possible_pii"
            and "possible_pii" not in reasons
        ):

            levels.append(
                (
                    "HIGH",
                    "possible_pii",
                )
            )

        if (
            signals.get(
                "ocr_derived"
            ) is True
            and
            "ocr_derived_verify_numbers"
            not in reasons
        ):

            levels.append(
                (
                    "HIGH",
                    "ocr_derived_verify_numbers",
                )
            )

        if (
            language == "Unknown"
            and
            "unknown_language"
            not in reasons
        ):

            levels.append(
                (
                    "MEDIUM",
                    "unknown_language",
                )
            )

        if (
            content_type == "mixed"
            and
            "mixed_content_types"
            not in reasons
        ):

            levels.append(
                (
                    "MEDIUM",
                    "mixed_content_types",
                )
            )

        if (
            rec.get("section") is None
            and
            "unknown_section"
            not in reasons
        ):

            levels.append(
                (
                    "LOW",
                    "unknown_section",
                )
            )

        if (
            content_type == "unknown"
            and
            "unknown_content_type"
            not in reasons
        ):

            levels.append(
                (
                    "LOW",
                    "unknown_content_type",
                )
            )

        # --------------------------------------------------------
        # Priority calculation
        # --------------------------------------------------------

        if levels:

            unique_levels = sorted(
                {
                    (
                        level,
                        reason,
                    )
                    for level, reason
                    in levels
                },
                key=lambda x: (
                    PRIORITY_RANK[x[0]],
                    x[1],
                ),
            )

            priority_pages.append(
                {
                    "scope": "page",
                    "source_id": rec[
                        "source_id"
                    ],
                    "page_number": rec[
                        "page_number"
                    ],
                    "page_id": rec[
                        "page_id"
                    ],
                    "priority": unique_levels[
                        0
                    ][0],
                    "reasons": [
                        {
                            "level": level,
                            "reason": reason,
                        }
                        for level, reason
                        in unique_levels
                    ],
                    "existing_review_required": rec.get(
                        "review_required"
                    ),
                }
            )

    # =========================================================================
    # 12. SOURCE-LEVEL HIGH METADATA ISSUES
    # =========================================================================

    for item in meta_issues:

        if (
            item["severity"] == "HIGH"
            and item["source_id"] is not None
        ):

            priority_pages.append(
                {
                    "scope": "source",
                    "source_id": item[
                        "source_id"
                    ],
                    "page_number": None,
                    "page_id": None,
                    "priority": "HIGH",
                    "reasons": [
                        {
                            "level": "HIGH",
                            "reason": item[
                                "issue"
                            ],
                        }
                    ],
                    "existing_review_required": None,
                }
            )

    priority_pages.sort(
        key=lambda p: (
            PRIORITY_RANK[
                p["priority"]
            ],
            str(p["source_id"]),
            p["page_number"]
            if p["page_number"] is not None
            else 0,
        )
    )

    priority_counts = Counter(
        p["priority"]
        for p in priority_pages
    )

    page_priority_counts = Counter(
        p["priority"]
        for p in priority_pages
        if p["scope"] == "page"
    )

    # =========================================================================
    # 13. REPRESENTATIVE EXAMPLES
    # =========================================================================

    def category(
        items,
        extra=None,
    ):

        chosen = spread(
            items,
            MAX_EXAMPLES,
        )

        return {
            "count": len(items),
            "sources_affected": len(
                {
                    r["source_id"]
                    for r in items
                }
            ),
            "examples_shown": len(
                chosen
            ),
            "representative_examples": [
                entry(
                    r,
                    **(
                        extra(r)
                        if extra
                        else {}
                    ),
                )
                for r in chosen
            ],
        }

    unknown_section_report = category(
        unknown_section,
        lambda r: {
            "section_at_page_start":
                r.get(
                    "section_at_page_start"
                )
        },
    )

    unknown_section_report[
        "with_earlier_section_context"
    ] = sum(
        1
        for r in unknown_section
        if r.get(
            "section_at_page_start"
        )
    )

    # =========================================================================
    # 14. LANGUAGE REPORT
    # =========================================================================

    shown_unknown_language = spread(
        unknown_language,
        MAX_UNKNOWN_LANGUAGE,
    )

    language_report = {
        "counts": dict(
            sorted(
                language_counts.items(),
                key=lambda kv: -kv[1],
            )
        ),
        "unknown_language_count":
            len(unknown_language),

        "unknown_language_with_substantial_text":
            sum(
                1
                for r in unknown_language
                if nonspace_len(
                    r.get("text", "")
                ) >= SUBSTANTIVE_CHARS
            ),

        "unknown_language_pages_listed":
            len(
                shown_unknown_language
            ),

        "unknown_language_pages": [
            entry(
                r,
                non_space_chars=
                    nonspace_len(
                        r.get(
                            "text",
                            "",
                        )
                    ),
                substantial_text=
                    nonspace_len(
                        r.get(
                            "text",
                            "",
                        )
                    )
                    >= SUBSTANTIVE_CHARS,
            )
            for r in shown_unknown_language
        ],
    }

    # =========================================================================
    # 15. CONTENT TYPE SUMMARY
    # =========================================================================

    content_summary = {}

    for content_type, count in sorted(
        type_counts.items(),
        key=lambda kv: (
            -kv[1],
            kv[0] or "",
        ),
    ):

        content_summary[
            content_type or "(missing)"
        ] = count

    # =========================================================================
    # 16. PII SORTING
    # =========================================================================

    pii_priority = {
        "possible_pii": 0,
        "public_contact_information": 1,
        "template_fields": 2,
    }

    pii_pages.sort(
        key=lambda e: (
            pii_priority.get(
                e["pii_status"],
                99,
            ),
            str(e["source_id"]),
            e["page_number"],
        )
    )

    # =========================================================================
    # 17. PER-SOURCE SUMMARY
    # =========================================================================

    per_source = {}

    for sid in sorted(by_source):

        recs = by_source[sid]

        per_source[sid] = {

            "pages": len(recs),

            "ocr": sum(
                1
                for r in recs
                if (
                    r.get("signals") or {}
                ).get(
                    "ocr_derived"
                ) is True
            ),

            "possible_pii": sum(
                1
                for r in recs
                if r.get(
                    "pii_status"
                ) == "possible_pii"
            ),

            "tables": sum(
                1
                for r in recs
                if r.get(
                    "contains_table"
                ) is True
            ),

            "forms": sum(
                1
                for r in recs
                if r.get(
                    "contains_form"
                ) is True
            ),

            "unknown_section": sum(
                1
                for r in recs
                if r.get(
                    "section"
                ) is None
            ),

            "unknown_content_type": sum(
                1
                for r in recs
                if r.get(
                    "content_type"
                ) == "unknown"
            ),

            "existing_review_required": sum(
                1
                for r in recs
                if r.get(
                    "review_required"
                ) is True
            ),
        }

    # =========================================================================
    # 18. SUMMARY
    # =========================================================================

    summary = {

        "ocr_pages":
            len(ocr_pages),

        "extraction_anomalies":
            len(anomaly_pages),

        "pii_status_counts":
            dict(pii_counts),

        "possible_pii":
            pii_counts.get(
                "possible_pii",
                0,
            ),

        "public_contact_information":
            pii_counts.get(
                "public_contact_information",
                0,
            ),

        "template_fields":
            pii_counts.get(
                "template_fields",
                0,
            ),

        "pages_with_tables_or_possible_tables":
            len(table_pages),

        "pages_with_forms_or_possible_forms":
            len(form_pages),

        "empty_or_near_empty_pages":
            len(empty_pages),

        "unknown_section":
            len(unknown_section),

        "unknown_content_type":
            len(unknown_content),

        "mixed_content_type":
            len(mixed_content),

        "unknown_language":
            len(unknown_language),

        "existing_review_required_pages":
            review_required_count,

        "priority_issue_counts_pages":
            dict(page_priority_counts),

        "priority_issue_counts_all_entries":
            dict(priority_counts),

        "metadata_issues_by_severity":
            dict(
                Counter(
                    i["severity"]
                    for i in meta_issues
                )
            ),

        "unmapped_review_reasons":
            dict(unmapped_reasons),

        "malformed_records":
            len(malformed),

        "duplicate_page_ids":
            len(duplicate_ids),

        "per_source":
            per_source,
    }

    # =========================================================================
    # 19. INPUT INTEGRITY CHECK
    # =========================================================================

    hashes_after = {
        path: sha256_of(path)
        for path in hashes_before
    }

    changed = [
        rel(path)
        for path in hashes_before
        if hashes_before[path]
        != hashes_after[path]
    ]

    inputs_info = {

        rel(RECORDS_PATH): {
            "sha256":
                hashes_after[
                    RECORDS_PATH
                ],
            "lines":
                line_count,
            "blank_lines":
                blank_lines,
        }
    }

    if META_PATH in hashes_after:

        inputs_info[
            rel(META_PATH)
        ] = {
            "sha256":
                hashes_after[
                    META_PATH
                ]
        }

    # =========================================================================
    # 20. FINAL REPORT
    # =========================================================================

    report = {

        "schema_version":
            SCHEMA_VERSION,

        "purpose":
            "Pre-chunking quality-control report for page-level knowledge-base records.",

        "inputs":
            inputs_info,

        "inputs_unchanged":
            not changed,

        "total_pages":
            len(records),

        "total_sources":
            len(by_source),

        "summary":
            summary,

        "ocr_pages":
            by_page(ocr_pages),

        "extraction_anomalies":
            by_page(anomaly_pages),

        "pii_pages":
            pii_pages,

        "table_pages":
            by_page(table_pages),

        "form_pages":
            by_page(form_pages),

        "empty_pages":
            by_page(empty_pages),

        "unknown_section":
            unknown_section_report,

        "unknown_content_type":
            category(
                unknown_content
            ),

        "mixed_content_type":
            category(
                mixed_content
            ),

        "language_summary":
            language_report,

        "content_type_summary":
            content_summary,

        "metadata_issues":
            meta_issues,

        "malformed_records": {
            "count":
                len(malformed),

            "listed":
                min(
                    len(malformed),
                    MAX_MALFORMED_LISTED,
                ),

            "records":
                malformed[
                    :MAX_MALFORMED_LISTED
                ],
        },

        "review_priority":
            priority_pages,
    }

    # =========================================================================
    # 21. WRITE ONLY qc_report.json
    # =========================================================================

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        REPORT_PATH,
        "w",
        encoding="utf-8",
        newline="\n",
    ) as f:

        json.dump(
            report,
            f,
            ensure_ascii=False,
            indent=2,
        )

        f.write("\n")

    # =========================================================================
    # 22. TERMINAL SUMMARY
    # =========================================================================

    print("=" * 70)
    print("PAGE RECORD QC SUMMARY")
    print("=" * 70)

    print(
        f"Total records:                "
        f"{len(records)} "
        f"(JSONL lines: {line_count}, "
        f"blank: {blank_lines})"
    )

    print(
        f"Total sources:                "
        f"{len(by_source)}"
    )

    print(
        f"OCR pages:                    "
        f"{len(ocr_pages)}"
    )

    print(
        f"Extraction anomalies:         "
        f"{len(anomaly_pages)}"
    )

    print(
        f"Possible PII:                 "
        f"{pii_counts.get('possible_pii', 0)} "
        f"(public contact: "
        f"{pii_counts.get('public_contact_information', 0)}, "
        f"template fields: "
        f"{pii_counts.get('template_fields', 0)})"
    )

    print(
        f"Possible tables:              "
        f"{len(table_pages)} "
        f"(contains_table = true: "
        f"{sum(1 for r in records if r.get('contains_table') is True)})"
    )

    print(
        f"Possible forms:               "
        f"{len(form_pages)} "
        f"(contains_form = true: "
        f"{sum(1 for r in records if r.get('contains_form') is True)})"
    )

    print(
        f"Empty / near-empty pages:     "
        f"{len(empty_pages)}"
    )

    print(
        f"Unknown sections:             "
        f"{len(unknown_section)}"
    )

    print(
        f"Unknown content types:        "
        f"{len(unknown_content)}"
    )

    print(
        f"Mixed content:                "
        f"{len(mixed_content)}"
    )

    print(
        f"Unknown languages:            "
        f"{len(unknown_language)}"
    )

    print(
        f"Languages:                    "
        f"{dict(language_report['counts'])}"
    )

    print(
        f"Content types:                "
        f"{content_summary}"
    )

    print(
        f"Existing review_required:     "
        f"{review_required_count} "
        f"of {len(records)}"
    )

    print(
        f"Pages by priority:            "
        f"HIGH {page_priority_counts.get('HIGH', 0)}, "
        f"MEDIUM {page_priority_counts.get('MEDIUM', 0)}, "
        f"LOW {page_priority_counts.get('LOW', 0)}"
    )

    print(
        f"Metadata issues:              "
        f"{len(meta_issues)} "
        f"{summary['metadata_issues_by_severity']}"
    )

    print(
        f"Malformed records:            "
        f"{len(malformed)}"
    )

    # Show only meaningful metadata issues.
    for item in meta_issues:

        if item["severity"] in (
            "HIGH",
            "MEDIUM",
        ):

            print(
                f"   [{item['severity']}] "
                f"{item['source_id']}: "
                f"{item['issue']} - "
                f"{item['detail']}"
            )

    # Show malformed records.
    for item in malformed[:10]:

        print(
            f"   MALFORMED line "
            f"{item['line']}: "
            f"{item['problem']}"
        )

    if unmapped_reasons:

        print(
            "Review reasons not explicitly "
            "mapped to priority: "
            f"{dict(unmapped_reasons)}"
        )

    if meta_rows is None:

        print(
            "NOTE: document_metadata.csv "
            "not found - metadata checks skipped."
        )

    print()

    print(
        "Input files unchanged:        "
        f"{'YES' if not changed else 'NO - ' + str(changed)}"
    )

    print(
        f"QC report written to:         "
        f"{REPORT_PATH}"
    )

    return 0


# ============================================================================
# 23. ENTRY POINT
# ============================================================================

if __name__ == "__main__":

    try:
        sys.stdout.reconfigure(
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        pass

    raise SystemExit(
        main()
    )