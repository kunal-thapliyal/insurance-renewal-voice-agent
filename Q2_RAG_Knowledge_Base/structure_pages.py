import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ---------------------------------------------------------------------------
# 1. Paths and settings
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
META_CSV = BASE_DIR / "Data" / "processed" / "metadata" / "document_metadata.csv"
NORM_DIR = BASE_DIR / "Data" / "processed" / "normalized"
OUT_DIR = BASE_DIR / "Data" / "processed" / "structured"
RECORDS_JSONL = OUT_DIR / "page_records.jsonl"

SCHEMA_VERSION = "1.0"

# Pages whose text came from OCR (their numbers must be checked against the image).
# "all" = every page, or a list of PDF page numbers.
OCR_PAGES = {
    "LIC-002": "all",
    "LIC-015A": [1],
}

CORE_FIELDS = ("title", "authority", "document_type")
NEAR_EMPTY_CHARS = 20
SUBSTANTIVE_CHARS = 300
BROCHURE_WORDS = ("brochure", "leaflet", "flyer", "marketing", "advertisement")

SKIP_COLUMNS = {"source_id", "filename", "file_exists"}
RENAME_COLUMNS = {"language": "document_language"}
RESERVED_KEYS = {
    "page_id", "source_id", "page_number", "filename", "text_filename", "citation",
    "language", "section", "section_confidence", "section_source",
    "section_at_page_start", "section_at_page_start_from_page", "headings",
    "candidate_headings", "topics", "content_type", "content_type_confidence",
    "content_types_detected", "content_type_basis", "pii_status", "pii_signals",
    "contains_table", "contains_form", "review_required", "review_reasons",
    "keyword_hits", "signals", "char_count", "word_count", "line_count",
    "text_hash", "previous_page_id", "next_page_id", "schema_version", "text",
}

# Reasons that set review_required = True.
HARD_REASONS = {
    "empty_page",
    "near_empty_page",
    "possible_pii",
    "possible_table",
    "possible_form",
    "extraction_anomaly",
    "ocr_derived_verify_numbers",
    "duplicate_page_number",
    "low_confidence_content_type",
    "unknown_language",
    "no_section_and_no_content_type",
}


# ---------------------------------------------------------------------------
# 2. Vocabulary
# ---------------------------------------------------------------------------
HEADING_LIST = [
    ("Death Benefit", "death_benefit", "benefit"),
    ("Survival Benefit", "survival_benefit", "benefit"),
    ("Maturity Benefit", "maturity_benefit", "benefit"),
    ("Guaranteed Additions", "guaranteed_additions", "benefit"),
    ("Loyalty Additions", "loyalty_additions", "benefit"),
    ("Benefits", "benefits", "benefit"),
    ("Riders", "riders", "benefit"),
    ("Premium Payment", "premium_payment", "rule"),
    ("Mode of Payment", "premium_payment", "rule"),
    ("Grace Period", "grace_period", "rule"),
    ("Lapse", "lapse", "rule"),
    ("Waiting Period", "waiting_period", "rule"),
    ("Revival", "revival", "procedure"),
    ("Revival of Lapsed Policy", "revival", "procedure"),
    ("Surrender", "surrender", "rule"),
    ("Surrender Value", "surrender", "rule"),
    ("Paid-up Value", "paid_up", "rule"),
    ("Policy Loan", "policy_loan", "rule"),
    ("Free Look Period", "free_look_period", "rule"),
    ("Free-Look Period", "free_look_period", "rule"),
    ("Nomination", "nomination", "rule"),
    ("Assignment", "assignment", "rule"),
    ("Terms and Conditions", "terms_and_conditions", "rule"),
    ("Exclusions", "exclusions", "exclusion"),
    ("Eligibility", "eligibility", "eligibility"),
    ("Definitions", "definitions", "definition"),
    ("Claim Procedure", "claims", "procedure"),
    ("Claims", "claims", "procedure"),
    ("Documents Required", "documents_required", "procedure"),
    ("Grievance Redressal", "grievance_redressal", "procedure"),
    ("Disclaimer", "disclaimer", "disclaimer"),
    ("Contact Details", "contact", "contact"),
]

HEADING_VOCAB = {
    name.lower(): (name, slug, ctype)
    for name, slug, ctype in HEADING_LIST
}

_names_longest_first = sorted(
    (n for n, _, _ in HEADING_LIST),
    key=len,
    reverse=True,
)

INLINE_HEADING_RE = re.compile(
    r"^("
    + "|".join(re.escape(n) for n in _names_longest_first)
    + r")\s*[:\u2013\u2014-]\s*\S",
    re.IGNORECASE,
)

KEYWORDS = [
    "grace period",
    "lapse",
    "lapsed",
    "revival",
    "revive",
    "reinstate",
    "free look",
    "free-look",
    "surrender",
    "paid-up",
    "paid up",
    "policy loan",
    "premium due",
    "due date",
    "nominee",
    "nomination",
    "ecs",
    "nach",
    "auto debit",
    "late fee",
]

KEYWORD_RES = [
    (k, re.compile(r"\b" + re.escape(k) + r"\b", re.IGNORECASE))
    for k in KEYWORDS
]

COMPLIANCE_PHRASES = [
    "subject matter of solicitation",
    "prohibition of rebates",
    "section 41",
    "spurious phone calls",
    "fraudulent",
    "beware of",
]

