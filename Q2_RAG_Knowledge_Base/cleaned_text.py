
import csv
import math
import re
import sys
from collections import Counter
from pathlib import Path
 
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
 
 
# ---------------------------------------------------------------------------
# 1. Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "Data" / "processed" / "raw_text"
CLEAN_DIR = BASE_DIR / "Data" / "processed" / "cleaned"
LOG_CSV = CLEAN_DIR / "cleaning_log.csv"
SUMMARY_CSV = CLEAN_DIR / "cleaning_summary.csv"
 
 
# ---------------------------------------------------------------------------
# 2. Settings (all deliberately cautious - raise a number to be MORE cautious)
# ---------------------------------------------------------------------------
MIN_LINES_FOR_EDGE_ANALYSIS = 6   # pages with fewer text lines are never touched
BANNER_MIN_PAGES = 4              # a banner must repeat on at least this many pages
BANNER_MIN_SHARE = 0.60           # ...and on at least 60% of the analysed pages
BANNER_MAX_CHARS = 60             # banners are short
BANNER_MAX_WORDS = 8
WEAK_REPEAT_MIN_SHARE = 0.25      # repeated but below 60%: not removed, only flagged
 
PAGE_NUMBER_MIN_PAGES = 3         # a page-number pattern must match on >= 3 pages
PAGE_NUMBER_MIN_SHARE = 0.30      # ...and on >= 30% of the pages
 
MAX_FLAGS_PER_KIND = 25           # keeps the log readable
NEAR_EMPTY_CHARS = 20
FLAG_TEXT_LIMIT = 300
 
# Meaningful headings are NEVER removed as banners (lower case).
PROTECTED_HEADINGS = {
    "death benefit", "survival benefit", "maturity benefit", "guaranteed additions",
    "premium payment", "grace period", "revival", "surrender", "policy loan",
    "free look period", "exclusions", "eligibility", "benefits", "definitions",
    "nomination", "assignment", "riders", "claims", "lapse", "paid-up",
}
 
# A repeated line containing any of these is treated as possible legal/compliance
# text and is KEPT (and flagged), never removed.
COMPLIANCE_WORDS = (
    "insurance", "insurer", "solicit", "irda", "regulat", "warning", "disclaim",
    "caution", "fraud", "rebate", "grievance", "ombudsman", "terms", "condition",
    "applicable", "liable", "claim", "mis-sell", "misleading", "prohibit",
    "penalt", "risk", "tax",
)
 
# Pure brand lines that are safe to remove even though they contain "insurance".
# Add your own exact brand lines here (lower case).
BRAND_WHITELIST = {"life insurance corporation of india", "lic of india", "lic"}
 
 
# ---------------------------------------------------------------------------
# 3. Patterns
# ---------------------------------------------------------------------------
MARKER_RE = re.compile(r"^--- PAGE (\d+) ---$")
# "Page 7", "Page 7 of 40", "- 7 -"   (the whole line, nothing else)
LABELLED_PAGE_RE = re.compile(
    r"^(?:page\s+\d{1,4}(?:\s+of\s+\d{1,4})?|[-\u2013\u2014]\s*\d{1,4}\s*[-\u2013\u2014])$",
    re.IGNORECASE,
)
BARE_NUMBER_RE = re.compile(r"^\d{1,4}$")
# A line made only of digits and number punctuation looks like table values
NUMERIC_LINE_RE = re.compile(r"^[\d\s,.%\u20b9/\-\u2013:()]+$")
# Broken-font symbols, private-use characters, "(cid:123)" codes
BROKEN_CHAR_RE = re.compile(r"[\ufffd\ue000-\uf8ff]|\(cid:\d+\)")
# Letters O / I / l glued to digits, e.g. "1O5" or "l05" (possible OCR confusion)
OCR_CONFUSION_RE = re.compile(r"\b\d+[OIl]\d*\b|\b[OIl]\d+\b")
 
 
# ---------------------------------------------------------------------------
# 4. Small helpers
# ---------------------------------------------------------------------------
def squash(text):
    """Collapse inner whitespace so comparisons ignore spacing differences."""
    return " ".join(text.split())
 
 
