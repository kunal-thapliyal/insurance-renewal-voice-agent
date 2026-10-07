
import csv
import hashlib
import re
import sys
from itertools import combinations
from pathlib import Path
 
try:
    import pymupdf
except ImportError:
    import fitz as pymupdf
 
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
 
 
# ---------------------------------------------------------------------------
# 1. Settings (you can change the thresholds)
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "Data" / "raw" / "PDF"
TXT_DIR = BASE_DIR / "Data" / "processed" / "raw_text"
REPORT_CSV = BASE_DIR / "Data" / "processed" / "extraction_report.csv"
 
OCR_FILE = "lic 002 payment by chequedemand draft.pdf"   # lower case
 
EMPTY_PAGE_CHARS = 20        # a page with fewer characters counts as "empty"
LOW_TOTAL_CHARS = 500        # whole file with fewer characters = very low text
LOW_AVG_CHARS_PER_PAGE = 300 # average below this = suspiciously thin
BAD_SYMBOL_RATIO = 0.01      # >1% broken-font symbols = possible corruption
LATIN1_RATIO = 0.05          # >5% accented-Latin symbols = possible Hindi mojibake
NEAR_DUPLICATE = 0.90        # word-overlap score for "near-duplicate"
HEAVY_OVERLAP = 0.50         # word-overlap score worth knowing about
 
PAGE_MARKER = re.compile(r"^--- PAGE (\d+) ---$", re.MULTILINE)
 
 
# ---------------------------------------------------------------------------
# 2. Helpers
# ---------------------------------------------------------------------------
def split_pages(text):
    """Split a .txt into (marker_numbers, page_texts) using the page markers."""
    matches = list(PAGE_MARKER.finditer(text))
    numbers = [int(m.group(1)) for m in matches]
    pages = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        pages.append(text[m.end():end].strip())
    return numbers, pages
 
 
def squash(text):
    """Collapse all whitespace so tiny spacing differences don't matter."""
    return " ".join(text.split())
 
 
def count_chars(ch_test, text):
    return sum(1 for c in text if ch_test(c))
 
 
def is_devanagari(c):
    return "\u0900" <= c <= "\u097F"
 
 
def is_bad_symbol(c):
    # U+FFFD = replacement box; U+E000-U+F8FF = private-use symbols (broken fonts)
    return c == "\ufffd" or "\ue000" <= c <= "\uf8ff"
 
 
def is_latin1_accent(c):
    # Characters like Ã ¤ ¥ that show up when Hindi is decoded wrongly
    return "\u0080" <= c <= "\u00ff"
 
 
def count_images_per_page(pdf_path):
    """Return (page_count, list of image counts per page) for a PDF."""
    with pymupdf.open(str(pdf_path)) as doc:
        counts = [len(page.get_images(full=True)) for page in doc]
        return doc.page_count, counts
 
 
def shingles(text, size=6):
    """Set of hashed 6-word sequences, used to compare documents."""
    words = text.split()
    return {hash(" ".join(words[i:i + size])) for i in range(max(len(words) - size + 1, 0))}
 
 