CONTACT_WORDS = (
    "grievance",
    "helpline",
    "customer care",
    "toll free",
    "toll-free",
    "ombudsman",
    "nodal officer",
    "contact us",
    "call cent",
    "customer service",
)

OFFICIAL_DOMAINS = (
    "licindia.in",
    "irdai.gov.in",
    "gov.in",
    "nic.in",
    "policyholder.gov.in",
    "cioins.co.in",
)

PERSONAL_DOMAINS = (
    "gmail.",
    "yahoo.",
    "hotmail.",
    "outlook.",
    "rediffmail.",
    "live.com",
)


# ---------------------------------------------------------------------------
# 3. Patterns
# ---------------------------------------------------------------------------
MARKER_RE = re.compile(
    r"^---\s*PAGE\s+(\d+)\s*---$",
    re.IGNORECASE,
)

LEADING_NUMBER_RE = re.compile(
    r"^(?:section\s+)?"
    r"(?:\d+(?:\.\d+)*[.):]?|[ivxlc]+[.)]|[a-z][.)]|\([a-z0-9ivx]+\))\s+",
    re.IGNORECASE,
)

ID_RE = re.compile(r"^\s*([A-Za-z]+)[\s_\-]*(\d+[A-Za-z]?)")

STRUCTURAL_RE = re.compile(
    r"^(?:(?:CHAPTER|Chapter)\s+(?:[IVXLC]+|\d+)\b[^.]{0,60}"
    r"|(?:SCHEDULE|Schedule|ANNEXURE|Annexure|APPENDIX|Appendix)"
    r"\s*(?:[IVXLC]+|\d+|[A-Z])?\b[^.]{0,60}"
    r"|(?:Regulation|REGULATION)\s+\d+[A-Za-z]?\.?)$"
)

NUMBERED_TITLE_RE = re.compile(
    r"^\d{1,2}(?:\.\d{1,2})*[.)]\s+[A-Z][A-Za-z'\u2019/&,\\-]*"
    r"(?:\s+(?:of|and|the|for|to|in|on|by|or|a|an|&|"
    r"[A-Z][A-Za-z'\u2019/&,\\-]*)){0,6}$"
)

ALLCAPS_TITLE_RE = re.compile(r"^[A-Z][A-Z &/\-]{4,50}$")

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

MOBILE_RE = re.compile(
    r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)"
)

LANDLINE_RE = re.compile(
    r"(?<!\d)0\d{2,4}[\s-]?\d{6,8}(?!\d)"
    r"|(?<!\d)0\d{2,4}[\s-]\d{3,4}[\s-]\d{3,4}(?!\d)"
)

TOLLFREE_RE = re.compile(
    r"(?<!\d)1800[\s-]?\d{3}[\s-]?\d{3,4}(?!\d)"
)

PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")

AADHAAR_RE = re.compile(
    r"(?<!\d)\d{4}\s\d{4}\s\d{4}(?!\d)"
)

IFSC_RE = re.compile(
    r"\b[A-Z]{4}0[A-Z0-9]{6}\b"
)

DOB_VALUE_RE = re.compile(
    r"(?:date\s+of\s+birth|d\.?o\.?b\.?)\s*[:\-]?\s*"
    r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}",
    re.IGNORECASE,
)

ACCOUNT_VALUE_RE = re.compile(
    r"account\s*(?:no\.?|number)\s*[:\-]?\s*\d{9,18}",
    re.IGNORECASE,
)

POLICY_VALUE_RE = re.compile(
    r"policy\s*(?:no\.?|number)\s*[:\-]?\s*\d{6,}",
    re.IGNORECASE,
)

DEFINITION_RE = re.compile(
    r"[\u201c\"][A-Z][^\u201d\"\n]{1,60}[\u201d\"]\s+"
    r"(?:means|shall\s+mean|shall\s+have\s+the\s+meaning)"
)

NUMERIC_SHORT_RE = re.compile(
    r"^[\d\s,.%\u20b9/\-\u2013()]+$"
)

STEP_RE = re.compile(
    r"^\s*step\s*\d+\b",
    re.IGNORECASE,
)

FORM_TITLE_RE = re.compile(
    r"\bForm\s*(?:No\.?|Number)?\s*[:\-]?\s*\d{2,4}\b",
    re.IGNORECASE,
)

SIGNATURE_RE = re.compile(
    r"\b(?:signature|declaration|applicant|proposer|policyholder|"
    r"life\s+assured|witness|thumb\s+impression)\b",
    re.IGNORECASE,
)

TABLE_TITLE_RE = re.compile(
    r"\btable\s+\d+\b|\bpremium\s+rates?\b|\brate\s+table\b",
    re.IGNORECASE,
)

PLAN_RE = re.compile(
    r"\bPlan\s*(?:No\.?|Number)\s*[:.\-]?\s*(\d{3})\b",
    re.IGNORECASE,
)

UIN_RE = re.compile(
    r"\b\d{3}[A-Z]\d{3}V\d{2}\b"
)

HARD_CORRUPTION_RE = re.compile(
    r"\ufffd|\(cid:\d+\)"
)

PRIVATE_USE_RE = re.compile(
    r"[\ue000-\uf8ff]"
)


# ---------------------------------------------------------------------------
# 4. Small helpers
# ---------------------------------------------------------------------------
def squash(text):
    return " ".join(text.split())


def nonspace_len(text):
    return len("".join(text.split()))


def clean_value(value):
    """Empty / 'null' style cells become None. Nothing else is changed."""
    if value is None:
        return None

    value = str(value).strip()

    return None if value.lower() in {
        "",
        "null",
        "none",
        "nan",
    } else value


