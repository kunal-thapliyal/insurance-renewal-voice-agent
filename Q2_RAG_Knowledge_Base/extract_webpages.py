import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

OUTPUT_DIR = (
    BASE_DIR
    / "Data"
    / "raw"
    / "WEB"
)

MANIFEST_FILE = OUTPUT_DIR / "web_sources_manifest.json"


# ============================================================
# WEB SOURCES
# ============================================================

WEB_SOURCES = [
    {
        "source_id": "LIC-001",
        "title": "Payment at Cash Counter",
        "url": "https://licindia.in/en/web/guest/payment-at-cash-counter",
        "authority": "LIC",
        "document_type": "Web Page",
    },
    {
        "source_id": "LIC-003",
        "title": "Payment through alternate channels",
        "url": "https://licindia.in/web/guest/payment-through-alternate-channels#main-title",
        "authority": "LIC",
        "document_type": "Web Page",
    },
    {
        "source_id": "LIC-004",
        "title": "LIC Portal",
        "url": "https://licindia.in/web/guest/lic-portal",
        "authority": "LIC",
        "document_type": "Web Page",
    },
    {
        "source_id": "LIC-005",
        "title": "Policy Guidelines & Helpline",
        "url": "https://licindia.in/web/guest/policy-guidelines-helpline",
        "authority": "LIC",
        "document_type": "Web Page",
    },
    {
        "source_id": "LIC-006",
        "title": "Policy Status",
        "url": "https://licindia.in/web/guest/policy-status",
        "authority": "LIC",
        "document_type": "Web Page",
    },
    {
        "source_id": "LIC-007",
        "title": "Customers Corner",
        "url": "https://licindia.in/web/guest/customers-corner",
        "authority": "LIC",
        "document_type": "Web Page",
    },
    {
        "source_id": "LIC-008",
        "title": "Grievance Redressal",
        "url": "https://licindia.in/grievances",
        "authority": "LIC",
        "document_type": "Web Page",
    },
]


# ============================================================
# REQUEST SETTINGS
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/154.0 Safari/537.36"
    )
}

TIMEOUT = 30


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_text(text):
    """
    Conservative whitespace cleanup.

    Does NOT summarize, rewrite, or remove substantive
    insurance information.
    """

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Normalize spaces/tabs.
    text = re.sub(r"[ \t]+", " ", text)

    # Remove excessive blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# ============================================================
# EXTRACT MAIN CONTENT
# ============================================================

def extract_main_content(html):
    """
    Extract visible textual webpage content while removing
    obvious presentation/navigation elements.
    """

    soup = BeautifulSoup(html, "html.parser")

    # Remove elements that are presentation/navigation noise.
    for tag in soup([
        "script",
        "style",
        "noscript",
        "svg",
        "iframe",
        "canvas",
        "nav",
        "footer"
    ]):
        tag.decompose()

    # Remove common header/navigation containers.
    selectors_to_remove = [
        "header",
        ".header",
        ".navbar",
        ".navigation",
        ".nav",
        ".breadcrumb",
        ".breadcrumbs",
        ".footer",
        ".site-footer",
        ".cookie",
        ".cookie-banner",
        ".modal",
    ]

    for selector in selectors_to_remove:

        for element in soup.select(selector):
            element.decompose()

    # Prefer main/article content when available.
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find(
            "div",
            class_=re.compile(
                r"(content|article|main|portlet)",
                re.I
            )
        )
    )

    if main:
        text = main.get_text(
            separator="\n",
            strip=True
        )
    else:
        text = soup.get_text(
            separator="\n",
            strip=True
        )

    return clean_text(text)


# ============================================================
# FETCH WEBPAGE
# ============================================================

def fetch_page(url):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT
    )

    response.raise_for_status()

    return response.text, response.status_code


# ============================================================
# MAIN
# ============================================================

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print("=" * 70)
    print("LIC WEBPAGE EXTRACTION")
    print("=" * 70)

    manifest = []

    for source in WEB_SOURCES:

        source_id = source["source_id"]
        title = source["title"]
        url = source["url"]

        print()
        print("-" * 70)
        print(f"{source_id}: {title}")
        print(url)

        record = {
            "source_id": source_id,
            "title": title,
            "url": url,
            "authority": source["authority"],
            "document_type": source["document_type"],
            "retrieved_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": "failed",
            "http_status": None,
            "text_file": None,
            "character_count": 0,
            "error": None,
        }

        try:

            html, status_code = fetch_page(url)

            record["http_status"] = status_code

            text = extract_main_content(html)

            if not text:
                raise ValueError(
                    "No textual content extracted"
                )

            output_file = (
                OUTPUT_DIR
                / f"{source_id}.txt"
            )

            output_file.write_text(
                text,
                encoding="utf-8"
            )

            record["status"] = "success"
            record["text_file"] = output_file.name
            record["character_count"] = len(text)

            print(
                f"SUCCESS - {len(text):,} characters extracted"
            )

        except Exception as e:

            record["error"] = str(e)

            print(
                f"FAILED - {e}"
            )

        manifest.append(record)

    # --------------------------------------------------------
    # Save manifest
    # --------------------------------------------------------

    with MANIFEST_FILE.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            manifest,
            f,
            indent=2,
            ensure_ascii=False
        )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    successful = sum(
        1
        for item in manifest
        if item["status"] == "success"
    )

    failed = len(manifest) - successful

    print()
    print("=" * 70)
    print("EXTRACTION COMPLETE")
    print("=" * 70)

    print(
        f"Sources attempted: {len(manifest)}"
    )

    print(
        f"Successful:        {successful}"
    )

    print(
        f"Failed:            {failed}"
    )

    print()
    print("Output directory:")
    print(OUTPUT_DIR)

    print()
    print("Manifest:")
    print(MANIFEST_FILE)

    print("=" * 70)


if __name__ == "__main__":
    main()