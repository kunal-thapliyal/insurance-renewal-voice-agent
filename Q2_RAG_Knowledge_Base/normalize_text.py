from pathlib import Path
import re


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

INPUT_DIR = BASE_DIR / "Data" / "processed" / "cleaned"
OUTPUT_DIR = BASE_DIR / "Data" / "processed" / "normalized"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# NORMALIZATION FUNCTIONS
# ============================================================

def normalize_whitespace(text):
    """
    Normalize obvious whitespace noise without changing content.
    """

    # Normalize Windows line endings
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Remove trailing whitespace from each line
    lines = [line.rstrip() for line in text.split("\n")]

    # Collapse 3+ consecutive blank lines to at most 2
    cleaned_lines = []
    blank_count = 0

    for line in lines:
        if line.strip() == "":
            blank_count += 1

            if blank_count <= 2:
                cleaned_lines.append("")
        else:
            blank_count = 0
            cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)

    return text.strip() + "\n"


def normalize_bullets(text):
    """
    Normalize clearly identifiable bullet glyphs.

    This does NOT attempt to change table values or normal text.
    """

    lines = text.split("\n")
    normalized = []

    for line in lines:
        stripped = line.lstrip()
        indentation = line[:len(line) - len(stripped)]

        # Common extracted bullet glyphs
        bullet_map = {
            "": "-",
            "": "-",
            "": "-",
            "▪": "-",
            "●": "-",
            "○": "-",
            "◦": "-",
        }

        replaced = False

        for bullet, replacement in bullet_map.items():
            if stripped.startswith(bullet):
                stripped = replacement + stripped[len(bullet):].lstrip()
                replaced = True
                break

        if replaced:
            normalized.append(indentation + stripped)
        else:
            normalized.append(line)

    return "\n".join(normalized)


def normalize_spaces(text):
    """
    Safely normalize excessive spaces.

    Important:
    - Does not modify numbers.
    - Does not modify punctuation.
    - Does not join/reconstruct lines.
    """

    lines = []

    for line in text.split("\n"):

        # Collapse multiple normal spaces
        line = re.sub(r"[ \t]{2,}", " ", line)

        lines.append(line)

    return "\n".join(lines)


def normalize_page_markers(text):
    """
    Keep page markers consistent.

    Existing markers generated during extraction/cleaning are preserved.
    """

    text = re.sub(
        r"---\s*PAGE\s+(\d+)\s*---",
        r"--- PAGE \1 ---",
        text,
        flags=re.IGNORECASE
    )

    return text


# ============================================================
# PROCESS ONE FILE
# ============================================================

def normalize_file(input_path, output_path):

    text = input_path.read_text(
        encoding="utf-8",
        errors="replace"
    )

    original_chars = len(text)

    # Apply only safe normalization operations
    text = normalize_page_markers(text)
    text = normalize_bullets(text)
    text = normalize_spaces(text)
    text = normalize_whitespace(text)

    normalized_chars = len(text)

    output_path.write_text(
        text,
        encoding="utf-8"
    )

    return original_chars, normalized_chars


# ============================================================
# MAIN
# ============================================================

def main():

    input_files = sorted(INPUT_DIR.glob("*.txt"))

    if not input_files:
        print(f"No TXT files found in: {INPUT_DIR}")
        return

    print(f"Found {len(input_files)} cleaned text file(s)")
    print(f"Input : {INPUT_DIR}")
    print(f"Output: {OUTPUT_DIR}")
    print()

    total_original = 0
    total_normalized = 0

    for input_path in input_files:

        output_path = OUTPUT_DIR / input_path.name

        original_chars, normalized_chars = normalize_file(
            input_path,
            output_path
        )

        total_original += original_chars
        total_normalized += normalized_chars

        print(
            f"{input_path.name}: "
            f"{original_chars:,} → {normalized_chars:,} characters"
        )

    print()
    print("=" * 60)
    print("NORMALIZATION SUMMARY")
    print("=" * 60)
    print(f"Input files       : {len(input_files)}")
    print(f"Output files      : {len(input_files)}")
    print(f"Original chars    : {total_original:,}")
    print(f"Normalized chars  : {total_normalized:,}")
    print(f"Character change  : {total_normalized - total_original:+,}")
    print()
    print("Normalization completed.")
    print()
    print("Original cleaned files were NOT modified.")


if __name__ == "__main__":
    main()