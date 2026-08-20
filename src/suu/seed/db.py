"""Raw Supabase writes into ucl-tools' `Officer` / `ManifestoPoint` tables.

ucl-tools is the schema's source of truth (see its `prisma/schema.prisma` and
`prisma/AGENTS.md`) — this module writes to the same tables `scripts/seed_officers.ts`
does, via the Supabase REST API rather than Prisma, since this package can't
depend on a generated Prisma client. Column names/types must be kept in sync
with that schema by hand.

Two things Prisma normally does for you that this module must do explicitly:
  - `Officer.id` / `ManifestoPoint.id` have no database-level default (Prisma
    generates `cuid()` client-side) — every insert here generates one.
  - `Officer.updatedAt` has no database-level default either (`@updatedAt` is
    Prisma-client-managed) — every write here sets it explicitly.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

from cuid import cuid
from supabase import Client, create_client

OFFICER_TABLE = "Officer"
MANIFESTO_POINT_TABLE = "ManifestoPoint"


def get_client() -> Client:
    """Build a Supabase client from env vars.

    Prefers the service-role key (bypasses RLS, needed for these writes),
    falling back through the same names the `scrape --upload` plugin and
    `.env.example` use respectively, so either convention works.
    """
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY")
        or os.getenv("SUPABASE_KEY")
    )
    if not url or not key:
        raise RuntimeError(
            "Missing Supabase credentials — set NEXT_PUBLIC_SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_URL/SUPABASE_KEY)."
        )
    return create_client(url, key)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_officer(client: Client, *, name: str, role: str, year: str) -> Optional[dict[str, Any]]:
    """Look up an Officer by the (name, role, year) compound unique key."""
    res = (
        client.table(OFFICER_TABLE)
        .select("id")
        .eq("name", name)
        .eq("role", role)
        .eq("year", year)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def upsert_officer(
    client: Client,
    *,
    name: str,
    role: str,
    category: str,
    year: str,
    election_type: str,
    source_election: Optional[str],
    image_url: Optional[str],
    election_margin: Optional[str],
    manifesto: Optional[str],
    term_starts_at: Optional[str],
    term_ends_at: Optional[str],
) -> dict[str, Any]:
    """Find-then-write on (name, role, year), preserving the row's `id` on update.

    Deliberately not a single PostgREST `on_conflict` upsert: that would
    include every payload column (including a freshly generated `id`) in the
    `ON CONFLICT DO UPDATE SET`, silently reassigning the existing officer's
    primary key on every re-seed. Mirrors the find-first pattern
    `scripts/seed_officers.ts` already uses for the same reason.
    """
    existing = find_officer(client, name=name, role=role, year=year)
    payload = {
        "name": name,
        "role": role,
        "category": category,
        "year": year,
        "electionType": election_type,
        "sourceElection": source_election,
        "imageUrl": image_url,
        "electionMargin": election_margin,
        "manifesto": manifesto,
        "termStartsAt": term_starts_at,
        "termEndsAt": term_ends_at,
        "updatedAt": _now_iso(),
    }

    if existing:
        res = (
            client.table(OFFICER_TABLE)
            .update(payload)
            .eq("id", existing["id"])
            .execute()
        )
        return res.data[0]

    payload["id"] = cuid()
    res = client.table(OFFICER_TABLE).insert(payload).execute()
    return res.data[0]


def replace_manifesto_points(client: Client, *, officer_id: str, points: list[str]) -> None:
    """Insert manifesto points only if this officer currently has none.

    Mirrors `scripts/seed_officers.ts`: `ManifestoVote` rows reference a
    specific `ManifestoPoint.id`, so re-seeding must never delete/recreate
    points that already have votes attached — it would silently orphan them.
    """
    if not points:
        return
    existing = (
        client.table(MANIFESTO_POINT_TABLE)
        .select("id")
        .eq("officerId", officer_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        return

    rows = [
        {"id": cuid(), "officerId": officer_id, "text": text, "order": i}
        for i, text in enumerate(points)
    ]
    client.table(MANIFESTO_POINT_TABLE).insert(rows).execute()


def list_source_election_officer_ids(
    client: Client, *, source_election: str, year: str
) -> set[str]:
    """All Officer ids currently tagged with this `sourceElection` + `year` — for `--supersede`."""
    res = (
        client.table(OFFICER_TABLE)
        .select("id")
        .eq("sourceElection", source_election)
        .eq("year", year)
        .execute()
    )
    return {row["id"] for row in res.data}


def delete_officers(client: Client, ids: list[str]) -> None:
    """Delete Officer rows by id. Cascades to their ManifestoPoint/ManifestoVote rows."""
    if not ids:
        return
    client.table(OFFICER_TABLE).delete().in_("id", ids).execute()


# ---------------------------------------------------------------------------
# CommitteeMember / Organiser
#
# The society-committee half of an election. `Officer` is the union-level
# accountability tracker (38 rows for 2026-27); `CommitteeMember` is the
# per-society roster (2,492 rows for the same election). Both come out of the
# same scrape, so seeding them together is what makes an election's results
# land in one pass — see `election.seed_election`.
# ---------------------------------------------------------------------------

COMMITTEE_TABLE = "CommitteeMember"
ORGANISER_TABLE = "Organiser"


def list_organisers(client: Client) -> list[dict[str, Any]]:
    """Every Organiser's id/name/type, for `organisers.match_organiser`."""
    res = client.table(ORGANISER_TABLE).select("id,name,type").execute()
    return res.data or []


