"""Retrieve ticket sales and door lists for Students' Union UCL events.

Kept in step with the Toolbox Connector's ``lib/retrieve/sales.js``: same selectors,
same refusals, same columns. Fix a parser in both places.

UNVERIFIED against a real SU page, and the least likely of the retrievers to be right:
it reads the *events list* URL (``/group/<slug>/events``) but parses its rows as ticket
buyers. A real events list more plausibly lists events, with buyers on a per-event sales
page. ``--event`` only labels the rows; it does not select an event. A real fixture must
confirm:
  - which page actually carries buyers — ``/group/<slug>/events`` or a per-event page,
    and if the latter, how its URL is found;
  - buyers are a ``<table>``, every ``table tbody tr`` one ticket, cells in the order
    buyer name, ticket tier, email, ticket code (code optional);
  - no other table on the page, and whether the list is paged.
"""

from __future__ import annotations

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
from suu.retrieve.members import slugify_group

SALES_FIELDS = ["buyer_name", "ticket_tier", "email", "ticket_code"]


def parse_sales(html: str) -> Retrieved:
    """Read the buyer table: name, tier, email and optional ticket code per row."""
    doc = parse_html(html)
    refuse_login_page(doc)
    if doc.select_one("table") is None:
        raise UnrecognisedPageError("event sales")
    rows = read_rows(
        doc,
        3,
        lambda cells: {
            "buyer_name": cells[0],
            "ticket_tier": cells[1],
            "email": cells[2],
            "ticket_code": cell_at(cells, 3),
        },
        "event sales",
    )
    return Retrieved(rows=rows, has_more=has_next_page(doc))


def fetch_sales(
    group_name: str,
    event_name: Optional[str] = None,
    auth_file: Optional[str] = None,
    headless: bool = True,
) -> Retrieved:
    """Fetch ticket purchaser / door list records for an event."""
    slug = slugify_group(group_name)
    click.echo(f"Fetching sales and door list for '{group_name}'...")
    html = fetch_page_html(f"/group/{slug}/events", "event sales", auth_file=auth_file, headless=headless)
    result = parse_sales(html)
    for row in result.rows:
        row["group"] = group_name
        row["event"] = event_name or "All Events"
    return result


def retrieve_sales_cmd(
    group_name: str,
    event_name: Optional[str] = None,
    as_csv: bool = False,
    as_xlsx: bool = False,
    as_json: bool = False,
    as_sheets: bool = False,
    auth_file: Optional[str] = None,
) -> None:
    """CLI handler for `suu retrieve sales`."""
    data = fetch_sales(group_name, event_name=event_name, auth_file=auth_file)
    if data.has_more:
        warn_first_page_only("ticket sales")
    slug = slugify_group(group_name)
    event_slug = slugify_group(event_name) if event_name else "all"
    export_data(
        rows=data.rows,
        fieldnames=[*SALES_FIELDS, "group", "event"],
        prefix=f"sales_{slug}_{event_slug}",
        as_csv=as_csv,
        as_xlsx=as_xlsx,
        as_json=as_json,
        as_sheets=as_sheets,
    )
