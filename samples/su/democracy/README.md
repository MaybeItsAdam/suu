# su/democracy — zone, papers-archive and policy pages (real, trimmed)

- **Pages**:
  - `zone_{az,ez,wcz,ue}.html` — `https://studentsunionucl.org/make-a-change/zones/<slug>`
    (`activities-zone`, `education-zone`, `welfare-community-zone`, `union-executive`);
    the meeting cards come from the page's inline directory JSON.
  - `archive.html` — `https://studentsunionucl.org/democracy-minutes-and-papers-archive`.
  - `policy_{current,lapsed}_p0.html` — `https://studentsunionucl.org/policy` filtered
    by status, first page.
  - `policy_up<code>.html` — single policy pages (`UP1908`, `UP2301`, `UP2508`).
  - `event_ue2601.html` — a meeting's What's On page
    (`/whats-on/representation/union-executive-meeting-1?v=95616`), cut to its main
    content block; it links `UE2601 Agenda and Papers.pdf` (captured 2026-10-05, when
    the archive had no 2026-27 UE entries yet).
  - `login_wall.html` — what a signed-out request gets instead; must raise
    `DemocracyPageError`.
- **Real or synthetic**: real, trimmed (large page chrome removed; the markers the
  parsers look for kept).
- **Captured**: 2026-09-25.
- **Redacted**: no — public pages; officer names on them are published by the SU.
- **Read by**: `tests/test_democracy.py` (`suu.scrape.democracy`). The archive's known
  dirt (wrong-meeting links, stale `data-id`s, year typos) is deliberate — it is pinned
  by the tests. No other repo copies these.