def norm_stem(name):
    return squash(Path(str(name)).stem.lower())


def id_from_text(text):
    match = ID_RE.match(text or "")

    return (
        f"{match.group(1).upper()}-{match.group(2).upper()}"
        if match
        else None
    )


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 5. Metadata loading and file -> source_id mapping
# ---------------------------------------------------------------------------
def load_metadata(path):
    """Return (rows_by_source_id, doc_columns, warnings)."""

    warnings = []
    rows = {}

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        columns = [
            (c or "").strip().lower()
            for c in (reader.fieldnames or [])
        ]

        if "source_id" not in columns:
            raise ValueError(
                "document_metadata.csv has no 'source_id' column"
            )

        for raw in reader:
            row = {
                (k or "").strip().lower(): clean_value(v)
                for k, v in raw.items()
                if k is not None
            }

            sid = row.get("source_id")

            if not sid:
                warnings.append(
                    "a metadata row without source_id was ignored"
                )

            elif sid in rows:
                warnings.append(
                    f"duplicate source_id in metadata: {sid} "
                    f"(first row kept)"
                )

            else:
                rows[sid] = row

    return (
        rows,
        [c for c in columns if c not in SKIP_COLUMNS],
        warnings,
    )


def map_files_to_metadata(txt_files, meta_rows):
    """
    Match each normalized .txt to a metadata row:

      1) by metadata 'filename' column,
      2) otherwise by ID at start of filename.

    Anything unmatched is returned in `unmatched`.
    """

    by_stem = {}
    by_id = {}

    for sid, row in meta_rows.items():

        if row.get("filename"):
            by_stem.setdefault(
                norm_stem(row["filename"]),
                sid,
            )

        key = id_from_text(sid)

        if key:
            by_id.setdefault(key, []).append(sid)

    mapping = {}
    unmatched = []
    warnings = []

    for path in txt_files:

        sid = by_stem.get(norm_stem(path.name))

        id_key = id_from_text(path.stem)

        by_id_match = (
            by_id.get(id_key, [])
            if id_key
            else []
        )

        if sid is None and len(by_id_match) == 1:

            sid = by_id_match[0]

        elif (
            sid is not None
            and by_id_match
            and sid not in by_id_match
        ):

            warnings.append(
                f"{path.name}: file name and ID point to "
                f"different rows ({sid} vs {by_id_match}); "
                f"used {sid}"
            )

        if sid is None:
            unmatched.append(path.name)

        else:
            mapping[path] = sid

    return mapping, unmatched, warnings


# ---------------------------------------------------------------------------
# 6. Parse a normalized text file into pages
# ---------------------------------------------------------------------------
def parse_pages(text):
    """
    Return:

        pages
        text_before_first_marker
        marker_chars

    pages = list of (page_number, page_text)
    """

    pages = []
    before = []

    current_no = None
    current = []
    marker_chars = 0

    for line in text.split("\n"):

        match = MARKER_RE.match(line.strip())

        if match:

            if current_no is not None:
                pages.append(
                    (
                        current_no,
                        "\n".join(current),
                    )
                )

            current_no = int(match.group(1))
            current = []

            marker_chars += nonspace_len(line)

        elif current_no is None:

            before.append(line)

        else:

            current.append(line)

    if current_no is not None:
        pages.append(
            (
                current_no,
                "\n".join(current),
            )
        )

    return (
        [
            (n, t.strip("\n"))
            for n, t in pages
        ],
        "\n".join(before),
        marker_chars,
    )


# ---------------------------------------------------------------------------
# 7. Page analysis pieces
# ---------------------------------------------------------------------------
def detect_language(text):
    """
    Script-based:

    English
    Hindi
    Mixed
    Unknown
    """

    letters = [
        c
        for c in text
        if c.isalpha()
    ]

    if len(letters) < 15:
        return "Unknown"

    hindi = sum(
        1
        for c in letters
        if "\u0900" <= c <= "\u097f"
    )

    latin = sum(
        1
        for c in letters
        if c.isascii()
    )

    if hindi / len(letters) >= 0.7:
        return "Hindi"

    if (
        hindi >= 5
        and hindi / len(letters) >= 0.03
    ):
        return "Mixed"

    return (
        "English"
        if latin / len(letters) >= 0.8
        else "Unknown"
    )


def match_vocab_heading(line):
    """A line that IS a known heading, or starts with one."""

    s = line.strip()

    if (
        not s
        or len(s) > 200
        or s.startswith(("- ", "\u2022"))
    ):
        return None

    s = LEADING_NUMBER_RE.sub(
        "",
        s,
        count=1,
    ).strip()

    if not s or not s[0].isupper():
        return None

    inline = INLINE_HEADING_RE.match(s)

    if inline:
        return HEADING_VOCAB.get(
            inline.group(1).lower()
        )

    if len(s) <= 60:

        s = (
            s.rstrip(":")
            .strip()
            .strip("\"\u201c\u201d'")
            .strip()
        )

        return HEADING_VOCAB.get(
            squash(s).lower()
        )

    return None


