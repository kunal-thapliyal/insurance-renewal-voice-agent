from pathlib import Path
import pymupdf


# ---------------------------------------------------------
# 1. Paths
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

PDF_PATH = (
    BASE_DIR
    / "Data"
    / "raw"
    / "PDF"
    / "IRDAI 002 Master Circular on Protection of Policyholders' interests 2024.pdf"
)

OUTPUT_PATH = (
    BASE_DIR
    / "Data"
    / "processed"
    / "raw_text"
    / "IRDAI 002 Master Circular on Protection of Policyholders' interests 2024_pymupdf.txt"
)


# ---------------------------------------------------------
# 2. Check PDF
# ---------------------------------------------------------

if not PDF_PATH.exists():
    print(f"ERROR: PDF not found:\n{PDF_PATH}")
    raise SystemExit


# ---------------------------------------------------------
# 3. Open PDF
# ---------------------------------------------------------

print(f"Opening: {PDF_PATH.name}")

document = pymupdf.open(PDF_PATH)

print(f"Pages: {len(document)}")


# ---------------------------------------------------------
# 4. Extract text page by page
# ---------------------------------------------------------

sections = []

for page_number, page in enumerate(document, start=1):

    print(f"Extracting page {page_number}/{len(document)}")

    text = page.get_text("text")

    sections.append(
        f"--- PAGE {page_number} ---\n{text}\n"
    )


document.close()


# ---------------------------------------------------------
# 5. Save extracted text
# ---------------------------------------------------------

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

with open(OUTPUT_PATH, "w", encoding="utf-8") as file:
    file.write("\n".join(sections))


# ---------------------------------------------------------
# 6. Summary
# ---------------------------------------------------------

total_characters = sum(
    len(section)
    for section in sections
)

print("\n" + "=" * 60)
print("PYMUPDF EXTRACTION COMPLETE")
print("=" * 60)

print(f"PDF: {PDF_PATH.name}")
print(f"Pages: {len(sections)}")
print(f"Characters: {total_characters}")
print(f"Output: {OUTPUT_PATH}")

print("\nNow open the generated TXT file and inspect the Hindi text.")