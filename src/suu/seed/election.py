"""Non-interactive election -> ucl-tools `Officer` + `CommitteeMember` seeding.

`suu scrape election` is built for a human at a terminal (it prompts to
disambiguate a name, opens a real browser window for first-time SU login).
This module is the scriptable counterpart driven by `suu seed election` — no
prompts, a name must resolve to exactly one election or this raises — so it
can run unattended from `ucl-suu-pipeline`'s `election-seed` task as well as
from a human's terminal.

Only winning candidates are seeded (these tables are a public accountability
tracker and a public roster, not an elections archive).

One scrape feeds **two** tables, split on `group_type`:

  * union-level positions (`is_officer_position`, i.e. `group_type ==
    "Union"`) -> `Officer` + `ManifestoPoint`, keyed `(name, role, year)`;
  * every society / club / network-committee position -> `CommitteeMember`,
    keyed `(societyName, role, memberName, year)`, soft-linked to an
    `Organiser` via `suu.seed.organisers`.

Seeding both here is what lets an election — the Leadership Race, or the
term-3 by-election that fills resigned and extra seats — land in one
unattended pass. The committee half previously went through a hand-exported
`committee_data_to_seed.json` and ucl-tools' `seed_committees.ts`, so it never
happened on a schedule at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from suu.scrape.browser import quit_driver
from suu.scrape.scrapers import (
    GenericElectionScraper,
    get_all_elections,
    is_officer_position,
)
from suu.seed import db
from suu.seed import organisers as org
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
    # Officer half.
    created: int = 0
    updated: int = 0
    superseded_removed: int = 0
    positions_skipped_no_winner: int = 0
    # CommitteeMember half.
    committee_created: int = 0
    committee_updated: int = 0
    committee_superseded_removed: int = 0
    organisers_linked: int = 0
    organisers_created: int = 0
    #: Seats where a by-election winner replaced the previous holder.
    displaced: int = 0
    #: (society, role) seats this run filled that already had more than one
    #: holder, so displacement refused to guess which one had left. Surfaced
    #: for a human rather than resolved — see `_displace_prior_holders`.
    displacement_ambiguous: list[str] = field(default_factory=list)


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


def _displace_prior_holders(
    client: Any,
    *,
    society_name: str,
    role: str,
    year: str,
    source_election: str,
    keep_ids: set[str],
    result: SeedResult,
) -> None:
    """Remove the previous holder of a seat this election has just refilled.

    This is the "roles that were resigned from" case. A resignation is
    **invisible in the election data**: the Leadership Race says Alice is
    Treasurer, Alice resigns, the by-election says Bob is Treasurer, and
    nothing anywhere records that Alice left. So displacement is an inference,
    and it is made only where the inference is safe.

    Safe means the seat had exactly one holder from a *different* election. If
    two or more people already hold (society, role), we cannot tell which one
    vacated — and blanket-removing them all would be destructive: 180 of the
    2,286 (society, role) pairs in 2026-27 have multiple holders, with
    Badminton Club running six Social Secretaries. Those are recorded in
    `displacement_ambiguous` for a human and otherwise left completely alone.

    That restriction costs almost nothing in practice: President and Treasurer
    — the seats by-elections actually refill — are never multi-holder in the
    2026-27 data. Only Vice President is, in 9 societies.

    Rows from *this* election are never displaced (`keep_ids`), so a genuine
    two-seat by-election doesn't have its own winners knock each other out.
    """
    holders = db.list_committee_holders(
        client, society_name=society_name, role=role, year=year
    )
    prior = [
        h
        for h in holders
        if h["id"] not in keep_ids and h.get("sourceElection") != source_election
    ]
    if not prior:
        return
    if len(prior) > 1:
        result.displacement_ambiguous.append(
            f"{society_name} — {role} ({len(prior)} prior holders: "
            f"{', '.join(h['memberName'] for h in prior)})"
        )
        return
    db.delete_committee_members(client, [prior[0]["id"]])
    result.displaced += 1


def seed_election(
    name_or_url: str,
    *,
    year: str,
    election_type: Optional[str] = None,
    source_election: Optional[str] = None,
    term_starts_at: Optional[str] = None,
    term_ends_at: Optional[str] = None,
    term_window: Optional[Any] = None,
    supersede: bool = False,
    seed_committees: bool = True,
    displace: Optional[bool] = None,
    resume: bool = False,
    dry_run: bool = False,
    progress: Optional[Any] = None,
) -> SeedResult:
    """Scrape NAME_OR_URL's winners into ucl-tools' `Officer` and `CommitteeMember`.

    `election_type` defaults to a best-effort guess from the URL (see
    `classify.guess_election_type`) but should normally be passed explicitly —
    the guess exists mainly so ad-hoc/manual runs don't have to think about it.

    `source_election` defaults to the resolved election URL and is the
    provenance every row is stamped with. `supersede` deletes rows tagged with
    that `sourceElection` + `year` that this run did *not* produce, in **both**
    tables — so re-running one election's seed fully replaces its own prior
    state and never touches another election's rows. That scoping is the whole
    reason a by-election can be re-seeded safely alongside the Leadership Race.

    `displace` handles the other half of a by-election: a seat whose previous
    holder resigned. It removes the prior occupant of a (society, role) this
    run refilled, but only where exactly one prior holder exists, because a
    resignation leaves no trace in the scraped data (see
    `_displace_prior_holders`). Defaults to on for `election_type ==
    "by-election"` and off otherwise — a Leadership Race re-run should replace
    its own rows via `supersede`, not evict anybody.

    `seed_committees` (default True) can be turned off to write only the
    union-level `Officer` rows, which is what the old behaviour effectively
    was.

    `term_window`, when given, is called as `term_window(category)` per officer
    and returns that officer's `(start, end)` — because the window is not
    uniform. Nearly everyone serves handover to handover, but a **student
    trustee serves a full 365 days**, and two of the four are elected in
    October rather than in the March Leadership Race, so their term straddles
    the handover into the next academic year. Passing a callable keeps that
    policy in `ucl-suu-pipeline`, which has the `AcademicYear` dates; this
    package only knows each position's category. `term_starts_at`/
    `term_ends_at` are the flat fallback when no callable is supplied.

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

    # Build the DB client BEFORE the scrape, not after.
    #
    # A full Leadership Race is ~2,100 positions and the better part of an
    # hour of browser work. Discovering missing credentials at the end of that
    # — which is what used to happen, because the client was created just
    # before the first write — throws the entire run away for a two-second
    # check. `get_client` only reads env vars and constructs a client; it
    # doesn't hold a connection open, so doing it early costs nothing.
    client = None if dry_run else db.get_client()

    scraper = GenericElectionScraper(selected["url"])
    try:
        scraped = scraper.scrape(
            include_tallies=True,
            winners_only=True,
            # A full Leadership Race is ~2,100 positions and takes the better
            # part of an hour of browser work. The scraper checkpoints after
            # every position regardless; `resume` is what lets a second run
            # read that back instead of starting over. Without it the
            # dry-run-then-apply sequence — the sensible way to use this —
            # pays for the same scrape twice.
            resume=resume,
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

    should_displace = (
        displace if displace is not None else resolved_type == "by-election"
    )

    seen_officer_ids: set[str] = set()
    seen_committee_ids: set[str] = set()
    # (societyName, role) seats this run filled — the displacement candidates.
    refilled_seats: set[tuple[str, str]] = set()

    # One lookup for the whole run rather than one per group: 395 groups
    # against ~440 organisers is a table scan either way, and doing it per
    # group would be 395 round trips.
    known_organisers = [] if dry_run else db.list_organisers(client)
    # Organisers created during this run must be visible to later groups, or a
    # society appearing twice in the scrape gets two rows (the second insert
    # would then fail the unique name constraint).
    organiser_cache: dict[str, Optional[str]] = {}

    def _organiser_for(
        group_name: str, group_type: str, group_link: Optional[str]
    ) -> Optional[str]:
        if group_name in organiser_cache:
            return organiser_cache[group_name]
        match = org.match_organiser(group_name, known_organisers)
        if match.organiser_id:
            result.organisers_linked += 1
            organiser_cache[group_name] = match.organiser_id
            return match.organiser_id
        created = db.create_organiser(
            client,
            name=group_name,
            type_=org.organiser_type(group_type),
            union_url=group_link,
        )
        known_organisers.append(
            {"id": created["id"], "name": created["name"], "type": created.get("type")}
        )
        result.organisers_created += 1
        organiser_cache[group_name] = created["id"]
        return created["id"]

    for position in scraped.get("positions", []):
        winners = [c for c in position.get("winners", []) if c.get("is_winner")]
        if not winners:
            result.positions_skipped_no_winner += 1
            continue

        role = position["title"]
        is_officer = is_officer_position(position)

        # Union-level positions were the only thing this function wrote, but it
        # never actually filtered on that — every society committee role went
        # into `Officer` too. The 2026-27 Officer table has 38 rows against
        # 2,492 committee rows, so an unfiltered run would have swamped the
        # accountability tracker by ~65x. The split is explicit now.
        if not is_officer and not seed_committees:
            continue

        for winner in winners:
            name = winner["name"]
            if progress:
                progress(role=role, name=name)

            if dry_run:
                continue

            if is_officer:
                category = category_slug(role)
                # Per-category, because a student trustee's 365-day term
                # doesn't line up with everyone else's handover-to-handover.
                officer_term_start, officer_term_end = (
                    term_window(category)
                    if term_window is not None
                    else (term_starts_at, term_ends_at)
                )
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
                    term_starts_at=officer_term_start,
                    term_ends_at=officer_term_end,
                )
                seen_officer_ids.add(officer["id"])
                result.updated += 1 if existing else 0
                result.created += 0 if existing else 1

                db.replace_manifesto_points(
                    client,
                    officer_id=officer["id"],
                    points=_campaign_points(winner.get("election_statement")),
                )
                continue

            group_name = position.get("group") or role
            group_type = position.get("group_type") or "Society"
            existing_cm = db.find_committee_member(
                client, society_name=group_name, role=role, member_name=name, year=year
            )
            member = db.upsert_committee_member(
                client,
                society_name=group_name,
                # Normalised, not raw: the scraper's "Other" (student media)
                # and "Network" fall outside CommitteeMember.groupType's
                # documented domain. See organisers.committee_group_type.
                group_type=org.committee_group_type(group_type),
                role=role,
                member_name=name,
                year=year,
                source_election=resolved_source,
                pronouns=winner.get("pronouns"),
                image_url=winner.get("image_url"),
                # The scraped election statement — this is what fills the
                # `manifesto` column that every 2026-27 committee row is
                # currently NULL on, because the old JSON-export route dropped
                # it before it ever reached the seeder.
                manifesto=winner.get("election_statement"),
                order=org.role_order(role),
                organiser_id=_organiser_for(
                    group_name, group_type, position.get("group_link")
                ),
            )
            seen_committee_ids.add(member["id"])
            refilled_seats.add((group_name, role))
            result.committee_updated += 1 if existing_cm else 0
            result.committee_created += 0 if existing_cm else 1

    if supersede and not dry_run:
        # Scoped to this election's own rows in both tables. A by-election
        # re-run therefore replaces only what the by-election produced and
        # leaves every Leadership Race row untouched — which only works
        # because `sourceElection` is populated. Rows predating that backfill
        # carry NULL and are invisible here, by design: silently adopting them
        # would let one election delete another's.
        stale_officers = (
            db.list_source_election_officer_ids(
                client, source_election=resolved_source, year=year
            )
            - seen_officer_ids
        )
        db.delete_officers(client, list(stale_officers))
        result.superseded_removed = len(stale_officers)

        if seed_committees:
            stale_committee = (
                db.list_source_election_committee_ids(
                    client, source_election=resolved_source, year=year
                )
                - seen_committee_ids
            )
            db.delete_committee_members(client, list(stale_committee))
            result.committee_superseded_removed = len(stale_committee)

    # Displacement runs after supersede so it only ever sees settled state,
    # and only over seats this run actually filled.
    if should_displace and seed_committees and not dry_run:
        for society_name, role in sorted(refilled_seats):
            _displace_prior_holders(
                client,
                society_name=society_name,
                role=role,
                year=year,
                source_election=resolved_source,
                keep_ids=seen_committee_ids,
                result=result,
            )

    return result