def create_organiser(client: Client, *, name: str, type_: str) -> dict[str, Any]:
    """Create an Organiser for a group that ran but has no row yet.

    `slug`/`instagram`/`logoUrl`/`color` are deliberately left NULL — this
    knows the name and nothing else. ucl-tools' `seed-organiser-slugs.ts`,
    `seed-logos.ts` and `seed-colors.ts` fill them in afterwards.

    Find-then-insert on the unique `name`, for the same reason
    `upsert_officer` does it: a PostgREST on_conflict upsert would put a
    freshly generated `id` in the DO UPDATE SET and reassign the existing
    organiser's primary key, orphaning every row that references it.
    """
    existing = (
        client.table(ORGANISER_TABLE).select("id,name,type").eq("name", name).limit(1).execute()
    )
    if existing.data:
        return existing.data[0]
    payload = {"id": cuid(), "name": name, "type": type_}
    res = client.table(ORGANISER_TABLE).insert(payload).execute()
    return res.data[0]


def find_committee_member(
    client: Client, *, society_name: str, role: str, member_name: str, year: str
) -> Optional[dict[str, Any]]:
    """Look up by the (societyName, role, memberName, year) compound unique key."""
    res = (
        client.table(COMMITTEE_TABLE)
        .select("id")
        .eq("societyName", society_name)
        .eq("role", role)
        .eq("memberName", member_name)
        .eq("year", year)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def upsert_committee_member(
    client: Client,
    *,
    society_name: str,
    group_type: str,
    role: str,
    member_name: str,
    year: str,
    source_election: Optional[str],
    pronouns: Optional[str],
    image_url: Optional[str],
    manifesto: Optional[str],
    order: int,
    organiser_id: Optional[str],
) -> dict[str, Any]:
    """Find-then-write on the compound key, preserving `id` on update.

    `userId` is never written here: it's a display-only auto-link to a matching
    User and, per the schema, never grants permissions. Overwriting it from a
    scrape would drop a link an admin's approval established.
    """
    existing = find_committee_member(
        client, society_name=society_name, role=role, member_name=member_name, year=year
    )
    payload = {
        "groupType": group_type,
        "pronouns": pronouns,
        "imageUrl": image_url,
        "manifesto": manifesto,
        "sourceElection": source_election,
        "order": order,
        "organiserId": organiser_id,
        "updatedAt": _now_iso(),
    }
    if existing:
        res = client.table(COMMITTEE_TABLE).update(payload).eq("id", existing["id"]).execute()
        return res.data[0]

    payload.update(
        {
            "id": cuid(),
            "societyName": society_name,
            "role": role,
            "memberName": member_name,
            "year": year,
        }
    )
    res = client.table(COMMITTEE_TABLE).insert(payload).execute()
    return res.data[0]


def list_source_election_committee_ids(
    client: Client, *, source_election: str, year: str
) -> set[str]:
    """All CommitteeMember ids tagged with this `sourceElection` + `year` — for `--supersede`."""
    res = (
        client.table(COMMITTEE_TABLE)
        .select("id")
        .eq("sourceElection", source_election)
        .eq("year", year)
        .execute()
    )
    return {row["id"] for row in res.data}


def list_committee_holders(
    client: Client, *, society_name: str, role: str, year: str
) -> list[dict[str, Any]]:
    """Everyone currently holding one (society, role) seat this year.

    Used by by-election displacement to answer "was this a single-holder seat?"
    before removing the previous occupant — see `election._displace_superseded`.
    """
    res = (
        client.table(COMMITTEE_TABLE)
        .select("id,memberName,sourceElection")
        .eq("societyName", society_name)
        .eq("role", role)
        .eq("year", year)
        .execute()
    )
    return res.data or []


def delete_committee_members(client: Client, ids: list[str]) -> None:
    """Delete CommitteeMember rows by id."""
    if not ids:
        return
    client.table(COMMITTEE_TABLE).delete().in_("id", ids).execute()
