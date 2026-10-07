import sys
from pathlib import Path
import fitz
import pytesseract
from PIL import Image


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ---------------------------------------------------------------------------
# 1. Settings
# ---------------------------------------------------------------------------

# Tesseract is not in the Windows PATH, so we tell pytesseract where it is.
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

BASE_DIR = Path(__file__).resolve().parent

PDF_DIR = BASE_DIR / "Data" / "raw" / "PDF"
TEXT_DIR = BASE_DIR / "Data" / "processed" / "raw_text"

OCR_LANGUAGE = "eng"
RENDER_DPI = 300


# ---------------------------------------------------------------------------
# 2. File settings
# ---------------------------------------------------------------------------

# LIC-002:
# Entire PDF needs OCR.
LIC_002_PDF = (
    PDF_DIR / "LIC 002 Payment by ChequeDemand Draft.pdf"
)

LIC_002_OUTPUT = (
    TEXT_DIR / "LIC 002 Payment by ChequeDemand Draft.txt"
)


# LIC-015A:
# Only page 1 needs OCR.
LIC_015A_PDF = (
    PDF_DIR / "LIC 015A LIC's Jeevan Utsav – Sales Brochure.pdf"
)

LIC_015A_OUTPUT = (
    TEXT_DIR / "LIC 015A LIC's Jeevan Utsav – Sales Brochure.txt"
)

LIC_015A_PAGE = 1


# ---------------------------------------------------------------------------
# 3. OCR one page
# ---------------------------------------------------------------------------

def ocr_page(page):
    """Render one PDF page as an image and return its OCR text."""

    pixmap = page.get_pixmap(
        dpi=RENDER_DPI,
        alpha=False
    )

    image = Image.frombytes(
        "RGB",
        (pixmap.width, pixmap.height),
        pixmap.samples
    )

    return pytesseract.image_to_string(
        image,
        lang=OCR_LANGUAGE
    )


# ---------------------------------------------------------------------------
# 4. OCR entire PDF
# ---------------------------------------------------------------------------

def ocr_entire_pdf(pdf_path, output_path):
    """OCR every page of a PDF and save the result."""

    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        return False

    print()
    print("=" * 60)
    print(f"OCR: {pdf_path.name}")
    print("=" * 60)

    try:
        document = fitz.open(str(pdf_path))
    except Exception as error:
        print(f"ERROR: could not open the PDF: {error}")
        return False

    page_count = document.page_count

    print(f"Opened: {pdf_path.name} ({page_count} page(s))")

    sections = []
    page_errors = []

    for index in range(page_count):

        page_number = index + 1

        print(
            f"  OCR page {page_number} "
            f"of {page_count} ..."
        )

        try:
            text = ocr_page(document[index])

        except Exception as error:

            text = ""

            page_errors.append(
                (page_number, str(error))
            )

            print(
                f"    page {page_number} FAILED: {error}"
            )

        sections.append(
            f"--- PAGE {page_number} ---\n"
            f"{text}\n"
        )

    document.close()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    content = "\n".join(sections)

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as f:
        f.write(content)

    total_chars = sum(
        len(section.split("\n", 1)[1].strip())
        for section in sections
    )

    print()
    print("OCR SUMMARY")
    print("-" * 60)
    print(f"PDF processed:       {pdf_path.name}")
    print(f"Number of pages:     {page_count}")
    print(f"Characters extracted:{total_chars}")
    print(f"Output file:         {output_path}")

    if page_errors:
        print("Page errors:")

        for page_number, message in page_errors:
            print(
                f"  - page {page_number}: {message}"
            )
    else:
        print("Page errors:         none")

    return True


# ---------------------------------------------------------------------------
# 5. OCR LIC-015A page 1
# ---------------------------------------------------------------------------

def ocr_lic_015a_page_1():
    """
    OCR only page 1 of LIC-015A.

    Pages 2-32 were already extracted using PyMuPDF.
    Only the empty page 1 is replaced with OCR text.
    """

    print()
    print("=" * 60)
    print("OCR: LIC-015A PAGE 1")
    print("=" * 60)

    if not LIC_015A_PDF.exists():
        print(
            f"ERROR: PDF not found: {LIC_015A_PDF}"
        )
        return False

    if not LIC_015A_OUTPUT.exists():
        print(
            f"ERROR: Existing TXT file not found:\n"
            f"{LIC_015A_OUTPUT}"
        )
        print(
            "Run extract_pdfs.py first."
        )
        return False

    try:
        document = fitz.open(
            str(LIC_015A_PDF)
        )
    except Exception as error:
        print(
            f"ERROR: could not open the PDF: {error}"
        )
        return False

    if document.page_count < LIC_015A_PAGE:
        document.close()

        print(
            "ERROR: Page 1 does not exist."
        )

        return False

    print(
        f"Opened: {LIC_015A_PDF.name}"
    )

    print(
        "  OCR page 1 ..."
    )

    try:
        ocr_text = ocr_page(
            document[LIC_015A_PAGE - 1]
        )

    except Exception as error:

        document.close()

        print(
            f"ERROR: OCR failed: {error}"
        )

        return False

    document.close()

    # -------------------------------------------------------
    # Read existing PyMuPDF text
    # -------------------------------------------------------

    content = LIC_015A_OUTPUT.read_text(
        encoding="utf-8",
        errors="replace"
    )

    page_1_marker = "--- PAGE 1 ---"
    page_2_marker = "--- PAGE 2 ---"

    page_1_start = content.find(
        page_1_marker
    )

    page_2_start = content.find(
        page_2_marker
    )

    if page_1_start == -1:
        print(
            "ERROR: PAGE 1 marker not found "
            "in existing TXT."
        )
        return False

    if page_2_start == -1:
        print(
            "ERROR: PAGE 2 marker not found "
            "in existing TXT."
        )
        return False

    # -------------------------------------------------------
    # Replace only page 1
    # -------------------------------------------------------

    before_page_1 = content[:page_1_start]

    after_page_1 = content[page_2_start:]

    new_page_1 = (
        f"{page_1_marker}\n"
        f"{ocr_text.strip()}\n\n"
    )

    new_content = (
        before_page_1
        + new_page_1
        + after_page_1
    )

    # -------------------------------------------------------
    # Save
    # -------------------------------------------------------

    LIC_015A_OUTPUT.write_text(
        new_content,
        encoding="utf-8"
    )

    print()
    print(
        f"OCR characters extracted: "
        f"{len(ocr_text.strip())}"
    )

    print(
        f"Updated file: {LIC_015A_OUTPUT}"
    )

    print(
        "Pages 2-32 were preserved."
    )

    return True


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------

def main():

    # Check Tesseract
    if not Path(TESSERACT_PATH).exists():

        print(
            f"ERROR: Tesseract not found at:\n"
            f"{TESSERACT_PATH}"
        )

        return

    TEXT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print("=" * 60)
    print("OCR PROCESSING")
    print("=" * 60)

    # -------------------------------------------------------
    # LIC-002
    # -------------------------------------------------------

    ocr_entire_pdf(
        LIC_002_PDF,
        LIC_002_OUTPUT
    )

    # -------------------------------------------------------
    # LIC-015A page 1
    # -------------------------------------------------------

    ocr_lic_015a_page_1()

    # -------------------------------------------------------
    # Final summary
    # -------------------------------------------------------

    print()
    print("=" * 60)
    print("OCR PROCESSING COMPLETE")
    print("=" * 60)

    print("LIC-002: entire PDF OCR")
    print("LIC-015A: page 1 OCR only")
    print()
    print("Original PDFs were not modified.")


if __name__ == "__main__":
    main()