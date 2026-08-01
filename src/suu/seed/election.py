"""Non-interactive election -> ucl-tools `Officer` table seeding.

`suu scrape election` is built for a human at a terminal (it prompts to
disambiguate a name, opens a real browser window for first-time SU login).
This module is the scriptable counterpart driven by `suu seed election` — no
prompts, a name must resolve to exactly one election or this raises — so it
can run unattended from `ucl-suu-pipeline`'s `election-seed` task as well as
from a human's terminal.

Only winning candidates are seeded (this table is a public accountability
tracker, not an elections archive) into `Officer` (+ `ManifestoPoint`), keyed
on the `(name, role, year)` compound unique constraint, via `suu.seed.db`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from suu.scrape.browser import quit_driver
from suu.scrape.scrapers import GenericElectionScraper, get_all_elections
from suu.seed import db
from suu.seed.classify import category_slug, guess_election_type

VALID_ELECTION_TYPES = ("leadership", "reps", "by-election")


class ElectionResolutionError(Exception):
    """Raised when NAME doesn't resolve to exactly one election (non-interactive)."""


@dataclass
class SeedResult:
    election_title: str
    election_url: str
    year: str
    election_type: str
    source_election: str
    created: int = 0
    updated: int = 0
    superseded_removed: int = 0
    positions_skipped_no_winner: int = 0


def resolve_election(name_or_url: str) -> dict[str, str]:
    """Resolve NAME to exactly one `{"title", "url"}`, or raise `ElectionResolutionError`.

    A bare https:// URL is used directly without a search (mirrors `suu scrape
    election`'s behaviour for direct links).
    """
    if name_or_url.startswith("http://") or name_or_url.startswith("https://"):
        return {"title": name_or_url, "url": name_or_url}

    all_elections: list[dict[str, str]] = []
    page = 0
    while True:
        page_results = get_all_elections(page=page)
        if not page_results:
            break
        all_elections.extend(page_results)
        matches = [e for e in all_elections if name_or_url.lower() in e["title"].lower()]
        if len(matches) == 1:
            return matches[0]
        page += 1

    matches = [e for e in all_elections if name_or_url.lower() in e["title"].lower()]
    if not matches:
        raise ElectionResolutionError(f"No election matched {name_or_url!r}.")
    titles = "\n".join(f"  - {m['title']} ({m['url']})" for m in matches)
    raise ElectionResolutionError(
        f"{name_or_url!r} matched {len(matches)} elections — pass a direct URL instead:\n{titles}"
    )


def _election_margin(candidate: dict[str, Any]) -> Optional[str]:
    final_tally = candidate.get("final_tally") or 0
    if final_tally > 0:
        return f"Won with {round(final_tally)} votes"
    return None


def _campaign_points(election_statement: Optional[str]) -> list[str]:
    """Split a manifesto blob into discrete points — one per non-empty line.

    The scraper only exposes a single `election_statement` string; there is
    no structured points list to consume, so this is a heuristic, not a
    guarantee every candidate's statement is formatted this way.
    """
    if not election_statement:
        return []
    return [line.strip(" \t-–—") for line in election_statement.splitlines() if line.strip()]


def seed_election(
    name_or_url: str,
    *,
    year: str,
    election_type: Optional[str] = None,
    source_election: Optional[str] = None,
    term_starts_at: Optional[str] = None,
    term_ends_at: Optional[str] = None,
    supersede: bool = False,
    dry_run: bool = False,
    progress: Optional[Any] = None,
) -> SeedResult:
    """Scrape NAME_OR_URL's winners and upsert them into ucl-tools' `Officer` table.

    `election_type` defaults to a best-effort guess from the URL (see
    `classify.guess_election_type`) but should normally be passed explicitly —
    the guess exists mainly so ad-hoc/manual runs don't have to think about it.
    `source_election` defaults to the resolved election URL; `--supersede`
    deletes any existing `Officer` rows tagged with that `sourceElection` +
    `year` that this run did *not* produce, so re-running an election's seed
    fully replaces its prior state without touching other elections' rows.
    `term_starts_at`/`term_ends_at` (ISO date strings) are left `None` unless
    passed explicitly — NULL means "always current, until backfilled" per the
    `Officer` schema doc. Computing real term windows needs `AcademicYear`/
    `CalendarEvent` context this package doesn't have; that's
    `ucl-suu-pipeline`'s `election-seed` task's job, which already manages
    those tables and can pass the dates in here.
    """
    selected = resolve_election(name_or_url)
    resolved_type = election_type or guess_election_type(selected["url"])
    if resolved_type not in VALID_ELECTION_TYPES:
        raise ValueError(
            f"election_type must be one of {VALID_ELECTION_TYPES} "
            f"(got {resolved_type!r} — pass --election-type explicitly)"
        )
    resolved_source = source_election or selected["url"]

    scraper = GenericElectionScraper(selected["url"])
    try:
        scraped = scraper.scrape(
            include_tallies=True,
            winners_only=True,
        )
    finally:
        quit_driver()

    result = SeedResult(
        election_title=selected["title"],
        election_url=selected["url"],
        year=year,
        election_type=resolved_type,
        source_election=resolved_source,
    )

    client = None if dry_run else db.get_client()
    seen_officer_ids: set[str] = set()

    for position in scraped.get("positions", []):
        winners = [c for c in position.get("winners", []) if c.get("is_winner")]
        if not winners:
            result.positions_skipped_no_winner += 1
            continue

        role = position["title"]
        category = category_slug(role)

        for winner in winners:
            name = winner["name"]
            if progress:
                progress(role=role, name=name)

            if dry_run:
                continue

            existing = db.find_officer(client, name=name, role=role, year=year)
            officer = db.upsert_officer(
                client,
                name=name,
                role=role,
                category=category,
                year=year,
                election_type=resolved_type,
                source_election=resolved_source,
                image_url=winner.get("image_url"),
                election_margin=_election_margin(winner),
                manifesto=winner.get("election_statement"),
                term_starts_at=term_starts_at,
                term_ends_at=term_ends_at,
            )
            seen_officer_ids.add(officer["id"])
            if existing:
                result.updated += 1
            else:
                result.created += 1

            db.replace_manifesto_points(
                client,
                officer_id=officer["id"],
                points=_campaign_points(winner.get("election_statement")),
            )

    if supersede and not dry_run:
        existing_ids = db.list_source_election_officer_ids(
            client, source_election=resolved_source, year=year
        )
        stale_ids = existing_ids - seen_officer_ids
        db.delete_officers(client, list(stale_ids))
        result.superseded_removed = len(stale_ids)

    return result
