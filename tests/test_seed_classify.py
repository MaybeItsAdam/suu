"""Verifies classify_category() against a real merged election dataset.

The 63 (title, category) pairs below are the actual positions from a merged
Leadership Race 2025 + Rep Elections 2025 + a January 2026 Societies Officer
by-election (source_elections in the original officer_data_to_seed.json) —
every SU portfolio is represented, including the "Societies Rep (Arts)"
title that overlaps two portfolio keywords and only passes if keyword
priority order is respected. Only titles + categories are kept (no winner
names/manifestos) since that's all classify_category() looks at.
"""

from suu.seed.classify import CATEGORY_SLUGS, category_slug, classify_category

PAIRS: list[tuple[str, str]] = [
    ("Activities & Engagement Officer", "Sabbatical Officers"),
    ("Education Officer", "Sabbatical Officers"),
    ("Equity & Inclusion Officer", "Sabbatical Officers"),
    ("Postgraduate Officer", "Sabbatical Officers"),
    ("Students' Union President", "Sabbatical Officers"),
    ("Welfare & Community Officer", "Sabbatical Officers"),
    ("Accommodation & Housing Officer", "Officers"),
    ("Disabled Students' Officer", "Officers"),
    ("International Students' Officer", "Officers"),
    ("LGBQ+ Officer", "Officers"),
    ("Mature, Part-Time & Carers Students' Officer", "Officers"),
    ("People of Colour (POC) Officer", "Officers"),
    ("Research Students' Officer", "Officers"),
    ("Social Class & Mobility Officer", "Officers"),
    ("Sustainability Officer", "Officers"),
    ("Trans Officer", "Officers"),
    ("UCL East Student Officer", "Officers"),
    ("Women's Officer", "Officers"),
    ("Student Trustee", "Student Trustees"),
    ("Sports Officer", "Sports"),
    ("Sports Rep", "Sports"),
    ("Arts Officer", "Arts"),
    ("Societies Rep (Arts)", "Arts"),
    ("Volunteering Officer", "Volunteering"),
    ("Volunteering Reps", "Volunteering"),
    ("Societies Officer", "Societies"),
    ("Societies Rep (Non-portfolio)", "Societies"),
    ("Societies Rep (Student Media)", "Societies"),
    ("Welfare Reps (Societies)", "Societies"),
    ("Hall Community Officer for Arthur Tattersall and John Tovell House", "Hall & Community"),
    ("Hall Community Officer for Astor College", "Hall & Community"),
    ("Hall Community Officer for Bernard Johnson House", "Hall & Community"),
    ("Hall Community Officer for Frances Gardner House and Langton Close", "Hall & Community"),
    ("Hall Community Officer for Ian Baker House and Ramsay Hall", "Hall & Community"),
    ("Hall Community Officer for New Hall - Caledonian Road", "Hall & Community"),
    ("Hall Community Officer for One Pool Street", "Hall & Community"),
    ("Hall Community Officer for Prankerd and Schafer House", "Hall & Community"),
    ("Hall Community Officer for Urbanest St Pancras", "Hall & Community"),
    (
        "Postgraduate Hall Community Officer for 109 Camden Road "
        "(Ann Stephenson, Ifor Evans, Max Rayne and Neil Sharp House)",
        "Hall & Community",
    ),
    (
        "Undergraduate Hall Community Officer for 109 Camden Road "
        "(Ann Stephenson, Ifor Evans, Max Rayne and Neil Sharp House)",
        "Hall & Community",
    ),
    ("Faculty of Arts and Humanities UG Rep", "Faculty Reps"),
    ("Faculty of Brain Sciences PGT Rep", "Faculty Reps"),
    ("Faculty of Brain Sciences UG Rep", "Faculty Reps"),
    ("Faculty of Engineering PGR Rep", "Faculty Reps"),
    ("Faculty of Engineering PGT Rep", "Faculty Reps"),
    ("Faculty of Engineering UG Rep", "Faculty Reps"),
    ("Faculty of Laws UG Rep", "Faculty Reps"),
    ("Faculty of Life Sciences PGT Rep", "Faculty Reps"),
    ("Faculty of Life Sciences UG Rep", "Faculty Reps"),
    ("Faculty of Mathematical and Physical Sciences PGT Rep", "Faculty Reps"),
    ("Faculty of Mathematical and Physical Sciences UG Rep", "Faculty Reps"),
    ("Faculty of Medical Sciences UG Rep (Non-Clinical)", "Faculty Reps"),
    ("Faculty of Population Health Sciences PGR Rep", "Faculty Reps"),
    ("Faculty of Population Health Sciences PGT Rep", "Faculty Reps"),
    ("Faculty of Population Health Sciences UG Rep", "Faculty Reps"),
    ("Faculty of Social and Historical Sciences PGT Rep", "Faculty Reps"),
    ("Faculty of Social and Historical Sciences UG Rep", "Faculty Reps"),
    ("Faculty of the Built Environment PGR Rep", "Faculty Reps"),
    ("Faculty of the Built Environment PGT Rep", "Faculty Reps"),
    ("Faculty of the Built Environment UG Rep", "Faculty Reps"),
    ("Institute of Education PGT Rep", "Faculty Reps"),
    ("Institute of Education UG Rep", "Faculty Reps"),
]


def test_classify_category_matches_real_election_dataset() -> None:
    for title, expected in PAIRS:
        assert classify_category(title) == expected, title


def test_category_slug_matches_seed_officers_ts_map_category() -> None:
    # Mirrors mapCategory()'s DB slugs in ucl-tools/scripts/seed_officers.ts.
    assert CATEGORY_SLUGS == {
        "Sabbatical Officers": "sabbs",
        "Officers": "officers",
        "Student Trustees": "trustees",
        "Hall & Community": "hall",
        "Faculty Reps": "faculty",
        "Sports": "sports",
        "Arts": "arts",
        "Volunteering": "volunteering",
        "Societies": "societies",
    }
    for title, expected_label in PAIRS:
        assert category_slug(title) == CATEGORY_SLUGS[expected_label]


def test_classify_category_default_fallback() -> None:
    assert classify_category("Some Brand New Officer Role") == "Officers"
