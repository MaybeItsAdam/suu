import pytest

from suu.scrape.gov_text import (
    Row,
    _drop_furniture,
    _fix_ocr,
    blocks_to_text,
    extract_structured_text,
    rows_to_blocks,
)


def row(y, text, x0=72.0, x1=520.0, size=11.0, bold=False, page=0):
    return Row(page=page, y=y, x0=x0, x1=x1, size=size, bold=bold, text=text)


def render(rows, **kwargs):
    return blocks_to_text(rows_to_blocks(rows, **kwargs))


def test_bye_law_heading_is_normalised_and_clauses_split():
    text = render([
        row(10, "Bye - Law 1 0 - Staffing", size=16),
        row(30, "1. The Union shall employ staff to support its", x0=93),
        row(44, "work.", x0=107, x1=140),
        row(58, "2. Staff shall report to the Chief Executive.", x0=93, x1=330),
    ])
    assert text.splitlines()[0] == "## Bye-Law 10 — Staffing"
    assert "1. The Union shall employ staff to support its work." in text
    assert "\n\n2. Staff shall report to the Chief Executive." in text


def test_nested_markers_indent_by_column():
    text = render([
        row(10, "Bye-Law 3 - Student Networks", size=16),
        row(30, "1. Student Networks shall exist to:", x0=93, x1=300),
        row(44, "a. challenge discrimination.", x0=110, x1=260),
        row(58, "i. defend their rights.", x0=130, x1=240),
        row(72, "b. The Officer shall assist.", x0=110, x1=260),
    ])
    lines = [line for line in text.splitlines() if line]
    assert lines[2] == "  a. challenge discrimination."
    assert lines[3] == "    i. defend their rights."
    assert lines[4] == "  b. The Officer shall assist."


def test_bold_body_font_is_not_a_heading_signal():
    # The Bye-Laws PDF flags its entire body as bold.
    rows = [row(10 + 14 * i, f"{i + 1}. Clause text that wraps right to the margin of", x0=93, bold=True) for i in range(6)]
    rows.append(row(200, "Short bold line", x0=93, x1=180, bold=True))
    assert "#" not in render(rows)


def test_minority_bold_short_line_is_a_heading():
    rows = [row(10 + 14 * i, "Plain body text that runs all the way across the page.", x1=520) for i in range(10)]
    rows.insert(3, row(40.5, "5. Powers", x1=140, bold=True))
    assert "### 5. Powers" in render(rows)


def test_part_heading_merges_with_its_title():
    rows = [row(10 + 14 * i, "Body text that runs across the page for the statistics.", x1=520) for i in range(10)]
    rows[4:4] = [
        row(60.2, "PART 1", x0=277, x1=319, bold=True),
        row(74.2, "KEY CONSTITUTIONAL PROVISIONS", x0=189, x1=406, bold=True),
    ]
    assert "## Part 1 — Key Constitutional Provisions" in render(rows)


def test_long_clause_ending_in_colon_is_not_a_heading():
    rows = [row(10 + 14 * i, "Body text that runs across the page for the statistics.", x1=520) for i in range(10)]
    rows.insert(3, row(40.5, "14.1 A Referendum may be called on any issue by:", x1=330, bold=True))
    assert "#" not in render(rows)


def test_ocr_numbered_headings_and_fixups():
    text = render([
        row(10, "4-3 Club and Society General Meetings", x1=300),
        row(30, "4.3.1 |f apresident resigns, ano confidence motion may follow.", x1=520),
    ], ocr=True)
    assert text.startswith("### 4.3 Club and Society General Meetings")
    assert "If a president resigns, a no confidence motion may follow." in text


def test_ocr_fixes_are_a_closed_list():
    assert _fix_ocr("another piano abandoned") == "another piano abandoned"


CLAUSES = ["Membership is open.", "Officers are elected.", "Grants are allocated.", "Rooms are booked.", "Kit is insured."]


def test_contents_page_page_numbers_and_running_headers_are_dropped():
    pages = [
        [row(10, "Contents"), row(30, "1 Introduction ........ 5"), row(44, "2 General ........ 6")],
    ] + [
        [
            row(5, "Students' Union UCL Regulations"),
            row(30, clause, x1=200),
            row(800, str(n)),
        ]
        for n, clause in enumerate(CLAUSES, start=2)
    ]
    kept = [r.text for rows in _drop_furniture(pages) for r in rows]
    assert kept == CLAUSES


def test_extract_structured_text_round_trips_a_real_pdf():
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 80), "Bye-Law 1 - General", fontsize=16)
    page.insert_text((93, 110), "1. The Union is a company limited by guarantee.", fontsize=11)
    page.insert_text((93, 126), "2. Words and phrases have the meanings in the Articles.", fontsize=11)
    text = extract_structured_text(document.tobytes())
    assert text.splitlines()[0] == "## Bye-Law 1 — General"
    assert "1. The Union is a company limited by guarantee.\n\n2. Words" in text