def find_sections(lines):
    """
    Return:

        headings
        topics
        section
        section_source
        candidates
        structural
    """

    headings = []
    topics = []
    structural = []
    candidates = []

    for line in lines:

        hit = match_vocab_heading(line)

        if hit:

            if hit[0] not in headings:
                headings.append(hit[0])

            if hit[1] not in topics:
                topics.append(hit[1])

            continue

        if (
            len(line) <= 80
            and STRUCTURAL_RE.match(line.strip())
        ):

            if line.strip() not in structural:
                structural.append(line.strip())

            continue

        if (
            len(candidates) < 8
            and len(line) <= 70
            and not line.endswith(".")
        ):

            if (
                NUMBERED_TITLE_RE.match(line)
                or ALLCAPS_TITLE_RE.match(line)
            ):
                candidates.append(line.strip())

    if headings:
        section = headings[0]
        source = "heading_vocabulary"

    elif structural:
        section = structural[0]
        source = "structural_marker"

    else:
        section = None
        source = None

    return (
        headings,
        topics,
        section,
        source,
        candidates,
        structural,
    )


def detect_table(lines, text):
    """
    Returns:

        contains_table
        table_uncertain
        numeric_short
        numeric_share
    """

    numeric_short = sum(
        1
        for l in lines
        if (
            len(l) <= 14
            and NUMERIC_SHORT_RE.match(l)
        )
    )

    share = (
        numeric_short / len(lines)
        if lines
        else 0.0
    )

    pipes = sum(
        1
        for l in lines
        if (
            "\t" in l
            or l.count(" | ") >= 1
        )
    )

    contains = (
        (
            numeric_short >= 12
            and share >= 0.35
        )
        or pipes >= 3
    )

    uncertain = (
        not contains
        and (
            (
                numeric_short >= 6
                and share >= 0.2
            )
            or (
                bool(TABLE_TITLE_RE.search(text))
                and numeric_short >= 4
            )
        )
    )

    return (
        contains,
        uncertain,
        numeric_short,
        share,
    )


def detect_form(lines, text):
    """Returns form detection and evidence."""

    blank_underscore = sum(
        1
        for l in lines
        if re.search(r"_{4,}", l)
    )

    blank_dotted = sum(
        1
        for l in lines
        if (
            re.search(r"\.{8,}", l)
            and not re.search(
                r"\.{5,}\s*\d+\s*$",
                l,
            )
        )
    )

    blank_fields = (
        blank_underscore
        + blank_dotted
    )

    label_lines = sum(
        1
        for l in lines
        if (
            l.endswith(":")
            and 3 <= len(l) <= 60
            and any(c.isalpha() for c in l)
        )
    )

    form_title = any(
        FORM_TITLE_RE.search(l)
        for l in lines[:10]
    )

    sig_hits = len(
        {
            m.lower()
            for m in SIGNATURE_RE.findall(text)
        }
    )

    contains = (
        blank_fields >= 3
        or (
            blank_fields >= 1
            and (
                form_title
                or label_lines >= 3
            )
        )
        or (
            label_lines >= 5
            and sig_hits >= 2
        )
    )

    uncertain = (
        not contains
        and (
            blank_fields >= 1
            or form_title
            or (
                label_lines >= 3
                and sig_hits >= 1
            )
        )
    )

    evidence = {
        "blank_field_lines": blank_fields,
        "label_only_lines": label_lines,
        "form_title_found": form_title,
        "signature_words": sig_hits,
    }

    return (
        contains,
        uncertain,
        evidence,
    )


def detect_pii(
    text,
    blank_fields,
    label_lines,
    analysable,
):
    """
    Classify PII but never remove it.

    possible_pii
    public_contact_information
    template_fields
    none_detected
    """

    if not analysable:
        return (
            "unknown",
            ["page_empty_or_unreadable"],
            {},
        )

    lower = text.lower()

    emails = EMAIL_RE.findall(text)

    phones = (
        len(MOBILE_RE.findall(text))
        + len(LANDLINE_RE.findall(text))
        + len(TOLLFREE_RE.findall(text))
    )

    contact_context = (
        any(
            w in lower
            for w in CONTACT_WORDS
        )
        or bool(TOLLFREE_RE.search(text))
    )

    personal = []

    for name, rx in (
        ("pan", PAN_RE),
        ("aadhaar", AADHAAR_RE),
        ("ifsc", IFSC_RE),
        ("dob_with_value", DOB_VALUE_RE),
        (
            "account_number_with_value",
            ACCOUNT_VALUE_RE,
        ),
        (
            "policy_number_with_value",
            POLICY_VALUE_RE,
        ),
    ):

        count = len(rx.findall(text))

        if count:
            personal.append(name)

    public_emails = 0

    for email in emails:

        lower_email = email.lower()

        if any(
            domain in lower_email
            for domain in OFFICIAL_DOMAINS
        ):
            public_emails += 1

    if personal:

        status = "possible_pii"
        signals = personal

    elif (
        emails
        and public_emails < len(emails)
    ):

        status = "possible_pii"

        signals = [
            "non_official_email"
        ]

    elif emails or phones:

        status = (
            "public_contact_information"
            if contact_context
            else "possible_pii"
        )

        signals = []

        if status == "possible_pii":
            signals.append(
                "contact_details_outside_contact_context"
            )

    elif (
        blank_fields
        or label_lines >= 3
    ):

        status = "template_fields"
        signals = []

    else:

        status = "none_detected"
        signals = []

    return (
        status,
        signals,
        {
            "emails": len(emails),
            "phones": phones,
        },
    )


# ---------------------------------------------------------------------------
# 8. Content type
# ---------------------------------------------------------------------------
RANK = {
    "high": 3,
    "medium": 2,
    "low": 1,
}


