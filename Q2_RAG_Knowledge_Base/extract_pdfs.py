
import sys
from pathlib import Path
 
# Newer PyMuPDF versions use "import pymupdf"; older ones use "import fitz".
try:
    import pymupdf
except ImportError:
    import fitz as pymupdf
 
 
# ---------------------------------------------------------------------------
# 0. Make console printing safe on Windows (does not affect the saved files)
# ---------------------------------------------------------------------------
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
 
 
# ---------------------------------------------------------------------------
# 1. Settings
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "Data" / "raw" / "PDF"
OUTPUT_DIR = BASE_DIR / "Data" / "processed" / "raw_text"
 
# Files handled by a different script (OCR). Compared in lower case.
SKIP_FILES = {"lic 002 payment by chequedemand draft.pdf"}
 
 
# ---------------------------------------------------------------------------
# 2. Extract one PDF -> list of page texts
# ---------------------------------------------------------------------------
def extract_pages(pdf_path):
    """Return (page_texts, page_errors) for one PDF. Text is kept as extracted."""
    page_texts = []
    page_errors = []
 
    with pymupdf.open(str(pdf_path)) as document:
        # Some PDFs are locked with an empty password; try to open them
        if document.needs_pass:
            if not document.authenticate(""):
                raise ValueError("PDF is password protected")
 
        for page_number, page in enumerate(document, start=1):
            try:
                text = page.get_text("text")
            except Exception as error:
                # One bad page should not lose the whole document
                text = ""
                page_errors.append((page_number, str(error)))
            page_texts.append(text)
 
    return page_texts, page_errors
 
 
# ---------------------------------------------------------------------------
# 3. Save the text file (UTF-8, with page markers)
# ---------------------------------------------------------------------------
def write_text_file(output_path, page_texts):
    """Write all pages to one .txt file using '--- PAGE n ---' markers."""
    parts = []
    for page_number, text in enumerate(page_texts, start=1):
        parts.append(f"--- PAGE {page_number} ---\n{text}\n")
    content = "\n".join(parts)
 
    try:
        with open(output_path, "w", encoding="utf-8") as f:   # "w" = overwrite
            f.write(content)
    except UnicodeEncodeError:
        # Very rare invalid character: save anyway, written as an escape code
        with open(output_path, "w", encoding="utf-8", errors="backslashreplace") as f:
            f.write(content)
        print("    note: some invalid characters were saved as \\uXXXX codes")
 
 
# ---------------------------------------------------------------------------
# 4. Main program
# ---------------------------------------------------------------------------
def main():
    if not INPUT_DIR.exists():
        print(f"ERROR: input folder not found: {INPUT_DIR}")
        return
 
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
 
    pdf_files = sorted(
        p for p in INPUT_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"
    )
 
    processed = []   # (name, pages, chars)
    skipped = []     # names
    failed = []      # (name, error)
    page_problems = []  # (name, page_number, error)
 
    print(f"Found {len(pdf_files)} PDF(s) in {INPUT_DIR}\n")
 
    for pdf_path in pdf_files:
        if pdf_path.name.lower() in SKIP_FILES:
            print(f"SKIPPED (OCR file): {pdf_path.name}")
            skipped.append(pdf_path.name)
            continue
 
        print(f"Processing: {pdf_path.name}")
        try:
            page_texts, page_errors = extract_pages(pdf_path)
            write_text_file(OUTPUT_DIR / (pdf_path.stem + ".txt"), page_texts)
 
            chars = sum(len(t) for t in page_texts)
            print(f"    OK: {len(page_texts)} pages, {chars} characters")
            processed.append((pdf_path.name, len(page_texts), chars))
 
            for page_number, message in page_errors:
                print(f"    page {page_number} failed: {message}")
                page_problems.append((pdf_path.name, page_number, message))
 
        except Exception as error:
            # Do not stop the whole program: record the failure and continue
            print(f"    FAILED: {error}")
            failed.append((pdf_path.name, str(error)))
 
    # -----------------------------------------------------------------------
    # 5. Final summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("EXTRACTION SUMMARY")
    print("=" * 60)
    print(f"PDFs found:              {len(pdf_files)}")
    print(f"Successfully processed:  {len(processed)}")
    print(f"Skipped (OCR file):      {len(skipped)}")
    print(f"Failed:                  {len(failed)}")
    print(f"Total pages extracted:   {sum(p for _, p, _ in processed)}")
    print(f"Total characters:        {sum(c for _, _, c in processed)}")
 
    for name in skipped:
        print(f"\nSkipped: {name}")
    if failed:
        print("\nFailed PDFs:")
        for name, message in failed:
            print(f"  - {name}  ({message})")
    if page_problems:
        print("\nPages that failed to extract (saved as blank):")
        for name, page_number, message in page_problems:
            print(f"  - {name}, page {page_number}: {message}")
 
    print(f"\nText files saved in: {OUTPUT_DIR}")
    print("Next: run  python validate_extraction.py")
 
 
if __name__ == "__main__":
    main()