def non_empty_indices(lines):
    """Positions of lines that still exist (not None) and contain text."""
    return [i for i, line in enumerate(lines) if line is not None and line.strip()]
 
 
def non_space_counter(text):
    """Count every non-whitespace character (used for the safety check)."""
    return Counter(c for c in text if not c.isspace())
 
 
def add_event(events, page, action, reason, text):
    events.append({"page": page, "action": action, "reason": reason, "text": text})
 
 
# ---------------------------------------------------------------------------
# 5. Split a raw file into pages (markers are kept exactly as they are)
# ---------------------------------------------------------------------------
def parse_pages(text):
    """
    Return a list of pages. Each page is a dict:
        {"number": 7, "marker": "--- PAGE 7 ---", "lines": [...]}
    Text before the first marker (normally none) is kept as a page with number None.
    """
    pages = []
    current = {"number": None, "marker": None, "lines": []}
    for line in text.split("\n"):   # split on \n only, so no other characters are touched
        match = MARKER_RE.match(line.rstrip())
        if match:
            pages.append(current)
            current = {"number": int(match.group(1)), "marker": line.rstrip(), "lines": []}
        else:
            current["lines"].append(line)
    pages.append(current)
 
    # Drop an empty "before the first marker" block
    if pages[0]["number"] is None and not any(l.strip() for l in pages[0]["lines"]):
        pages = pages[1:]
    return pages
 
 
# ---------------------------------------------------------------------------
# 6. Repeated header/footer banners (very conservative)
# ---------------------------------------------------------------------------
def edge_groups(lines):
    """The first two and last two text lines of a page (where headers/footers live)."""
    idx = non_empty_indices(lines)
    if len(idx) < MIN_LINES_FOR_EDGE_ANALYSIS:
        return None
    return {"top": idx[:2], "bottom": idx[-2:]}
 
 
def banner_verdict(text):
    """Decide if a repeated line may be removed. Returns (ok, reason_if_not)."""
    low = text.lower().strip(" .,:;-\u2013\u2014\u00ae\u2122")
    if len(text) > BANNER_MAX_CHARS:
        return False, "line is long"
    if len(text.split()) > BANNER_MAX_WORDS:
        return False, "too many words"
    if text.endswith((".", ":", ";", ",")):
        return False, "looks like a sentence or label"
    if any(ch.isdigit() for ch in text):
        return False, "contains digits (could be a plan number / UIN)"
    if low in PROTECTED_HEADINGS:
        return False, "protected heading"
    if low in BRAND_WHITELIST:
        return True, ""
    if any(word in low for word in COMPLIANCE_WORDS):
        return False, "possible compliance/legal wording"
    return True, ""
 
 
def remove_repeated_banners(pages, events):
    """Remove only short, identical, brand-like lines repeated at the page edges."""
    numbered = [i for i, p in enumerate(pages) if p["number"] is not None]
    if not numbered:
        return
 
    # Count on how many pages each (position, line) appears
    counts = Counter()
    eligible = []
    for i in numbered:
        lines = pages[i]["lines"]
        groups = edge_groups(lines)
        if groups is None:
            continue
        eligible.append(i)
        seen = {(g, squash(lines[j])) for g, idxs in groups.items() for j in idxs}
        counts.update(seen)
 
    n = len(eligible)
    if n == 0:
        return
    need = max(BANNER_MIN_PAGES, math.ceil(BANNER_MIN_SHARE * n))
    weak_need = max(BANNER_MIN_PAGES, math.ceil(WEAK_REPEAT_MIN_SHARE * n))
 
    approved, kept = {}, []
    for key, count in counts.most_common():
        group, text = key
        if count >= need:
            ok, why = banner_verdict(text)
            if ok:
                approved[key] = count
            else:
                kept.append((key, count, why))
        elif count >= weak_need:
            kept.append((key, count, f"below {int(BANNER_MIN_SHARE * 100)}% of pages"))
 
    # Remove approved banners, but never on the first page (title / cover page)
    first_page = numbered[0]
    for i in eligible:
        if i == first_page:
            continue
        lines = pages[i]["lines"]
        for group, idxs in edge_groups(lines).items():
            for j in idxs:
                key = (group, squash(lines[j]))
                if key in approved:
                    add_event(events, pages[i]["number"], "REMOVE",
                              f"repeated_{group}_banner (same line on {approved[key]} of {n} pages)",
                              lines[j].rstrip())
                    lines[j] = None
 
    # Flag repeated lines we chose to KEEP, so a human can review them
    for key, count, why in kept[:MAX_FLAGS_PER_KIND]:
        group, text = key
        add_event(events, "ALL", "FLAG",
                  f"repeated_line_kept ({group}, {count} of {n} pages): {why}", text)
 
 
