"""Layout-aware text extraction for governing-document PDFs.

pypdf's ``extract_text()`` has no notion of layout: on the SU's Word-exported
PDFs it splits words mid-glyph ("r egistered", "Bye - Law 1 0"), fuses whole
runs of clauses into one paragraph and keeps contents pages and page numbers
as body text. This module rebuilds the document from PyMuPDF's positioned
glyphs instead, and emits a small, stable plaintext convention that readers
can parse without guessing:

* ``## `` / ``### `` prefix a heading (``#`` is reserved for the title line).
* Every clause or paragraph is its own block, separated by a blank line.
* A clause keeps its own marker (``3.1.2.``, ``b.``, ``iv.``, ``(a)``, ``•``)
  and is indented by two spaces per nesting level.
* Ruled tables become Markdown pipe tables.

It is deliberately conservative about the words themselves: nothing is
spell-corrected, because this is the text people quote in disputes.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

try:
    import pymupdf
except ImportError:  # Core installs do not carry the scrape extra.
    pymupdf = None

# A gap wider than this fraction of the font size between two fragments on
# one baseline is a word break. Word frequently emits the space between two
# words as its own fragment, or omits it and relies on positioning.
_SPACE_GAP = 0.2
# Marker columns are compared with this tolerance (points). Roman numerals
# are right-aligned in the Bye-Laws, so "viii." starts ~9pt left of "i.".
_INDENT_TOLERANCE = 12.0

_MARKER_RE = re.compile(
    r"^(?P<marker>"
    r"\d{1,2}(?:\.\d{1,2}){1,3}\.?"  # dotted: 3.1 / 3.1.2.
    r"|\d{1,2}[.)]"  # 1.  1)
    r"|\d{1,2}(?=\s)"  # bare 1 (OCR drops the dot); column-checked below
    r"|[a-z]{1,2}[.)]"  # a.  aa.  b)
    r"|[ivxl]{1,6}[.)]"  # iv.
    r"|[A-Z][.)]"  # A.
    r"|\((?:[a-z]{1,2}|[ivxl]{1,6}|\d{1,2}|[A-Z])\)"  # (a) (iv) (2)
    r"|[•●▪◦‣∙·–-]"  # bullets
    r")\s+(?=\S)"
)
_DOTTED_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2}){1,3}\.?$")
_BYELAW_HEADING_RE = re.compile(r"^Bye\s*-?\s*Law\s*((?:\d\s*){1,2})\s*[-–—:]\s*(.+)$", re.IGNORECASE)
_NUMBER_ONLY_RE = re.compile(r"^(?:page\s+)?\d{1,3}(?:\s+of\s+\d{1,3})?$", re.IGNORECASE)
# Contents-page leader: real dots, or the "ssssseeee" OCR makes of them.
_LEADER_RE = re.compile(r"(?:\.\s?){4,}|…{2,}|[.,:;sScCeEoOnNuUmMr]{14,}")
_RULE_RE = re.compile(r"^[_\-–—=.\s]{8,}$")
_SENTENCE_END_RE = re.compile(r"[.;:!?”’\")]$")


@dataclass
class Row:
    """One visual line of a page."""

    page: int
    y: float
    x0: float
    x1: float
    size: float
    bold: bool
    text: str


@dataclass
class Block:
    kind: str  # "heading" | "para" | "table"
    text: str
    level: int = 0  # heading level (2/3) or clause depth
    marker: Optional[str] = None
    marker_x: float = 0.0
    cont_x: Optional[float] = None
    last: Optional[Row] = None
    lines: list[str] = field(default_factory=list)


# -- page → rows ---------------------------------------------------------


def page_rows(page, page_number: int, textpage=None, skip_rects=()) -> list[Row]:
    """Merge a page's text fragments into visual lines.

    Word-exported PDFs split one visual line into many fragments (often one
    per kerning run) and emit them out of order. Fragments are ordered by x,
    but glyphs inside a fragment keep content-stream order: sorting glyphs
    by x scrambles tightly kerned text ("By-eLaws").
    """
    kwargs = {"textpage": textpage} if textpage is not None else {}
    frags = []
    for block in page.get_text("rawdict", **kwargs)["blocks"]:
        for line in block.get("lines", []):
            if abs(line["dir"][1]) > 0.1:  # rotated margin text, stamps
                continue
            chars = [(ch, span) for span in line["spans"] for ch in span["chars"]]
            if not chars:
                continue
            ink = [(ch, span) for ch, span in chars if ch["c"].strip()]
            if not ink:
                ch, span = chars[0]
                frags.append({
                    "y": ch["origin"][1], "x0": ch["bbox"][0], "x1": ch["bbox"][0],
                    "size": span["size"], "bold": 0, "text": " ", "ink": 0,
                })
                continue
            first = ink[0][0]
            if any(_contains(rect, first["bbox"]) for rect in skip_rects):
                continue
            frags.append({
                "y": first["origin"][1],
                "x0": first["bbox"][0],
                "x1": max(ch["bbox"][2] for ch, _ in ink),
                "size": Counter(round(span["size"], 1) for _, span in ink).most_common(1)[0][0],
                "bold": sum(1 for _, span in ink if _is_bold(span)),
                "text": "".join(ch["c"] for ch, _ in chars),
                "ink": len(ink),
            })

    frags.sort(key=lambda f: (f["y"], f["x0"]))
    grouped: list[dict] = []
    for frag in frags:
        if grouped and abs(frag["y"] - grouped[-1]["y"]) <= max(2.0, 0.4 * frag["size"]):
            grouped[-1]["frags"].append(frag)
        else:
            grouped.append({"y": frag["y"], "frags": [frag]})

    rows: list[Row] = []
    for group in grouped:
        ordered = sorted(group["frags"], key=lambda f: f["x0"])
        inked = [f for f in ordered if f["ink"]]
        if not inked:
            continue
        weights: Counter = Counter()
        for frag in inked:
            weights[frag["size"]] += frag["ink"]
        size = weights.most_common(1)[0][0]
        text = ""
        prev = None
        for frag in ordered:
            piece = frag["text"]
            if prev is not None and frag["x0"] - prev["x1"] > _SPACE_GAP * frag["size"]:
                if not text.endswith(" ") and not piece.startswith(" "):
                    text += " "
            text += piece
            if frag["ink"] and (prev is None or frag["x1"] > prev["x1"]):
                prev = frag
        text = re.sub(r"[  \t]+", " ", text).strip()
        if not text:
            continue
        ink_total = sum(f["ink"] for f in inked)
        rows.append(Row(
            page=page_number,
            y=group["y"],
            x0=inked[0]["x0"],
            x1=max(f["x1"] for f in inked),
            size=size,
            bold=sum(f["bold"] for f in inked) >= 0.8 * ink_total,
            text=text,
        ))
    return rows


def _is_bold(span) -> bool:
    return bool(span.get("flags", 0) & 16) or "bold" in span.get("font", "").lower()


def _contains(rect, bbox) -> bool:
    x0, y0, x1, y1 = rect
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    return x0 - 1 <= cx <= x1 + 1 and y0 - 1 <= cy <= y1 + 1


# -- tables --------------------------------------------------------------


def _clean_cell(value) -> str:
    if value is None:
        return ""
    text = re.sub(r"-\n(?=[a-z])", "-", str(value))
    return re.sub(r"\s+", " ", text).strip().replace("|", "/")


def page_tables(page) -> list[tuple[tuple, str]]:
    """Return ``(bbox, markdown)`` for ruled tables with a consistent shape.

    PyMuPDF reports merged cells as ``None`` columns; collapsing those gives
    the table's real shape. Anything that doesn't collapse to one consistent
    column count (tracked-change boxes in amendment PDFs do this) is left to
    the line reflow instead.
    """
    try:
        found = page.find_tables().tables
    except Exception:
        return []
    tables = []
    for table in found:
        rows = []
        for raw in table.extract():
            cells = [_clean_cell(cell) for cell in raw if cell is not None]
            cells = [cell for cell in cells]
            while cells and not cells[-1]:
                cells.pop()
            while cells and not cells[0]:
                cells.pop(0)
            if cells:
                rows.append(cells)
        if len(rows) < 2:
            continue
        widths = Counter(len(row) for row in rows)
        width, count = widths.most_common(1)[0]
        if width < 2 or count < len(rows) - 1:
            if width == 1 and count == len(rows):
                # A one-column "table" is a boxed list (Appendix 3's activity list).
                head, *items = [row[0] for row in rows]
                tables.append((tuple(table.bbox), "\n".join([head, *(f"• {item}" for item in items)])))
            continue
        rows = [row + [""] * (width - len(row)) if len(row) < width else row[:width] for row in rows]
        if width == 2 and all(row[0].endswith(":") for row in rows):
            # Proposer/Seconder/Passed boxes on amendment cover sheets.
            tables.append((tuple(table.bbox), "\n".join(f"{row[0]} {row[1]}".strip() for row in rows)))
            continue
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
        lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
        tables.append((tuple(table.bbox), "\n".join(lines)))
    return tables


# -- page furniture ------------------------------------------------------


def _is_leader(text: str) -> bool:
    return bool(_LEADER_RE.search(text))


def _norm(text: str) -> str:
    return re.sub(r"[^a-z]+", "", text.lower())


def _drop_furniture(pages: list[list[Row]]) -> list[list[Row]]:
    """Remove covers, contents pages, page numbers and running headers."""
    if not pages:
        return pages

    # Running headers/footers: the same (digit-stripped) text as the first or
    # last row of most pages.
    edge_counts: Counter = Counter()
    for rows in pages:
        for row in rows[:2] + rows[-2:]:
            key = _norm(re.sub(r"\d+", "", row.text))
            if key:
                edge_counts[key] += 1
    threshold = max(3, int(len(pages) * 0.5))
    running = {key for key, n in edge_counts.items() if n >= threshold} if len(pages) >= 4 else set()

    later_headings = {_norm(row.text) for rows in pages[1:] for row in rows if len(row.text) < 90}

    cleaned: list[list[Row]] = []
    for index, rows in enumerate(pages):
        kept = []
        for position, row in enumerate(rows):
            text = row.text.strip()
            at_edge = position < 2 or position >= len(rows) - 2
            if at_edge and _NUMBER_ONLY_RE.match(text):
                continue
            if _RULE_RE.match(text):
                continue
            if at_edge and _norm(re.sub(r"\d+", "", text)) in running:
                continue
            kept.append(row)
        rows = kept
        if not rows:
            continue

        leaders = sum(1 for row in rows if _is_leader(row.text))
        titled = any(re.match(r"^(table of )?contents\b", row.text, re.IGNORECASE) for row in rows[:4])
        article_refs = sum(1 for row in rows if re.search(r"\bArticles?\s+\d+(?:\s*[-–]\s*\d+)?$", row.text))
        if leaders >= 4 or (titled and (leaders >= 1 or article_refs >= 3)):
            continue  # contents page
        if index == 0 and len(pages) > 2:
            repeats = sum(1 for row in rows if _norm(row.text) in later_headings)
            longest = max(len(row.text) for row in rows)
            if repeats >= max(3, len(rows) * 0.5) or (len(rows) <= 15 and longest < 70):
                continue  # cover page, or a cover that lists the contents
        cleaned.append(rows)
    return cleaned


# -- rows → blocks -------------------------------------------------------


def _marker(row: Row) -> Optional[str]:
    match = _MARKER_RE.match(row.text)
    return match.group("marker") if match else None


def _heading_number_depth(text: str) -> int:
    match = re.match(r"^(\d{1,2}(?:\.\d{1,2})*)\.?\s", text)
    return len(match.group(1).split(".")) if match else 0


def _normalise_heading(text: str) -> str:
    byelaw = _BYELAW_HEADING_RE.match(text)
    if byelaw:
        number = re.sub(r"\s+", "", byelaw.group(1))
        return f"Bye-Law {number} — {byelaw.group(2).strip()}"
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_heading_text(text: str) -> bool:
    if len(text) > 110 or _is_leader(text):
        return False
    body = _MARKER_RE.sub("", text, count=1)
    if not body or not (body[0].isupper() or body[0].isdigit()):
        return False
    if body.endswith(":") and len(body.split()) > 5:
        return False  # "14.1 A Referendum may be called on any issue by:"
    return not re.search(r"[.;,]$", body)


# Tesseract slips seen on the SU's scanned regulations. Deliberately a closed
# list: this is legal text, so no general spelling correction.
_OCR_FIXES = [
    (re.compile(r"^(\d{1,2})-(\d{1,2})(?=[.\s])"), r"\1.\2"),  # "4-3 Club…" → "4.3 Club…"
    (re.compile(r"(?<![A-Za-z])\|f\b"), "If"),
    (re.compile(r"\b([Aa])(club|society|president|treasurer|member|representative|constitution|welfare)\b"), r"\1 \2"),
    (re.compile(r"\bano(?= confidence\b)"), "a no"),
    (re.compile(r"\bNew(clubs|societies)\b"), r"New \1"),
]


def _fix_ocr(text: str) -> str:
    for pattern, replacement in _OCR_FIXES:
        text = pattern.sub(replacement, text)
    return text


def rows_to_blocks(rows: list[Row], ocr: bool = False) -> list[Block]:
    if not rows:
        return []
    if ocr:
        for row in rows:
            row.text = _fix_ocr(row.text)
    text_rows = [row for row in rows if not row.text.startswith("\x00TABLE:")] or rows
    size_weights: Counter = Counter()
    for row in text_rows:
        size_weights[round(row.size)] += len(row.text)
    body_size = size_weights.most_common(1)[0][0]
    right_edge = sorted(row.x1 for row in text_rows)[int(len(text_rows) * 0.9)]
    # Bold is only a heading signal where it's the exception: the Bye-Laws PDF
    # sets its whole body in a bold-flagged font.
    bold_chars = sum(len(row.text) for row in text_rows if row.bold)
    bold_signals = bold_chars < 0.4 * sum(len(row.text) for row in text_rows)
    heading_sizes = sorted(
        {round(row.size) for row in text_rows if row.size >= body_size * 1.15 and _looks_like_heading_text(row.text)},
        reverse=True,
    )

    def heading_level(row: Row, prev: Optional[Row], nxt: Optional[Row]) -> Optional[int]:
        text = row.text
        if _BYELAW_HEADING_RE.match(text) and row.size >= body_size:
            return 2
        if not _looks_like_heading_text(text):
            return None
        if not ocr and round(row.size) in heading_sizes:
            return 2 if heading_sizes.index(round(row.size)) == 0 else 3
        wraps = row.x1 >= right_edge - 40
        continues_bold = prev is not None and prev.bold and prev.x1 >= right_edge - 40 and prev.page == row.page
        if not ocr and bold_signals and row.bold and not wraps and not continues_bold:
            if re.match(r"^(PART|SCHEDULE|APPENDIX)\b", text, re.IGNORECASE):
                return 2
            return 3
        if ocr or not heading_sizes:
            # Numbered heading with no terminal punctuation whose next line is
            # a deeper clause: "2.2 Activity Levels" → "2.2.1. Clubs and…".
            depth = _heading_number_depth(text)
            if depth and nxt is not None:
                next_depth = _heading_number_depth(nxt.text)
                title = re.sub(r"^[\d.]+\s+", "", text)
                short_title = len(title.split()) <= 10 and title[:1].isupper()
                if len(text) < 80 and (next_depth > depth or (ocr and short_title and depth <= 2)):
                    return 2 if depth == 1 else 3
        return None

    blocks: list[Block] = []
    stack: list[tuple[float, int]] = []  # (marker x, depth)
    heading_depth = 0
    current: Optional[Block] = None

    def flush():
        nonlocal current
        if current is not None:
            blocks.append(current)
            current = None

    for index, row in enumerate(rows):
        prev = rows[index - 1] if index else None
        nxt = rows[index + 1] if index + 1 < len(rows) else None

        if row.text.startswith("\x00TABLE:"):
            flush()
            blocks.append(Block(kind="table", text=row.text[len("\x00TABLE:"):]))
            continue

        level = heading_level(row, prev, nxt)
        if level is not None:
            text = _normalise_heading(row.text)
            if (
                current is not None and current.kind == "heading" and current.level == level
                and current.last is not None and current.last.page == row.page
                and row.y - current.last.y < row.size * 1.8
                and not _MARKER_RE.match(row.text)
                and (row.text[:1].islower() or re.search(r"(?:\b(?:and|of|for|the)|[&,–—-])$", current.text))
            ):
                current.text = f"{current.text} {text}"
                current.last = row
                continue
            if (
                current is not None and current.kind == "heading"
                and re.fullmatch(r"(PART|SCHEDULE|APPENDIX)\s+\w+", current.text, re.IGNORECASE)
                and text.isupper()
            ):
                current.text = f"{current.text.title()} — {text.title()}"
                current.last = row
                continue
            flush()
            current = Block(kind="heading", text=text, level=level, last=row)
            stack = []
            heading_depth = _heading_number_depth(row.text)
            continue

        marker = _marker(row)
        if marker and re.fullmatch(r"\d{1,2}", marker):
            # A bare number only counts at a clause column: "4 of Term 1."
            # wrapped from the previous line is indented like continuation text.
            column = current.marker_x if current is not None and current.kind == "para" and current.marker else None
            if column is None or abs(row.x0 - column) > 4:
                marker = None

        if marker:
            flush()
            if _DOTTED_RE.match(marker):
                depth = max(0, len(marker.rstrip(".").split(".")) - max(heading_depth, 1) - 1)
                stack = [entry for entry in stack if entry[1] < depth] + [(row.x0, depth)]
            else:
                while stack and row.x0 < stack[-1][0] - _INDENT_TOLERANCE:
                    stack.pop()
                if stack and abs(row.x0 - stack[-1][0]) <= _INDENT_TOLERANCE:
                    depth = stack[-1][1]
                    stack[-1] = (row.x0, depth)
                else:
                    depth = stack[-1][1] + 1 if stack else 0
                    stack.append((row.x0, depth))
            current = Block(
                kind="para", text=row.text, level=depth, marker=marker,
                marker_x=row.x0, last=row,
            )
            continue

        # Continuation or a fresh unnumbered paragraph.
        if current is not None and current.kind == "para" and current.last is not None:
            last = current.last
            same_page = last.page == row.page
            gap = row.y - last.y if same_page else 0
            ended = _SENTENCE_END_RE.search(last.text) is not None
            short = last.x1 < right_edge - max(40.0, (right_edge - last.x0) * 0.12)
            dedent = (
                current.cont_x is not None and row.x0 < current.cont_x - 6
            ) or (current.marker and current.cont_x is None and row.x0 <= current.marker_x + 3)
            new_para = (
                (same_page and gap > last.size * 1.9)
                or (ended and short)
                or (ended and dedent)
            )
            if not new_para:
                if current.cont_x is None:
                    current.cont_x = row.x0
                current.text = _join(current.text, row.text)
                current.last = row
                continue
            flush()
            depth = current_depth_for(stack, row.x0)
            current = Block(kind="para", text=row.text, level=depth, marker_x=row.x0, last=row)
            continue

        flush()
        current = Block(kind="para", text=row.text, level=current_depth_for(stack, row.x0), marker_x=row.x0, last=row)

    flush()
    return blocks


def current_depth_for(stack: list[tuple[float, int]], x: float) -> int:
    """Depth for an unnumbered paragraph: nested under the clause it sits in."""
    depth = 0
    for marker_x, marker_depth in stack:
        if x > marker_x + 4:
            depth = marker_depth + 1
    return depth


def _join(text: str, more: str) -> str:
    if re.search(r"[A-Za-z]-$", text) and more[:1].isalpha():
        return text + more  # "non-" + "visible", "Bye-" + "Laws"
    return f"{text} {more}"


def blocks_to_text(blocks: list[Block]) -> str:
    out = []
    for block in blocks:
        if block.kind == "heading":
            out.append(f"{'#' * block.level} {block.text}")
        elif block.kind == "table":
            out.append(block.text)
        else:
            text = re.sub(r"\s+", " ", block.text).strip()
            if text:
                out.append("  " * block.level + text)
    return "\n\n".join(out)


# -- document ------------------------------------------------------------


def _needs_ocr(pages_rows: list[list[Row]]) -> bool:
    chars = sum(len(row.text) for rows in pages_rows for row in rows)
    return chars < max(500, len(pages_rows) * 200)


def extract_structured_text(pdf_bytes: bytes) -> Optional[str]:
    """Structured plaintext for *pdf_bytes*, or None without PyMuPDF."""
    if pymupdf is None:
        return None
    document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pages_rows = [page_rows(page, number) for number, page in enumerate(document)]
    ocr = False
    if _needs_ocr(pages_rows):
        try:
            pages_rows = []
            for number, page in enumerate(document):
                textpage = page.get_textpage_ocr(language="eng", dpi=300, full=True)
                pages_rows.append(page_rows(page, number, textpage=textpage))
            ocr = True
        except Exception:
            # No Tesseract on this host: keep the sparse text layer rather
            # than losing the document.
            pass

    if not ocr:
        # Replace ruled tables with a single synthetic row at their position,
        # so they keep their place in the reading order.
        for number, page in enumerate(document):
            tables = page_tables(page)
            if not tables:
                continue
            rects = [bbox for bbox, _ in tables]
            rows = page_rows(page, number, skip_rects=rects)
            for bbox, markdown in tables:
                rows.append(Row(page=number, y=bbox[1], x0=bbox[0], x1=bbox[2], size=0, bold=False,
                                text=f"\x00TABLE:{markdown}"))
            rows.sort(key=lambda row: row.y)
            pages_rows[number] = rows

    pages_rows = _drop_furniture(pages_rows)
    rows = [row for page in pages_rows for row in page]
    return blocks_to_text(rows_to_blocks(rows, ocr=ocr))
