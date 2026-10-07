from pathlib import Path
import csv


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

RAW_PDF_DIR = BASE_DIR / "Data" / "raw" / "PDF"
OUTPUT_DIR = BASE_DIR / "Data" / "processed" / "metadata"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = OUTPUT_DIR / "document_metadata.csv"


DOCUMENTS = {

    # --------------------------------------------------------
    # IRDAI
    # --------------------------------------------------------

    "IRDAI-001": {
        "title": "IRDAI (Protection of Policyholder's Interests, operations and allied matters of insurers) Regulations, 2024",
        "authority": "IRDAI",
        "document_type": "Regulation",
        "product": "",
        "plan_number": "",
        "uin": "",
        "version": "2024",
        "effective_date": "01/04/2024",
        "language": "English",
        "status": "Current",
    },

    "IRDAI-002": {
        "title": "Master Circular on Protection of Policyholders' Interests, 2024",
        "authority": "IRDAI",
        "document_type": "Master Circular",
        "product": "",
        "plan_number": "",
        "uin": "",
        "version": "2024",
        "effective_date": "05/09/2024",
        "language": "English",
        "status": "Current",
    },

    "IRDAI-003": {
        "title": "Master Circular on Life Insurance Products, 2024",
        "authority": "IRDAI",
        "document_type": "Master Circular",
        "product": "",
        "plan_number": "",
        "uin": "",
        "version": "2024",
        "effective_date": "12/06/2024",
        "language": "English",
        "status": "Current",
    },


    # --------------------------------------------------------
    # LIC
    # --------------------------------------------------------

    "LIC-002": {
        "title": "Payment of Premium by Cheque/Demand Draft",
        "authority": "LIC",
        "document_type": "Payment Guidance",
        "product": "",
        "plan_number": "",
        "uin": "",
        "version": "",
        "effective_date": "",
        "language": "English",
        "status": "Current",
    },

    "LIC-009": {
        "title": "Branch Grievance Redressal Officers 2026–27",
        "authority": "LIC",
        "document_type": "Grievance Contact Directory",
        "product": "",
        "plan_number": "",
        "uin": "",
        "version": "2026–27",
        "effective_date": "",
        "language": "English",
        "status": "Current",
    },

    "LIC-010": {
        "title": "Divisional Grievance Redressal Officers 2026–27",
        "authority": "LIC",
        "document_type": "Grievance Contact Directory",
        "product": "",
        "plan_number": "",
        "uin": "",
        "version": "2026–27",
        "effective_date": "",
        "language": "English",
        "status": "Current",
    },

    "LIC-011": {
        "title": "Zonal Grievance Redressal Officers 2026–27",
        "authority": "LIC",
        "document_type": "Grievance Contact Directory",
        "product": "",
        "plan_number": "",
        "uin": "",
        "version": "2026–27",
        "effective_date": "",
        "language": "English",
        "status": "Current",
    },

    "LIC-012": {
        "title": "Corporate Grievance Redressal Officers 2026–27",
        "authority": "LIC",
        "document_type": "Grievance Contact Directory",
        "product": "",
        "plan_number": "",
        "uin": "",
        "version": "2026–27",
        "effective_date": "",
        "language": "English",
        "status": "Current",
    },

    "LIC-013": {
        "title": "Policy for Protection of Interests of Policyholders, 2024",
        "authority": "LIC",
        "document_type": "Policy",
        "product": "",
        "plan_number": "",
        "uin": "",
        "version": "2024",
        "effective_date": "",
        "language": "English",
        "status": "Current",
    },


    # --------------------------------------------------------
    # NEW JEEVAN ANAND
    # --------------------------------------------------------

    "LIC-014A": {
        "title": "LIC's New Jeevan Anand – Sales Brochure",
        "authority": "LIC",
        "document_type": "Sales Brochure",
        "product": "New Jeevan Anand",
        "plan_number": "715",
        "uin": "512N279V03",
        "version": "22092025 onwards",
        "effective_date": "22/09/2025",
        "language": "English",
        "status": "Current",
    },

    "LIC-014B": {
        "title": "LIC's New Jeevan Anand – Policy Document",
        "authority": "LIC",
        "document_type": "Policy Document",
        "product": "New Jeevan Anand",
        "plan_number": "715",
        "uin": "512N279V03",
        "version": "04072025",
        "effective_date": "04/07/2025",
        "language": "English",
        "status": "Current",
    },

    "LIC-014C": {
        "title": "LIC's New Jeevan Anand – Customer Information Sheet",
        "authority": "LIC",
        "document_type": "Customer Information Sheet",
        "product": "New Jeevan Anand",
        "plan_number": "715",
        "uin": "512N279V03",
        "version": "04072025 onwards",
        "effective_date": "04/07/2025",
        "language": "English",
        "status": "Current",
    },


    # --------------------------------------------------------
    # JEEVAN UTSAV
    # --------------------------------------------------------

    "LIC-015A": {
        "title": "LIC's Jeevan Utsav – Sales Brochure",
        "authority": "LIC",
        "document_type": "Sales Brochure",
        "product": "Jeevan Utsav",
        "plan_number": "871",
        "uin": "512N363V02",
        "version": "",
        "effective_date": "",
        "language": "English",
        "status": "Current",
    },

    "LIC-015B": {
        "title": "LIC's Jeevan Utsav – Customer Information Sheet",
        "authority": "LIC",
        "document_type": "Customer Information Sheet",
        "product": "Jeevan Utsav",
        "plan_number": "871",
        "uin": "512N363V02",
        "version": "",
        "effective_date": "",
        "language": "English",
        "status": "Current",
    },

    "LIC-015C": {
        "title": "LIC's Jeevan Utsav – Policy Document",
        "authority": "LIC",
        "document_type": "Policy Document",
        "product": "Jeevan Utsav",
        "plan_number": "871",
        "uin": "512N363V02",
        "version": "04/07/2025",
        "effective_date": "04/07/2025",
        "language": "English",
        "status": "Current",
    },


    # --------------------------------------------------------
    # NEW MONEY BACK PLAN – 20 YEARS
    # --------------------------------------------------------

    "LIC-016A": {
        "title": "LIC's New Money Back Plan – 20 Years – Sales Brochure",
        "authority": "LIC",
        "document_type": "Sales Brochure",
        "product": "New Money Back Plan – 20 Years",
        "plan_number": "720",
        "uin": "512N280V03",
        "version": "",
        "effective_date": "",
        "language": "English",
        "status": "Current",
    },

    "LIC-016B": {
        "title": "LIC's New Money Back Plan – 20 Years – Customer Information Sheet",
        "authority": "LIC",
        "document_type": "Customer Information Sheet",
        "product": "New Money Back Plan – 20 Years",
        "plan_number": "720",
        "uin": "512N280V03",
        "version": "",
        "effective_date": "",
        "language": "English",
        "status": "Current",
    },

    "LIC-016C": {
        "title": "LIC's New Money Back Plan – 20 Years – Policy Document",
        "authority": "LIC",
        "document_type": "Policy Document",
        "product": "New Money Back Plan – 20 Years",
        "plan_number": "720",
        "uin": "512N280V03",
        "version": "",
        "effective_date": "",
        "language": "English",
        "status": "Current",
    },


    # --------------------------------------------------------
    # NEW TECH-TERM
    # --------------------------------------------------------

    "LIC-017A": {
        "title": "LIC's New Tech-Term – Sales Brochure",
        "authority": "LIC",
        "document_type": "Sales Brochure",
        "product": "New Tech-Term",
        "plan_number": "954",
        "uin": "512N351V02",
        "version": "",
        "effective_date": "",
        "language": "English",
        "status": "Current",
    },

    "LIC-017B": {
        "title": "LIC's New Tech-Term – Customer Information Sheet",
        "authority": "LIC",
        "document_type": "Customer Information Sheet",
        "product": "New Tech-Term",
        "plan_number": "954",
        "uin": "512N351V02",
        "version": "",
        "effective_date": "",
        "language": "English",
        "status": "Current",
    },

    "LIC-017C": {
        "title": "LIC's New Tech-Term – Policy Document",
        "authority": "LIC",
        "document_type": "Policy Document",
        "product": "New Tech-Term",
        "plan_number": "954",
        "uin": "512N351V02",
        "version": "",
        "effective_date": "",
        "language": "English",
        "status": "Current",
    },


    # --------------------------------------------------------
    # FORM
    # --------------------------------------------------------

    "LIC-018": {
        "title": "Revival of Lapsed Policy – Form No. 680",
        "authority": "LIC",
        "document_type": "Form",
        "product": "",
        "plan_number": "",
        "uin": "",
        "version": "",
        "effective_date": "",
        "language": "English",
        "status": "Current",
    },
}