def classify_content(ctx):
    """
    Collect evidence for each content type,
    then pick one only if evidence is clear.
    """

    found = {}

    def add(
        ctype,
        confidence,
        basis,
    ):

        entry = found.setdefault(
            ctype,
            [confidence, []],
        )

        if (
            RANK[confidence]
            > RANK[entry[0]]
        ):
            entry[0] = confidence

        entry[1].append(basis)

    if ctx["contains_form"]:

        strong = (
            ctx["form_evidence"][
                "blank_field_lines"
            ] >= 3
        )

        add(
            "form",
            "high" if strong else "medium",
            f"form evidence {ctx['form_evidence']}",
        )

    elif "form" in (
        ctx["document_type"] or ""
    ).lower():

        add(
            "form",
            "low",
            "document_type is a form "
            "(no page-level evidence)",
        )

    contact_items = (
        ctx["emails"]
        + ctx["phones"]
    )

    has_contact_word = any(
        w in ctx["lower"]
        for w in CONTACT_WORDS
    )

    if contact_items >= 5:

        add(
            "contact",
            "high",
            f"{contact_items} emails/phone numbers",
        )

    elif (
        contact_items >= 2
        and has_contact_word
    ):

        add(
            "contact",
            "medium",
            f"{contact_items} emails/phone numbers "
            "with contact wording",
        )

    if (
        ctx["contains_table"]
        and ctx["numeric_share"] >= 0.6
        and ctx["line_count"] >= 20
    ):

        add(
            "table",
            "medium",
            f"{ctx['numeric_short']} of "
            f"{ctx['line_count']} lines are "
            "short numeric values",
        )

    if ctx["definition_count"] >= 3:

        add(
            "definition",
            "high",
            f"{ctx['definition_count']} "
            "quoted-term 'means' definitions",
        )

    if ctx["step_lines"] >= 2:

        add(
            "procedure",
            "medium",
            f"{ctx['step_lines']} 'Step n' lines",
        )

    for name in ctx["headings"]:

        add(
            HEADING_VOCAB[name.lower()][2],
            "medium",
            f"heading:{name}",
        )

    if (
        ctx["compliance_phrases"]
        and ctx["non_compliance_chars"] < 400
    ):

        add(
            "disclaimer",
            "medium",
            "page is mainly compliance wording",
        )

    if (
        not found
        and ctx["chars"] >= SUBSTANTIVE_CHARS
        and any(
            w in (
                ctx["document_type"] or ""
            ).lower()
            for w in BROCHURE_WORDS
        )
    ):

        add(
            "marketing",
            "low",
            "brochure-type document, no other "
            "evidence (document-type guess)",
        )

    if not found:
        return (
            "unknown",
            None,
            [],
            [],
        )

    detected = sorted(found)

    if len(found) == 1:

        ctype = detected[0]

        return (
            ctype,
            found[ctype][0],
            found[ctype][1],
            detected,
        )

    top = max(
        RANK[v[0]]
        for v in found.values()
    )

    tops = [
        t
        for t, v in found.items()
        if RANK[v[0]] == top
    ]

    if len(tops) == 1:

        return (
            tops[0],
            found[tops[0]][0],
            found[tops[0]][1],
            detected,
        )

    basis = [
        b
        for v in found.values()
        for b in v[1]
    ]

    return (
        "mixed",
        "medium",
        basis,
        detected,
    )


def is_ocr_page(
    source_id,
    page_number,
):
    rule = OCR_PAGES.get(source_id)

    return (
        rule == "all"
        or (
            isinstance(rule, list)
            and page_number in rule
        )
    )


# ---------------------------------------------------------------------------
# 9. Document-level cross-check
# ---------------------------------------------------------------------------
def crosscheck(
    meta_value,
    found_counter,
    digits_only=False,
):

    found = ";".join(
        f"{v}x{n}"
        for v, n
        in found_counter.most_common()
    )

    if meta_value is None:

        return (
            found,
            (
                "metadata_empty"
                if not found
                else "metadata_empty_but_text_has_values"
            ),
        )

    wanted = (
        re.sub(r"\D", "", meta_value)
        if digits_only
        else meta_value.replace(
            " ",
            "",
        ).upper()
    )

    if not found:

        return (
            found,
            "no_evidence_in_text",
        )

    if wanted in found_counter:

        return (
            found,
            (
                "ok"
                if len(found_counter) == 1
                else "ok_but_other_values_in_text"
            ),
        )

    return (
        found,
        "METADATA_NOT_FOUND_IN_TEXT",
    )


