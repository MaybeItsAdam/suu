"""Maps a scraped election position title to ucl-tools' `Officer.category`.

`GenericElectionScraper` (see `suu.scrape.scrapers`) only knows `title` /
`group` / `group_type` — it has no notion of the SU's officer/portfolio
hierarchy. ucl-tools' `scripts/seed_officers.ts` expects a category *label*
(e.g. "Sports") on each position and maps that label to a DB slug via its own
`mapCategory()`; this module is the missing upstream piece that produces that
label from a raw scraped title.

The rules below were reverse-engineered from a real merged Leadership
Race + Rep Elections + by-election dataset (63 positions, every SU portfolio
represented) and are verified against that exact dataset in
`tests/test_classify.py` — treat that test as the source of truth if a new
election title doesn't classify the way you expect.
"""

from __future__ import annotations

# Mirrors mapCategory()'s DB slugs in ucl-tools/scripts/seed_officers.ts.
CATEGORY_SLUGS: dict[str, str] = {
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

# The full-time sabbatical officer titles are a small, fixed constitutional
# set — matched exactly rather than by keyword, since e.g. "Education Officer"
# has no other distinguishing feature from the liberation/identity officers.
_SABB_TITLES = {
    "Students' Union President",
    "Activities & Engagement Officer",
    "Education Officer",
    "Equity & Inclusion Officer",
    "Postgraduate Officer",
    "Welfare & Community Officer",
}

# Checked in order — collisions to watch for:
#   - "Faculty" must come before "Arts": "Faculty of Arts and Humanities UG
#     Rep" contains both, and is Faculty Reps, not Arts.
#   - The Institute of Education is organisationally a faculty-equivalent at
#     UCL, so its reps are Faculty Reps too despite the title saying
#     "Institute" rather than "Faculty".
#   - A portfolio keyword wins over the generic "Societies" catch-all, e.g.
#     "Societies Rep (Arts)" is Arts, not Societies.
_PORTFOLIO_KEYWORDS: list[tuple[str, str]] = [
    ("Faculty", "Faculty Reps"),
    ("Institute of Education", "Faculty Reps"),
    ("Sports", "Sports"),
    ("Arts", "Arts"),
    ("Volunteering", "Volunteering"),
    ("Hall", "Hall & Community"),
    ("Societies", "Societies"),
]


def classify_category(title: str) -> str:
    """Return the category *label* (e.g. "Sports") for a scraped position title."""
    if title in _SABB_TITLES:
        return "Sabbatical Officers"
    if "Trustee" in title:
        return "Student Trustees"
    for keyword, category in _PORTFOLIO_KEYWORDS:
        if keyword in title:
            return category
    return "Officers"


def category_slug(title: str) -> str:
    """Return the DB category slug (e.g. "sports") directly for a scraped position title."""
    return CATEGORY_SLUGS[classify_category(title)]


# ---------------------------------------------------------------------------
# Election type
# ---------------------------------------------------------------------------

_ELECTION_TYPE_URL_HINTS: list[tuple[str, str]] = [
    ("by-election", "by-election"),
    ("leadership-race", "leadership"),
    ("rep-election", "reps"),
]


def guess_election_type(url: str) -> "str | None":
    """Best-effort `Officer.electionType` guess from an election URL/name.

    Always overridable via `--election-type` — this is a convenience default,
    not a source of truth (SU election URLs aren't a stable contract).
    """
    lowered = url.lower()
    for hint, election_type in _ELECTION_TYPE_URL_HINTS:
        if hint in lowered:
            return election_type
    return None