# ============================================================
# SOURCE FILE MAPPING
# ============================================================
# This connects our source IDs to the actual PDF filenames.
# ============================================================

SOURCE_FILES = {
    "IRDAI-001": "IRDAI 001 IRDAI (Protection of Policyholder's Interests, operations and allied matters of insurers) Regulations, 2024.pdf",
    "IRDAI-002": "IRDAI 002 Master Circular on Protection of Policyholders' interests 2024.pdf",
    "IRDAI-003": "IRDAI 003 Master Circular on Life Insurance Products, 2024.pdf",

    "LIC-002": "LIC 002 Payment by ChequeDemand Draft.pdf",
    "LIC-009": "LIC 009 Branch Grievance Redressal Officers 2026–27.pdf",
    "LIC-010": "LIC 010 Divisional Grievance Redressal Officers 2026–27.pdf",
    "LIC-011": "LIC 011 Zonal Grievance Redressal Officers 2026–27.pdf",
    "LIC-012": "LIC 012 Corporate Grievance Redressal Officers 2026–27.pdf",
    "LIC-013": "LIC 013 Policy for Protection of Interest of Policyholders.pdf",

    "LIC-014A": "LIC 014A LIC's New Jeevan Anand – Sales Brochure (22092025 onwards).pdf",
    "LIC-014B": "LIC 014B LIC's New Jeevan Anand – Policy Document (04072025).pdf",
    "LIC-014C": "LIC 014C LIC's New Jeevan Anand – CIS (04072025 onwards).pdf",

    "LIC-015A": "LIC 015A LIC's Jeevan Utsav – Sales Brochure.pdf",
    "LIC-015B": "LIC 015B LIC's Jeevan Utsav – CIS.pdf",
    "LIC-015C": "LIC 015C LIC's Jeevan Utsav – Policy Document.pdf",

    "LIC-016A": "LIC 016A LIC's New Money Back Plan – 20 Years – Sales Brochure.pdf",
    "LIC-016B": "LIC 016B LIC's New Money Back Plan – 20 Years – CIS.pdf",
    "LIC-016C": "LIC 016C LIC's New Money Back Plan – 20 Years – Policy Document.pdf",

    "LIC-017A": "LIC 017A LIC's New Tech-Term – Sales Brochure.pdf",
    "LIC-017B": "LIC 017B LIC's New Tech-Term – CIS.pdf",
    "LIC-017C": "LIC 017C LIC's New Tech-Term – Policy Document.pdf",

    "LIC-018": "LIC 018 Revival of Lapsed Policy – Form No. 680.pdf",
}


