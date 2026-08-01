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
