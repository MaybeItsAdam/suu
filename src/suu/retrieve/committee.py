"""Retrieve registered committee roster for a Students' Union UCL club or society.

Kept in step with the Toolbox Connector's ``lib/retrieve/committee.js``: same selectors,
same refusals, same columns. Fix a parser in both places.

UNVERIFIED against a real SU page. A real fixture must confirm:
  - the page lives at ``/group/<slug>/committee``, with the same slug as the members page;
  - the committee is a ``<table>`` (suu used to also wait for ``.committee-list``, which
    suggests it may be a list instead — if so this parser refuses the page);
  - every ``table tbody tr`` is one committee member, cells in the order role, name,
    email (email optional);
  - no other table on the page.
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

COMMITTEE_FIELDS = ["role", "name", "email"]


def parse_committee(html: str) -> Retrieved:
    """Read the committee table: role, name and optional email per row."""
    doc = parse_html(html)
    refuse_login_page(doc)
    if doc.select_one("table") is None:
        raise UnrecognisedPageError("committee")
    rows = read_rows(
        doc,
        2,
        lambda cells: {"role": cells[0], "name": cells[1], "email": cell_at(cells, 2)},
        "committee",
    )
    return Retrieved(rows=rows, has_more=has_next_page(doc))


def fetch_committee(
    group_name: str,
    auth_file: Optional[str] = None,
    headless: bool = True,
) -> Retrieved:
    """Fetch registered committee members for a club or society."""
    slug = slugify_group(group_name)
    click.echo(f"Fetching committee lineup for '{group_name}'...")
    html = fetch_page_html(f"/group/{slug}/committee", "committee", auth_file=auth_file, headless=headless)
    result = parse_committee(html)
    for row in result.rows:
        row["group"] = group_name
    return result


def retrieve_committee_cmd(
    group_name: str,
    as_csv: bool = False,
    as_xlsx: bool = False,
    as_json: bool = False,
    as_sheets: bool = False,
    auth_file: Optional[str] = None,
) -> None:
    """CLI handler for `suu retrieve committee`."""
    data = fetch_committee(group_name, auth_file=auth_file)
    if data.has_more:
        warn_first_page_only("committee")
    export_data(
        rows=data.rows,
        fieldnames=[*COMMITTEE_FIELDS, "group"],
        prefix=f"committee_{slugify_group(group_name)}",
        as_csv=as_csv,
        as_xlsx=as_xlsx,
        as_json=as_json,
        as_sheets=as_sheets,
    )
