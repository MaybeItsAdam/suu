"""Retrieve room & space booking request statuses from Students' Union UCL.

Kept in step with the Toolbox Connector's ``lib/retrieve/bookings.js``: same selectors,
same refusals, same columns. Fix a parser in both places.

UNVERIFIED against a real SU page. A real fixture must confirm:
  - the page lives at ``/group/<slug>/room-bookings``, with the same slug as the members
    page;
  - the requests are a ``<table>`` (suu used to also wait for ``.booking-list``);
  - every ``table tbody tr`` is one request, cells in the order reference, title, room,
    date, status (date and status optional);
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

BOOKINGS_FIELDS = ["booking_ref", "title", "room", "date", "status"]


def parse_bookings(html: str) -> Retrieved:
    """Read the room booking requests table; a missing status defaults to "Requested"."""
    doc = parse_html(html)
    refuse_login_page(doc)
    if doc.select_one("table") is None:
        raise UnrecognisedPageError("room bookings")
    rows = read_rows(
        doc,
        3,
        lambda cells: {
            "booking_ref": cells[0],
            "title": cells[1],
            "room": cells[2],
            "date": cell_at(cells, 3),
            "status": cell_at(cells, 4, "Requested"),
        },
        "room bookings",
    )
    return Retrieved(rows=rows, has_more=has_next_page(doc))


def fetch_bookings(
    group_name: str,
    auth_file: Optional[str] = None,
    headless: bool = True,
) -> Retrieved:
    """Fetch room booking requests for a club or society."""
    slug = slugify_group(group_name)
    click.echo(f"Fetching room booking requests for '{group_name}'...")
    html = fetch_page_html(f"/group/{slug}/room-bookings", "room bookings", auth_file=auth_file, headless=headless)
    result = parse_bookings(html)
    for row in result.rows:
        row["group"] = group_name
    return result


def retrieve_bookings_cmd(
    group_name: str,
    as_csv: bool = False,
    as_xlsx: bool = False,
    as_json: bool = False,
    as_sheets: bool = False,
    auth_file: Optional[str] = None,
) -> None:
    """CLI handler for `suu retrieve bookings`."""
    data = fetch_bookings(group_name, auth_file=auth_file)
    if data.has_more:
        warn_first_page_only("room booking requests")
    export_data(
        rows=data.rows,
        fieldnames=[*BOOKINGS_FIELDS, "group"],
        prefix=f"bookings_{slugify_group(group_name)}",
        as_csv=as_csv,
        as_xlsx=as_xlsx,
        as_json=as_json,
        as_sheets=as_sheets,
    )