# ---------------------------------------------------------------------------
# 10. Build records for one document
# ---------------------------------------------------------------------------
def build_document(
    txt_path,
    source_id,
    meta,
    doc_columns,
):

    text = txt_path.read_text(
        encoding="utf-8"
    )

    pages, before, marker_chars = parse_pages(text)

    problems = []

    if before.strip():

        problems.append(
            "text found before the first page marker "
            "(not in any page record)"
        )

    if (
        nonspace_len(text)
        - marker_chars
        - nonspace_len(before)
        != sum(
            nonspace_len(t)
            for _, t in pages
        )
    ):

        problems.append(
            "parsing integrity check failed "
            "(page text does not add up to the file)"
        )

    inherited = {}

    for col in doc_columns:

        key = RENAME_COLUMNS.get(
            col,
            col,
        )

        if key in RESERVED_KEYS:
            key = f"doc_{key}"

        inherited[key] = meta.get(col)

    missing_core = [
        c
        for c in CORE_FIELDS
        if not meta.get(c)
    ]

    numbers = [
        n
        for n, _
        in pages
    ]

    duplicates = sorted(
        {
            n
            for n, c
            in Counter(numbers).items()
            if c > 1
        }
    )

    present = set(numbers)

    gaps = [
        n
        for n in range(
            1,
            (max(numbers) if numbers else 0) + 1,
        )
        if n not in present
    ]

    records = []
    used_ids = set()

    last_section = None
    last_section_page = None

    for index, (
        page_number,
        page_text,
    ) in enumerate(pages):

        lines = [
            l.strip()
            for l in page_text.split("\n")
            if l.strip()
        ]

        lower = page_text.lower()

        chars = nonspace_len(
            page_text
        )

        analysable = (
            chars >= NEAR_EMPTY_CHARS
            and not HARD_CORRUPTION_RE.search(
                page_text
            )
        )

        (
            headings,
            topics,
            section,
            section_source,
            candidates,
            structural,
        ) = find_sections(lines)

        (
            contains_table,
            table_uncertain,
            numeric_short,
            numeric_share,
        ) = detect_table(
            lines,
            page_text,
        )

        (
            contains_form,
            form_uncertain,
            form_evidence,
        ) = detect_form(
            lines,
            page_text,
        )

        (
            pii_status,
            pii_signals,
            contact_counts,
        ) = detect_pii(
            page_text,
            form_evidence[
                "blank_field_lines"
            ],
            form_evidence[
                "label_only_lines"
            ],
            analysable,
        )

        compliance = [
            p
            for p in COMPLIANCE_PHRASES
            if p in lower
        ]

        non_compliance_chars = nonspace_len(
            "\n".join(
                l
                for l in lines
                if not any(
                    p in l.lower()
                    for p in COMPLIANCE_PHRASES
                )
            )
        )

        language = detect_language(
            page_text
        )

        (
            content_type,
            confidence,
            basis,
            detected,
        ) = classify_content(
            {
                "document_type": meta.get(
                    "document_type"
                ),
                "lower": lower,
                "chars": chars,
                "contains_form": contains_form,
                "form_evidence": form_evidence,
                "contains_table": contains_table,
                "numeric_short": numeric_short,
                "numeric_share": numeric_share,
                "line_count": len(lines),
                "emails": contact_counts.get(
                    "emails",
                    0,
                ),
                "phones": contact_counts.get(
                    "phones",
                    0,
                ),
                "definition_count": len(
                    DEFINITION_RE.findall(
                        page_text
                    )
                ),
                "step_lines": sum(
                    1
                    for l in lines
                    if STEP_RE.match(l)
                ),
                "headings": headings,
                "compliance_phrases": compliance,
                "non_compliance_chars": non_compliance_chars,
            }
        )

        # ---------------------------------------------------------------
        # Review reasons
        # ---------------------------------------------------------------
        reasons = []

        if chars == 0:

            reasons.append(
                "empty_page"
            )

        elif chars < NEAR_EMPTY_CHARS:

            reasons.append(
                "near_empty_page"
            )

        if pii_status == "possible_pii":

            reasons.append(
                "possible_pii"
            )

        if table_uncertain:

            reasons.append(
                "possible_table"
            )

        if form_uncertain:

            reasons.append(
                "possible_form"
            )

        if (
            HARD_CORRUPTION_RE.search(
                page_text
            )
            or len(
                PRIVATE_USE_RE.findall(
                    page_text
                )
            ) >= 20
        ):

            reasons.append(
                "extraction_anomaly"
            )

        if is_ocr_page(
            source_id,
            page_number,
        ):

            reasons.append(
                "ocr_derived_verify_numbers"
            )

        if page_number in duplicates:

            reasons.append(
                "duplicate_page_number"
            )

        if confidence == "low":

            reasons.append(
                "low_confidence_content_type"
            )

        if (
            language == "Unknown"
            and chars >= SUBSTANTIVE_CHARS
        ):

            reasons.append(
                "unknown_language"
            )

        # Soft reasons
        if section is None:

            reasons.append(
                "unknown_section"
            )

        if content_type == "unknown":

            reasons.append(
                "unknown_content_type"
            )

        if content_type == "mixed":

            reasons.append(
                "mixed_content_types"
            )

        if missing_core:

            reasons.append(
                "doc_metadata_missing_"
                + "+".join(missing_core)
            )

        no_signal = (
            section is None
            and not candidates
            and last_section is None
            and content_type == "unknown"
            and chars >= SUBSTANTIVE_CHARS
        )

        if no_signal:

            reasons.append(
                "no_section_and_no_content_type"
            )

        page_id = (
            f"{source_id}-p{page_number}"
        )

        if page_id in used_ids:

            page_id += f"-dup{index}"

        used_ids.add(page_id)

        record = {
            "page_id": page_id,

            "source_id": source_id,

            "page_number": page_number,

            "filename": meta.get(
                "filename"
            ),

            "text_filename": txt_path.name,

            "citation": (
                f"{source_id}, "
                f"page {page_number}"
            ),

            **inherited,

            "language": language,

            "section": section,

            "section_confidence": (
                "medium"
                if section
                else None
            ),

            "section_source": section_source,

            "section_at_page_start": (
                last_section
            ),

            "section_at_page_start_from_page": (
                last_section_page
            ),

            "headings": headings,

            "candidate_headings": candidates,

            "topics": topics,

            "content_type": content_type,

            "content_type_confidence": confidence,

            "content_types_detected": detected,

            "content_type_basis": basis,

            "pii_status": pii_status,

            "pii_signals": pii_signals,

            "contains_table": contains_table,

            "contains_form": contains_form,

            "review_required": any(
                r in HARD_REASONS
                for r in reasons
            ),

            "review_reasons": reasons,

            "keyword_hits": [
                k
                for k, rx
                in KEYWORD_RES
                if rx.search(page_text)
            ],

            "signals": {
                "numeric_short_lines": numeric_short,

                "compliance_phrases": compliance,

                "form_evidence": form_evidence,

                "structural_markers": structural,

                "private_use_char_count": len(
                    PRIVATE_USE_RE.findall(
                        page_text
                    )
                ),

                "ocr_derived": is_ocr_page(
                    source_id,
                    page_number,
                ),
            },

            "char_count": len(page_text),

            "word_count": len(
                page_text.split()
            ),

            "line_count": (
                len(
                    page_text.split("\n")
                )
                if page_text
                else 0
            ),

            "text_hash": hashlib.sha256(
                page_text.encode("utf-8")
            ).hexdigest(),

            "previous_page_id": None,

            "next_page_id": None,

            "schema_version": SCHEMA_VERSION,

            "text": page_text,
        }

        records.append(record)

        if headings or structural:

            last_section = (
                structural[-1]
                if structural and not headings
                else headings[-1]
            )

            last_section_page = page_number

    for a, b in zip(
        records,
        records[1:],
    ):

        a["next_page_id"] = b["page_id"]
        b["previous_page_id"] = a["page_id"]

    plan_in_text, plan_check = crosscheck(
        meta.get("plan_number"),
        Counter(
            PLAN_RE.findall(text)
        ),
        True,
    )

    uin_in_text, uin_check = crosscheck(
        meta.get("uin"),
        Counter(
            UIN_RE.findall(text)
        ),
    )

    def count(pred):
        return sum(
            1
            for r in records
            if pred(r)
        )

    summary = {
        "source_id": source_id,

        "filename": meta.get(
            "filename"
        ),

        "pages_processed": len(
            records
        ),

        "pages_with_unknown_section": count(
            lambda r: r["section"] is None
        ),

        "pages_with_unknown_content_type": count(
            lambda r: r["content_type"] == "unknown"
        ),

        "pages_with_possible_pii": count(
            lambda r: r["pii_status"] == "possible_pii"
        ),

        "pages_with_tables": count(
            lambda r: r["contains_table"]
        ),

        "pages_with_forms": count(
            lambda r: r["contains_form"]
        ),

        "pages_requiring_review": count(
            lambda r: r["review_required"]
        ),

        "missing_page_numbers": ",".join(
            map(str, gaps[:20])
        ),

        "duplicate_page_numbers": ",".join(
            map(str, duplicates)
        ),

        "metadata_plan_number": meta.get(
            "plan_number"
        ),

        "plan_numbers_in_text": plan_in_text,

        "plan_check": plan_check,

        "metadata_uin": meta.get(
            "uin"
        ),

        "uins_in_text": uin_in_text,

        "uin_check": uin_check,

        "missing_core_metadata": "+".join(
            missing_core
        ),

        "parse_problems": " | ".join(
            problems
        ),
    }

    return (
        records,
        summary,
        problems,
    )