# ============================================================
# CREATE MASTER METADATA FILE
# ============================================================

def main():

    rows = []

    for source_id, metadata in DOCUMENTS.items():

        filename = SOURCE_FILES[source_id]
        pdf_path = RAW_PDF_DIR / filename

        row = {
            "source_id": source_id,
            "filename": filename,
            "file_exists": pdf_path.exists(),
            **metadata
        }

        rows.append(row)

    fieldnames = [
        "source_id",
        "filename",
        "file_exists",
        "title",
        "authority",
        "document_type",
        "product",
        "plan_number",
        "uin",
        "version",
        "effective_date",
        "language",
        "status",
    ]

    with open(
        OUTPUT_FILE,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames
        )

        writer.writeheader()
        writer.writerows(rows)

    print("=" * 60)
    print("DOCUMENT METADATA CREATED")
    print("=" * 60)

    print(f"Records created : {len(rows)}")
    print(f"Output file     : {OUTPUT_FILE}")
    print()

    missing_files = [
        row["source_id"]
        for row in rows
        if not row["file_exists"]
    ]

    if missing_files:

        print("WARNING: PDF files not found:")
        for source_id in missing_files:
            print(f"  - {source_id}")

    else:

        print("All 22 PDF files found successfully.")

    print()
    print("Document-level metadata only.")
    print("Page/section/chunk metadata will be added later.")


if __name__ == "__main__":
    main()