# ---------------------------------------------------------------------------
# 7. Page numbers (only with strong evidence)
# ---------------------------------------------------------------------------
def remove_page_numbers(pages, events):
    """
    Rule A - labelled: a line that is ONLY "Page 7", "Page 7 of 40" or "- 7 -" and sits
             at the very top or very bottom of a page.
    Rule B - bare number: a line that is ONLY digits, at the very top or very bottom of
             the page, where the number minus the PDF page number is the SAME on many
             pages (e.g. printed 9 on PDF page 7 -> offset 2). The most common offset
             must appear on >= 3 pages and >= 30% of pages. A number is also never
             a candidate if the neighbouring line is numeric (looks like table values).
    Anything else is kept. Returns the offsets found (also useful as page metadata).
    """
    numbered = [i for i, p in enumerate(pages) if p["number"] is not None]
    offsets_found = {}
 
    # --- Rule A: labelled page numbers ---
    for i in numbered:
        lines = pages[i]["lines"]
        idx = non_empty_indices(lines)
        if not idx:
            continue
        for position, j in (("top", idx[0]), ("bottom", idx[-1])):
            if lines[j] is not None and LABELLED_PAGE_RE.match(squash(lines[j])):
                add_event(events, pages[i]["number"], "REMOVE",
                          f"page_number_labelled ({position})", lines[j].rstrip())
                lines[j] = None
 
    # --- Rule B: bare numbers following the page sequence ---
    candidates = {"top": [], "bottom": []}   # (page index, line index, offset)
    for i in numbered:
        lines = pages[i]["lines"]
        idx = non_empty_indices(lines)
        if not idx:
            continue
        for position, k, neighbour in (("top", 0, 1), ("bottom", -1, -2)):
            if position == "top" and len(idx) == 1:
                continue    # a one-line page is handled as "bottom" only
            j = idx[k]
            text = squash(lines[j])
            if not BARE_NUMBER_RE.match(text):
                continue
            if len(idx) >= 2 and NUMERIC_LINE_RE.match(squash(lines[idx[neighbour]])):
                continue    # surrounded by numbers: probably a table
            candidates[position].append((i, j, int(text) - pages[i]["number"]))
 
    need = max(PAGE_NUMBER_MIN_PAGES, math.ceil(PAGE_NUMBER_MIN_SHARE * len(numbered)))
    for position in ("top", "bottom"):
        offsets = Counter(offset for _, _, offset in candidates[position])
        if not offsets:
            continue
        best, count = offsets.most_common(1)[0]
        if count < need:
            continue
        offsets_found[position] = best
        for i, j, offset in candidates[position]:
            lines = pages[i]["lines"]
            if offset == best:
                add_event(events, pages[i]["number"], "REMOVE",
                          f"page_number_sequence ({position}, offset {best:+d}, "
                          f"matches {count} of {len(numbered)} pages)", lines[j].rstrip())
                lines[j] = None
            elif abs(offset - best) <= 2:
                add_event(events, pages[i]["number"], "FLAG",
                          f"bare_number_near_page_sequence_kept ({position}, offset "
                          f"{offset:+d} vs document offset {best:+d})", lines[j].rstrip())
    return offsets_found
 
 