# ---------------------------------------------------------------------------
# 11. Main program
# ---------------------------------------------------------------------------
def main():

    if not META_CSV.exists():

        print(
            f"ERROR: metadata file not found: "
            f"{META_CSV}"
        )

        return

    if not NORM_DIR.exists():

        print(
            f"ERROR: normalized folder not found: "
            f"{NORM_DIR}"
        )

        return

    meta_rows, doc_columns, warnings = (
        load_metadata(META_CSV)
    )

    txt_files = sorted(
        NORM_DIR.glob("*.txt")
    )

    (
        mapping,
        unmatched,
        map_warnings,
    ) = map_files_to_metadata(
        txt_files,
        meta_rows,
    )

    warnings += map_warnings

    # Prove at the end that no input file was changed.
    inputs = [
        META_CSV
    ] + txt_files

    hashes_before = {
        p: file_hash(p)
        for p in inputs
    }

    OUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    all_records = []
    summaries = []
    failed = []
    parse_problems = []

    for txt_path in txt_files:

        source_id = mapping.get(
            txt_path
        )

        if source_id is None:
            continue

        try:

            (
                records,
                summary,
                problems,
            ) = build_document(
                txt_path,
                source_id,
                meta_rows[source_id],
                doc_columns,
            )

        except Exception as error:

            failed.append(
                (
                    txt_path.name,
                    str(error),
                )
            )

            continue

        all_records.extend(records)
        summaries.append(summary)

        parse_problems += [
            (
                txt_path.name,
                p,
            )
            for p in problems
        ]

    # -----------------------------------------------------------------------
    # Validate every record before writing.
    # -----------------------------------------------------------------------
    invalid = [
        r["page_id"]
        for r in all_records
        if (
            not isinstance(
                r["page_number"],
                int,
            )
            or not r["source_id"]
            or r["source_id"]
            not in meta_rows
        )
    ]

    ids = Counter(
        r["page_id"]
        for r in all_records
    )

    dup_ids = [
        i
        for i, n in ids.items()
        if n > 1
    ]

    with open(
        RECORDS_JSONL,
        "w",
        encoding="utf-8",
        newline="\n",
    ) as f:

        for record in all_records:

            f.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                )
                + "\n"
            )

    hashes_after = {
        p: file_hash(p)
        for p in inputs
    }

    changed = [
        p.name
        for p in inputs
        if hashes_before[p]
        != hashes_after[p]
    ]

    # -----------------------------------------------------------------------
    # Terminal summary
    # -----------------------------------------------------------------------
    mapped_ids = set(
        mapping.values()
    )

    meta_without_txt = sorted(
        set(meta_rows)
        - mapped_ids
    )

    total = len(all_records)

    print("=" * 66)
    print("PAGE STRUCTURING SUMMARY")
    print("=" * 66)

    print(
        f"Metadata rows (documents):          "
        f"{len(meta_rows)}"
    )

    print(
        f"Normalized files found:             "
        f"{len(txt_files)}"
    )

    print(
        f"Files mapped to a source_id:        "
        f"{len(mapping)}"
    )

    print(
        f"Files missing metadata:             "
        f"{len(unmatched)}"
    )

    print(
        f"Total pages processed:              "
        f"{total}"
    )

    print(
        f"Page records created:               "
        f"{total}"
    )

    if unmatched:

        print(
            "\nERROR - text files with NO "
            "metadata row "
            "(NOT included in the output):"
        )

        for name in unmatched:

            print(
                f"   - {name}"
            )

    if meta_without_txt:

        print(
            "\nERROR - metadata rows with NO "
            "normalized text file:"
        )

        for sid in meta_without_txt:

            print(
                f"   - {sid}"
            )

    for name, message in failed:

        print(
            f"\nPARSING ERROR: "
            f"{name}: {message}"
        )

    for name, problem in parse_problems:

        print(
            f"PARSE WARNING: "
            f"{name}: {problem}"
        )

    for w in warnings:

        print(
            f"WARNING: {w}"
        )

    if invalid:

        print(
            "\nVALIDATION ERROR: "
            "records without a valid "
            f"page_number/source_id: "
            f"{invalid[:10]}"
        )

    if dup_ids:

        print(
            "\nVALIDATION ERROR: "
            f"duplicate page_ids: "
            f"{dup_ids[:10]}"
        )

    def pct(n):

        return (
            f"{n} ({n / total:.0%})"
            if total
            else "0"
        )

    print(
        "\nPages with unknown section:        "
        f"{pct(sum(1 for r in all_records if r['section'] is None))}"
    )

    print(
        "Pages by content type:",
        dict(
            Counter(
                r["content_type"]
                for r in all_records
            )
        ),
    )

    print(
        "Pages by language:    ",
        dict(
            Counter(
                r["language"]
                for r in all_records
            )
        ),
    )

    print(
        "Pages by PII status:  ",
        dict(
            Counter(
                r["pii_status"]
                for r in all_records
            )
        ),
    )

    print(
        "Pages with tables:                  "
        f"{sum(1 for r in all_records if r['contains_table'])}"
    )

    print(
        "Pages with forms:                   "
        f"{sum(1 for r in all_records if r['contains_form'])}"
    )

    print(
        "Pages with possible PII:            "
        f"{sum(1 for r in all_records if r['pii_status'] == 'possible_pii')}"
    )

    print(
        "Pages requiring review:             "
        f"{pct(sum(1 for r in all_records if r['review_required']))}"
    )

    reason_counts = Counter(
        (
            "doc_metadata_missing"
            if x.startswith(
                "doc_metadata_missing"
            )
            else x
        )
        for r in all_records
        for x in r["review_reasons"]
    )

    print(
        "Review reasons (all, incl. soft):  ",
        dict(reason_counts),
    )

    null_counts = {
        c: sum(
            1
            for r in meta_rows.values()
            if r.get(c) is None
        )
        for c in doc_columns
    }

    null_counts = {
        c: n
        for c, n in null_counts.items()
        if n
    }

    print(
        "Empty metadata values (documents):",
        (
            null_counts
            if null_counts
            else "none"
        ),
    )

    print(
        "\nMetadata vs text cross-check "
        "(plan number / UIN):"
    )

    bad = (
        "METADATA_NOT_FOUND_IN_TEXT",
        "ok_but_other_values_in_text",
        "metadata_empty_but_text_has_values",
    )

    flagged = [
        s
        for s in summaries
        if (
            s["plan_check"] in bad
            or s["uin_check"] in bad
            or s["missing_page_numbers"]
            or s["duplicate_page_numbers"]
        )
    ]

    if not flagged:

        print(
            "   no differences found"
        )

    for s in flagged:

        print(
            f"   - {s['source_id']}: "
            f"plan {s['metadata_plan_number']} "
            f"vs text [{s['plan_numbers_in_text']}] "
            f"-> {s['plan_check']}; "
            f"UIN {s['metadata_uin']} "
            f"vs text [{s['uins_in_text']}] "
            f"-> {s['uin_check']}"
            + (
                f"; missing pages "
                f"{s['missing_page_numbers']}"
                if s["missing_page_numbers"]
                else ""
            )
            + (
                f"; duplicate pages "
                f"{s['duplicate_page_numbers']}"
                if s["duplicate_page_numbers"]
                else ""
            )
        )

    print(
        "\nInput files unchanged:              "
        f"{'YES' if not changed else 'NO - ' + str(changed)}"
    )

    print(
        f"Page records:   {RECORDS_JSONL}"
    )


if __name__ == "__main__":
    main()