# su/democracy — zone, papers-archive and policy pages (real, trimmed)

- **Pages**:
  - `zone_{az,ez,wcz,ue}.html` — `https://studentsunionucl.org/make-a-change/zones/<slug>`
    (`activities-zone`, `education-zone`, `welfare-community-zone`, `union-executive`);
    the meeting cards come from the page's inline directory JSON.
  - `archive.html` — `https://studentsunionucl.org/democracy-minutes-and-papers-archive`.
  - `policy_{current,lapsed}_p0.html` — `https://studentsunionucl.org/policy` filtered
    by status, first page.
  - `policy_up<code>.html` — single policy pages (`UP1908`, `UP2301`, `UP2508`).
  - `login_wall.html` — what a signed-out request gets instead; must raise
    `DemocracyPageError`.
- **Real or synthetic**: real, trimmed (large page chrome removed; the markers the
  parsers look for kept).
- **Captured**: 2026-09-25.
- **Redacted**: no — public pages; officer names on them are published by the SU.
- **Read by**: `tests/test_democracy.py` (`suu.scrape.democracy`). The archive's known
  dirt (wrong-meeting links, stale `data-id`s, year typos) is deliberate — it is pinned
  by the tests. No other repo copies these.