# ---------------------------------------------------------------------------
# 8. Flags for things that look suspicious (never changed, only recorded)
# ---------------------------------------------------------------------------
def flag_suspicious(pages, events):
    numbered = [p for p in pages if p["number"] is not None]
 
    # Page markers should run 1, 2, 3 ...
    numbers = [p["number"] for p in numbered]
    if numbers != list(range(1, len(numbers) + 1)):
        add_event(events, "FILE", "FLAG", "page_markers_not_sequential",
                  str(numbers[:12]))
 
    broken_count = ocr_count = 0
    for page in numbered:
        for line in page["lines"]:
            if line is None or not line.strip():
                continue
            if BROKEN_CHAR_RE.search(line) and broken_count < MAX_FLAGS_PER_KIND:
                add_event(events, page["number"], "FLAG",
                          "possible_extraction_corruption (broken-font symbols)",
                          line.strip()[:FLAG_TEXT_LIMIT])
                broken_count += 1
            if OCR_CONFUSION_RE.search(line) and ocr_count < MAX_FLAGS_PER_KIND:
                found = ", ".join(OCR_CONFUSION_RE.findall(line)[:5])
                add_event(events, page["number"], "FLAG",
                          f"possible_ocr_digit_confusion ({found})",
                          line.strip()[:FLAG_TEXT_LIMIT])
                ocr_count += 1
 
 
# ---------------------------------------------------------------------------
# 9. Whitespace tidy-up (safe formatting only)
# ---------------------------------------------------------------------------
def tidy_whitespace(lines):
    """
    * drops lines already removed (None)
    * trims trailing whitespace (leading spaces are kept: they can show structure)
    * whitespace-only lines become empty lines
    * several blank lines in a row become ONE blank line
    * blank lines at the start/end of a page are dropped
    Returns (new_lines, number_of_lines_with_trailing_whitespace_trimmed).
    """
    trimmed = 0
    out = []
    previous_blank = False
    for line in lines:
        if line is None:
            continue
        stripped = line.rstrip()
        if stripped != line:
            trimmed += 1
        if not stripped:
            if not previous_blank:
                out.append("")
            previous_blank = True
        else:
            out.append(stripped)
            previous_blank = False
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return out, trimmed
 
 
# ---------------------------------------------------------------------------
# 10. Clean one file
# ---------------------------------------------------------------------------
def clean_file(raw_path):
    """Return (cleaned_text, events, summary_row) for one raw .txt file."""
    raw_text = raw_path.read_text(encoding="utf-8")   # strict: errors are reported, not hidden
    pages = parse_pages(raw_text)
    events = []
 
    remove_repeated_banners(pages, events)
    offsets = remove_page_numbers(pages, events)
    flag_suspicious(pages, events)
 
    trimmed_total = 0
    for page in pages:
        page["lines"], trimmed = tidy_whitespace(page["lines"])
        trimmed_total += trimmed
 
    # Near-empty pages are flagged (kept as they are)
    for page in pages:
        if page["number"] is None:
            continue
        body = "\n".join(page["lines"])
        if len("".join(body.split())) < NEAR_EMPTY_CHARS:
            add_event(events, page["number"], "FLAG", "near_empty_page", body[:FLAG_TEXT_LIMIT])
 
    # Put the file back together in the same layout as the raw files
    parts = []
    for page in pages:
        body = "\n".join(page["lines"])
        if page["marker"] is None:
            parts.append(body)
        else:
            parts.append(f"{page['marker']}\n{body}\n")
    cleaned_text = "\n".join(parts)
    if not cleaned_text.endswith("\n"):
        cleaned_text += "\n"
 
    # Safety net: raw characters must equal cleaned characters + logged removals
    removed_text = "".join(e["text"] for e in events if e["action"] == "REMOVE")
    integrity = (non_space_counter(raw_text)
                 == non_space_counter(cleaned_text) + non_space_counter(removed_text))
 
    removals = sum(1 for e in events if e["action"] == "REMOVE")
    flags = sum(1 for e in events if e["action"] == "FLAG")
    raw_blank = sum(1 for l in raw_text.split("\n") if not l.strip())
    clean_blank = sum(1 for l in cleaned_text.split("\n") if not l.strip())
 
    summary = {
        "source_file": raw_path.name,
        "pages": sum(1 for p in pages if p["number"] is not None),
        "chars_raw": len(raw_text),
        "chars_cleaned": len(cleaned_text),
        "lines_removed": removals,
        "flags": flags,
        "trailing_space_lines_trimmed": trimmed_total,
        "blank_lines_removed": max(raw_blank - clean_blank, 0),
        "page_number_offset_top": offsets.get("top", ""),
        "page_number_offset_bottom": offsets.get("bottom", ""),
        "integrity_check": "OK" if integrity else "MISMATCH",
    }
    return cleaned_text, events, summary
 
 