# ---------------------------------------------------------------------------
# 3. Check one file
# ---------------------------------------------------------------------------
def check_file(pdf_path):
    """Return a dictionary describing the health of one PDF's extracted text."""
    row = {
        "file": pdf_path.name, "pdf_pages": "", "marker_pages": "", "markers_ok": "",
        "chars": 0, "empty_pages": "", "image_only_pages": "", "hindi_chars": 0,
        "status": "", "notes": "",
    }
    notes = []
    txt_path = TXT_DIR / (pdf_path.stem + ".txt")
 
    # --- PDF page and image info ---
    try:
        pdf_pages, image_counts = count_images_per_page(pdf_path)
    except Exception as error:
        row["status"] = "PDF UNREADABLE"
        row["notes"] = str(error)
        return row, ""
    row["pdf_pages"] = pdf_pages
 
    # --- Does the .txt exist? ---
    if not txt_path.exists():
        row["status"] = "MISSING TXT"
        row["notes"] = "no matching .txt file in raw_text"
        return row, ""
 
    text = txt_path.read_text(encoding="utf-8", errors="replace")
    numbers, pages = split_pages(text)
    row["marker_pages"] = len(numbers)
 
    # --- Page boundaries ---
    markers_ok = numbers == list(range(1, len(numbers) + 1)) and len(numbers) == pdf_pages
    row["markers_ok"] = "yes" if markers_ok else "NO"
    if not markers_ok:
        notes.append(f"page markers wrong: PDF has {pdf_pages} pages, "
                     f"txt has markers {numbers[:8]}{'...' if len(numbers) > 8 else ''}")
 
    # --- Amount of text ---
    body = "".join(pages)
    visible = [c for c in body if not c.isspace()]
    row["chars"] = len(visible)
    avg = len(visible) / pdf_pages if pdf_pages else 0
    needs_ocr = False
 
    is_ocr_file = pdf_path.name.lower() == OCR_FILE
 
    if len(visible) == 0:
        if any(image_counts):
            notes.append("ZERO text extracted but the PDF contains images - needs OCR")
            needs_ocr = True
        else:
            notes.append("ZERO text and no images - the PDF looks blank")
    elif is_ocr_file:
        # OCR output is naturally short; it just needs a human comparison
        notes.append(f"OCR output ({len(visible)} chars) - compare with the PDF by eye")
    elif len(visible) < LOW_TOTAL_CHARS:
        notes.append(f"very low text ({len(visible)} chars)")
    elif avg < LOW_AVG_CHARS_PER_PAGE:
        notes.append(f"thin text (average {avg:.0f} chars per page)")
 
    # --- Empty and image-only pages ---
    empty = [i + 1 for i, p in enumerate(pages) if len(p) < EMPTY_PAGE_CHARS]
    image_only = [n for n in empty if n <= len(image_counts) and image_counts[n - 1] > 0]
    row["empty_pages"] = ",".join(map(str, empty)) if empty else ""
    row["image_only_pages"] = ",".join(map(str, image_only)) if image_only else ""
    if empty:
        shown = empty[:10]
        notes.append(f"{len(empty)} empty page(s): {shown}{'...' if len(empty) > 10 else ''}")
    if image_only:
        notes.append(f"{len(image_only)} possible image-only page(s): {image_only[:10]}")
        if len(image_only) >= max(1, pdf_pages // 2):
            needs_ocr = True
 
    # --- Possible corruption ---
    if visible:
        bad = count_chars(is_bad_symbol, body)
        if "(cid:" in body or bad / len(visible) > BAD_SYMBOL_RATIO:
            notes.append("POSSIBLE CORRUPTION: broken-font symbols found")
        hindi = count_chars(is_devanagari, body)
        row["hindi_chars"] = hindi
        accents = count_chars(is_latin1_accent, body)
        if accents / len(visible) > LATIN1_RATIO:
            notes.append("POSSIBLE MOJIBAKE: many accented-Latin symbols "
                         "(Hindi may be decoded wrongly) - inspect by eye")
        if hindi:
            notes.append(f"contains Hindi ({hindi} Devanagari chars) - read a sample by eye")
 
    # --- Repeated identical pages inside one file ---
    seen = {}
    for i, p in enumerate(pages, start=1):
        if len(p) > 200:
            h = hashlib.sha256(squash(p).encode("utf-8")).hexdigest()
            seen.setdefault(h, []).append(i)
    repeated = [v for v in seen.values() if len(v) > 1]
    if repeated:
        notes.append(f"identical repeated pages: {repeated[:3]}")
 
    # --- Final status ---
    serious = (not markers_ok) or needs_ocr or any(
        n.startswith(("POSSIBLE CORRUPTION", "POSSIBLE MOJIBAKE", "ZERO")) for n in notes
    )
    if needs_ocr:
        row["status"] = "NEEDS OCR?"
    elif serious:
        row["status"] = "REVIEW"
    elif any(not n.startswith("contains Hindi") for n in notes):
        row["status"] = "CHECK"
    else:
        row["status"] = "OK"
    row["notes"] = " | ".join(notes)
    return row, body
 
 
# ---------------------------------------------------------------------------
# 4. Main program
# ---------------------------------------------------------------------------
def main():
    if not PDF_DIR.exists():
        print(f"ERROR: PDF folder not found: {PDF_DIR}")
        return
 
    pdf_files = sorted(p for p in PDF_DIR.iterdir()
                       if p.is_file() and p.suffix.lower() == ".pdf")
    print(f"Validating {len(pdf_files)} PDF(s)...\n")
 
    rows = []
    bodies = {}
    for pdf_path in pdf_files:
        row, body = check_file(pdf_path)
        rows.append(row)
        if body.strip():
            bodies[pdf_path.name] = squash(body)
 
    # --- Orphan .txt files (text with no PDF) ---
    pdf_stems = {p.stem for p in pdf_files}
    orphans = [t.name for t in sorted(TXT_DIR.glob("*.txt")) if t.stem not in pdf_stems] \
        if TXT_DIR.exists() else []
 
    # --- Duplicate and overlap checks between files ---
    exact = {}
    for name, text in bodies.items():
        exact.setdefault(hashlib.sha256(text.encode("utf-8")).hexdigest(), []).append(name)
    exact_groups = [v for v in exact.values() if len(v) > 1]
 
    near, overlap = [], []
    sets = {name: shingles(text) for name, text in bodies.items()}
    for a, b in combinations(sorted(sets), 2):
        sa, sb = sets[a], sets[b]
        if not sa or not sb:
            continue
        score = len(sa & sb) / min(len(sa), len(sb))   # shared share of the smaller doc
        if score >= NEAR_DUPLICATE:
            near.append((a, b, score))
        elif score >= HEAVY_OVERLAP:
            overlap.append((a, b, score))
 
    # --- Print table ---
    print(f"{'STATUS':<12}{'PDF pg':>7}{'marks':>7}{'ok?':>5}{'chars':>9}  FILE")
    print("-" * 78)
    for r in rows:
        print(f"{r['status']:<12}{str(r['pdf_pages']):>7}{str(r['marker_pages']):>7}"
              f"{str(r['markers_ok']):>5}{r['chars']:>9}  {r['file']}")
 
    # --- Print details ---
    print("\nDETAILS (only files with notes)")
    print("-" * 78)
    for r in rows:
        if r["notes"]:
            print(f"* {r['file']}  [{r['status']}]")
            for n in r["notes"].split(" | "):
                print(f"     - {n}")
 
    print("\nCROSS-FILE CHECKS")
    print("-" * 78)
    print("Exact duplicate files:", exact_groups if exact_groups else "none")
    print("Near-duplicates (>=90% shared):",
          [(a, b, f"{s:.0%}") for a, b, s in near] if near else "none")
    print("Heavy overlap (50-90% shared, often normal e.g. brochure vs policy document):")
    for a, b, s in overlap:
        print(f"     {s:.0%}  {a}  <->  {b}")
    if not overlap:
        print("     none")
    print("Orphan .txt files (no matching PDF):", orphans if orphans else "none")
 
    # --- Overall counts ---
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("\nSUMMARY:", ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
 
    # --- Save CSV ---
    REPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Report saved: {REPORT_CSV}")
 
 
if __name__ == "__main__":
    main()