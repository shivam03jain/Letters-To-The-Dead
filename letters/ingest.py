"""Step 1 of the pipeline: turn the raw Gutenberg text into clean passages.

A "passage" is one numbered section of one book:
    {"book": 1, "section": 2, "text": "From the reputation and ..."}

Run a quick check from the project root:
    python -m letters.ingest
"""

import re
from pathlib import Path

RAW_PATH = "data/raw/meditations_long.txt"

# --- The rules, taken from looking at the real file -------------------------

# The phrase "THE THOUGHTS" appears alone on a line twice: once on the title
# page, once where the real text begins. We start after the SECOND one.
START_LINE = "THE THOUGHTS"

# The text ends here; everything after is an index and the Gutenberg footer.
END_LINE = "INDEXES."

# Book headings are a Roman numeral alone on a line: "I.", "II.", ... "XII."
ROMAN = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
    "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
}

# A new section starts with a number, a period and a space: "2. From my mother..."
SECTION_START = re.compile(r"^(\d+)\. (.*)$")

# A footnote block starts with four spaces and a marker: "    [A] Annius Verus was..."
# It runs until the next line that is NOT indented. Plain indented lines outside
# a footnote (like quoted verse) are real text and must be kept.
FOOTNOTE_START = re.compile(r"^    \[[A-Z]\] ")

# Footnote markers like [A] or [B]. Only a single capital letter in brackets,
# so the translator's own additions like [I learned] are kept.
FOOTNOTE_MARK = re.compile(r"\[[A-Z]\]")


# --- The parser --------------------------------------------------------------

def parse_meditations(path=RAW_PATH):
    """Read the raw file and return a list of {"book", "section", "text"}."""
    # read_text turns Windows line endings (\r\n) into plain \n for us.
    lines = Path(path).read_text(encoding="utf-8").splitlines()

    # 1. Cut out just the real text.
    starts = [i for i, line in enumerate(lines) if line.strip() == START_LINE]
    start = starts[1] + 1                      # after the second "THE THOUGHTS"
    end = lines.index(END_LINE, start)         # first "INDEXES." after the start
    body = lines[start:end]

    passages = []
    book = 0                # which book we are in (0 = none yet)
    section = 0             # which section we are in
    paragraphs = []         # finished paragraphs of the current section
    current = []            # wrapped lines of the paragraph being built
    in_footnote = False     # True while we are inside a footnote block

    def finish_paragraph():
        """Join the wrapped lines of one paragraph into a single string."""
        nonlocal current
        if current:
            text = " ".join(part.strip() for part in current)
            text = FOOTNOTE_MARK.sub("", text)      # drop [A], [B], ...
            text = re.sub(r"\s+", " ", text).strip()  # tidy leftover spaces
            if text:
                paragraphs.append(text)
        current = []

    def finish_section():
        """Save the current section (if there is one) and reset."""
        finish_paragraph()
        if book and section and paragraphs:
            passages.append(
                {"book": book, "section": section, "text": "\n\n".join(paragraphs)}
            )
        paragraphs.clear()

    for line in body:
        stripped = line.strip()

        # 2. Footnotes. A footnote block starts with "    [A] " and lasts until
        #    the next non-indented line. Skip everything inside it. (Indented
        #    lines OUTSIDE a footnote, like quoted verse, are kept.)
        if FOOTNOTE_START.match(line):
            in_footnote = True
            continue
        if in_footnote:
            if not stripped or line.startswith(" "):
                continue           # blank or indented: still inside the footnote
            in_footnote = False    # a normal line: the footnote is over

        # 3. A blank line ends a paragraph.
        if not stripped:
            finish_paragraph()
            continue

        # 4. A book heading: "I.", "II.", ...
        if stripped.endswith(".") and stripped[:-1] in ROMAN:
            finish_section()
            book = ROMAN[stripped[:-1]]
            section = 1        # section 1 has no number, so we set it ourselves
            continue

        # 5. A new numbered section. Only accept the NEXT expected number, so a
        #    wrapped line that happens to start with a digit can't fool us.
        match = SECTION_START.match(stripped)
        if match and int(match.group(1)) == section + 1:
            finish_section()
            section = int(match.group(1))
            current.append(match.group(2))   # the rest of the line after "2. "
            continue

        # 6. Otherwise it is an ordinary line of the current paragraph.
        current.append(stripped)

    finish_section()  # don't forget the very last section
    return passages


# --- The sanity checks -------------------------------------------------------

def check_passages(passages):
    """Fail loudly if the parser output looks wrong."""
    books = {}
    for p in passages:
        books.setdefault(p["book"], []).append(p["section"])

    assert sorted(books) == list(range(1, 13)), f"expected books 1-12, got {sorted(books)}"

    for book, sections in books.items():
        expected = list(range(1, len(sections) + 1))
        assert sections == expected, f"book {book}: sections are not 1..{len(sections)} in order"

    for p in passages:
        assert p["text"].strip(), f"empty text in book {p['book']} section {p['section']}"
        assert not FOOTNOTE_MARK.search(p["text"]), \
            f"footnote marker left in book {p['book']} section {p['section']}"

    print(f"OK: {len(books)} books, {len(passages)} sections")
    for book in sorted(books):
        print(f"  Book {book}: {len(books[book])} sections")


if __name__ == "__main__":
    result = parse_meditations()
    check_passages(result)
    print()
    print(result[1])   # Book 1, section 2, so you can eyeball one passage