# ---------------------------------------------------------------------------
# 11. Main program
# ---------------------------------------------------------------------------
def main():
    if not RAW_DIR.exists():
        print(f"ERROR: raw text folder not found: {RAW_DIR}")
        return
 
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    raw_files = sorted(RAW_DIR.glob("*.txt"))
    print(f"Found {len(raw_files)} raw text file(s) in {RAW_DIR}\n")
 
    log_rows, summaries, failed = [], [], []
    files_written = 0
 
    for raw_path in raw_files:
        try:
            cleaned_text, events, summary = clean_file(raw_path)
        except Exception as error:
            print(f"{raw_path.name}: FAILED ({error})")
            failed.append((raw_path.name, str(error)))
            continue
 
        # newline="\n" keeps the same line endings on Windows
        with open(CLEAN_DIR / raw_path.name, "w", encoding="utf-8", newline="\n") as f:
            f.write(cleaned_text)
        files_written += 1
        summaries.append(summary)
 
        for e in events:
            log_rows.append({
                "source_file": raw_path.name, "page_number": e["page"],
                "action": e["action"], "reason": e["reason"], "removed_text": e["text"],
            })
 
        warn = "" if summary["integrity_check"] == "OK" else "   <-- INTEGRITY MISMATCH"
        print(f"{raw_path.name}: {summary['pages']} pages, "
              f"{summary['lines_removed']} removed, {summary['flags']} flagged{warn}")
 
    # --- Write the log and the summary ---
    log_fields = ["source_file", "page_number", "action", "reason", "removed_text"]
    with open(LOG_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=log_fields)
        writer.writeheader()
        writer.writerows(log_rows)
 
    if summaries:
        with open(SUMMARY_CSV, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(summaries[0].keys()))
            writer.writeheader()
            writer.writerows(summaries)
 
    # --- Final summary ---
    removed_rows = [r for r in log_rows if r["action"] == "REMOVE"]
    flag_rows = [r for r in log_rows if r["action"] == "FLAG"]
    files_with_removals = sorted({r["source_file"] for r in removed_rows})
    mismatches = [s["source_file"] for s in summaries if s["integrity_check"] != "OK"]
 
    print("\n" + "=" * 60)
    print("CLEANING SUMMARY")
    print("=" * 60)
    print(f"Input files:               {len(raw_files)}")
    print(f"Output files written:      {files_written}")
    print(f"Pages processed:           {sum(s['pages'] for s in summaries)}")
    print(f"Lines removed (logged):    {len(removed_rows)}")
    print(f"Items flagged for review:  {len(flag_rows)}")
    print(f"Files with removals:       {len(files_with_removals)}")
    for name in files_with_removals:
        count = sum(1 for r in removed_rows if r["source_file"] == name)
        print(f"    - {name}  ({count})")
    print(f"Integrity mismatches:      {len(mismatches)}")
    for name in mismatches:
        print(f"    - {name}   <-- investigate before using this file")
    if failed:
        print(f"Failed files:              {len(failed)}")
        for name, message in failed:
            print(f"    - {name}: {message}")
    print(f"\nCleaned files folder: {CLEAN_DIR}")
    print(f"Cleaning log:         {LOG_CSV}")
    print(f"Per-file summary:     {SUMMARY_CSV}")
 
 
if __name__ == "__main__":
    main()