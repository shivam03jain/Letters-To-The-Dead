"""Steps 1 and 2 of the pipeline: raw text -> passages -> chunks.

A "passage" is one numbered section of one book:
    {"book": 1, "section": 2, "text": "From the reputation and ..."}

A "chunk" is a passage that is small enough to embed. Most passages are already
small enough, so they become exactly one chunk. Long passages are split at
sentence boundaries into several chunks that share the same book and section.
    {"id": "meditations:3:4:2", "source": "meditations", "translation": "George Long",
     "book": 3, "section": 4, "part": 2, "text": "..."}

Run a quick check from the project root:
    python -m letters.ingest
"""

import math
import re
from pathlib import Path

RAW_PATH = "data/raw/meditations_long.txt"
SOURCE_NAME = "meditations"
TRANSLATION = "George Long"

# Sections longer than this many words get split into several chunks.
# Change this one number to experiment (evals will tell you what works best).
MAX_WORDS = 300

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


# --- The chunker -------------------------------------------------------------

# A sentence ends at . ? or ! (optionally followed by a closing quote or bracket)
# and then whitespace. The two alternatives cover: 'thee?" But' and 'three]? for'.
SENTENCE_END = re.compile(r'(?<=[.!?]["\')\]])\s+|(?<=[.!?])\s+')

# Fallback for the rare "sentence" that is itself longer than MAX_WORDS
# (Book 1 section 17 has one of 420 words with 15 semicolons): split at semicolons.
CLAUSE_END = re.compile(r"(?<=;)\s+")


def count_words(text):
    return len(text.split())


def split_into_units(text, max_words):
    """Cut text into small pieces (sentences) without changing any words."""
    units = []
    for sentence in SENTENCE_END.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if count_words(sentence) > max_words:          # a huge "sentence"
            units.extend(c.strip() for c in CLAUSE_END.split(sentence) if c.strip())
        else:
            units.append(sentence)
    return units


def chunk_passage(passage, source=SOURCE_NAME, translation=TRANSLATION, max_words=MAX_WORDS):
    """Turn one passage into one or more chunk records."""
    text = passage["text"]

    if count_words(text) <= max_words:
        texts = [text]                                  # small enough: one chunk
    else:
        units = split_into_units(text, max_words)
        total = sum(count_words(u) for u in units)

        # Decide how many chunks we need, then aim for EQUAL sizes. (Plain
        # "fill each chunk up to the cap" leaves tiny leftovers of 6-20 words.)
        n_parts = math.ceil(total / max_words)
        target = total / n_parts

        texts, current, current_words = [], [], 0
        for unit in units:
            k = count_words(unit)
            parts_left = n_parts - len(texts)           # includes the one being built
            too_big = current_words + k > max_words
            drifts = abs(current_words + k - target) > abs(current_words - target)
            # Close the current chunk if adding this unit would break the cap, or
            # would take the chunk further from the target size. (The last chunk
            # is never closed early; it just takes whatever is left.)
            if current and (too_big or (parts_left > 1 and drifts)):
                texts.append(" ".join(current))
                current, current_words = [], 0
            current.append(unit)
            current_words += k
        if current:
            texts.append(" ".join(current))

    return [
        {
            "id": f"{source}:{passage['book']}:{passage['section']}:{part}",
            "source": source,
            "translation": translation,
            "book": passage["book"],
            "section": passage["section"],
            "part": part,
            "text": chunk_text,
        }
        for part, chunk_text in enumerate(texts, start=1)
    ]


def chunk_all(passages, **kwargs):
    """Chunk every passage and return one flat list of chunk records."""
    chunks = []
    for passage in passages:
        chunks.extend(chunk_passage(passage, **kwargs))
    return chunks


def check_chunks(passages, chunks, max_words=MAX_WORDS):
    """Fail loudly if chunking changed any words or broke the size rules."""
    by_section = {}
    for c in chunks:
        by_section.setdefault((c["book"], c["section"]), []).append(c)

    assert len({c["id"] for c in chunks}) == len(chunks), "duplicate chunk ids"

    for p in passages:
        parts = by_section[(p["book"], p["section"])]
        where = f"book {p['book']} section {p['section']}"

        # Parts are numbered 1, 2, 3... in order.
        assert [c["part"] for c in parts] == list(range(1, len(parts) + 1)), f"{where}: bad part numbers"

        # THE key rule: the words must be identical, ignoring whitespace.
        rejoined = " ".join(" ".join(c["text"] for c in parts).split())
        original = " ".join(p["text"].split())
        assert rejoined == original, f"{where}: chunking changed the text"

        # Small passages stay whole.
        if count_words(p["text"]) <= max_words:
            assert len(parts) == 1, f"{where}: small section was split"

    split = [k for k, v in by_section.items() if len(v) > 1]
    print(f"OK: {len(passages)} passages -> {len(chunks)} chunks ({len(split)} sections were split)")


if __name__ == "__main__":
    passages = parse_meditations()
    check_passages(passages)

    print()
    chunks = chunk_all(passages)
    check_chunks(passages, chunks)

    print()
    # Show how one long section was split (Book 3 section 4 is about 500 words).
    example = [c for c in chunks if c["book"] == 3 and c["section"] == 4]
    for c in example:
        print(c["id"], "->", count_words(c["text"]), "words")