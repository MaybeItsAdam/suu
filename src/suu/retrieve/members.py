"""Retrieve society member rosters from Students' Union UCL."""

from __future__ import annotations

import re
from typing import Optional
import click

from suu.retrieve.common import (
    Retrieved,
    UnrecognisedPageError,
    cell_at,
    fetch_page_html,
    has_next_page,
    parse_html,
    read_rows,
    refuse_login_page,
)
from suu.retrieve.export import export_data, warn_first_page_only


def slugify_group(group_name: str) -> str:
    """Convert group title or URL into a web slug."""
    if group_name.startswith("http://") or group_name.startswith("https://"):
        match = re.search(r"/(?:group|user|organisation|content)/([^/]+)", group_name)
        if match:
            return match.group(1)
    return re.sub(r"[^a-z0-9]+", "-", group_name.lower()).strip("-")


def parse_members(html: str) -> Retrieved:
    """Read suu's guess at the members table: name, membership type, email, purchase date.

    Uses the shared refusal rule (login page, unrelated page or wrong-shaped table is an
    error). NOT the Connector's members parser: the Connector reads the verified
    ``/clubs-societies/<slug>/members`` roster (``lib/roster.js``); this still reads the
    unverified ``/group/<slug>/members``.
    """
    doc = parse_html(html)
    refuse_login_page(doc)
    if doc.select_one("table") is None:
        raise UnrecognisedPageError("members")
    rows = read_rows(
        doc,
        2,
        lambda cells: {
            "name": cells[0],
            "email": cell_at(cells, 2),
            "membership_type": cells[1],
            "purchase_date": cell_at(cells, 3),
        },
        "members",
    )
    return Retrieved(rows=rows, has_more=has_next_page(doc))


def fetch_members(
    group_name: str,
    auth_file: Optional[str] = None,
    headless: bool = True,
) -> Retrieved:
    """Fetch official member roster for a club or society using the saved login session."""
    slug = slugify_group(group_name)
    click.echo(f"Fetching member roster for '{group_name}'...")
    html = fetch_page_html(f"/group/{slug}/members", "members", auth_file=auth_file, headless=headless)
    result = parse_members(html)
    for row in result.rows:
        row["group"] = group_name
    return result


def retrieve_members_cmd(
    group_name: str,
    as_csv: bool = False,
    as_xlsx: bool = False,
    as_json: bool = False,
    as_sheets: bool = False,
    auth_file: Optional[str] = None,
) -> None:
    """CLI handler for `suu retrieve members`."""
    data = fetch_members(group_name, auth_file=auth_file)
    if data.has_more:
        warn_first_page_only("members")
    fieldnames = ["name", "email", "membership_type", "purchase_date", "group"]
    slug = slugify_group(group_name)
    export_data(
        rows=data.rows,
        fieldnames=fieldnames,
        prefix=f"members_{slug}",
        as_csv=as_csv,
        as_xlsx=as_xlsx,
        as_json=as_json,
        as_sheets=as_sheets,
    )
