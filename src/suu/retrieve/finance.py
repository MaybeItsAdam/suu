"""Retrieve financial account balances and payment request statuses from Students' Union UCL.

Kept in step with the Toolbox Connector's ``lib/retrieve/finance.js``: same selectors,
same refusals, same columns. Fix a parser in both places.

UNVERIFIED against a real SU page. The selectors look guessed, and no one has captured
this page yet. A real fixture must confirm:
  - the page lives at ``/group/<slug>/finance``, with the same slug as the members page;
  - the grant (account 10) balance is an element matching ``.grant-account-balance`` or
    ``[data-account='grant']``;
  - the subs (account 11) balance matches ``.subs-account-balance`` or
    ``[data-account='subs']``;
  - every ``table tbody tr`` on the page is a request, with cells in the order request
    id, title, amount, status, date (status and date optional) — so no other table on
    the page, and no header cells inside ``<tbody>``;
  - whether the list is paged (only the first page is read).

A balance that isn't on the page is ``None``, not "£0.00": a made-up zero would show an
empty account where the truth is "couldn't read it".
"""

from __future__ import annotations

from typing import Any, Dict, Optional

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
    text,
)
from suu.retrieve.export import export_data, warn_first_page_only
from suu.retrieve.members import slugify_group

GRANT = ".grant-account-balance, [data-account='grant']"
SUBS = ".subs-account-balance, [data-account='subs']"

FINANCE_FIELDS = ["request_id", "title", "amount", "status", "date"]


def parse_finance(html: str) -> Retrieved:
    """Read the finance page: both balances (``summary``) and the submitted requests."""
    doc = parse_html(html)
    refuse_login_page(doc)
    grant = doc.select_one(GRANT)
    subs = doc.select_one(SUBS)
    # Any page may carry a table; only a balance marks this as the finance page.
    if grant is None and subs is None:
        raise UnrecognisedPageError("finance")

    rows = read_rows(
        doc,
        3,
        lambda cells: {
            "request_id": cells[0],
            "title": cells[1],
            "amount": cells[2],
            "status": cell_at(cells, 3, "Submitted"),
            "date": cell_at(cells, 4),
        },
        "finance",
    )
    return Retrieved(
        rows=rows,
        has_more=has_next_page(doc),
        summary={
            "grant_account_balance": text(grant) or None,
            "subs_account_balance": text(subs) or None,
        },
    )


def fetch_finance(
    group_name: str,
    auth_file: Optional[str] = None,
    headless: bool = True,
) -> Retrieved:
    """Fetch live balances and submitted financial requests for a club or society."""
    slug = slugify_group(group_name)
    click.echo(f"Fetching financial balances and requests for '{group_name}'...")
    html = fetch_page_html(f"/group/{slug}/finance", "finance", auth_file=auth_file, headless=headless)
    result = parse_finance(html)
    for row in result.rows:
        row["group"] = group_name
    return result


def _balance(value: Any) -> str:
    return value if value is not None else "not shown on the page"


def retrieve_finance_cmd(
    group_name: str,
    as_csv: bool = False,
    as_xlsx: bool = False,
    as_json: bool = False,
    as_sheets: bool = False,
    auth_file: Optional[str] = None,
) -> None:
    """CLI handler for `suu retrieve finance`."""
    data = fetch_finance(group_name, auth_file=auth_file)
    summary: Dict[str, Any] = data.summary or {}

    click.echo("\n------------------------------------------------")
    click.echo(f"  Financial Summary for: {group_name}")
    click.echo(f"  Account 10 (Grant Account):    {_balance(summary.get('grant_account_balance'))}")
    click.echo(f"  Account 11 (Non-Grant Subs):  {_balance(summary.get('subs_account_balance'))}")
    click.echo("------------------------------------------------\n")

    if data.has_more:
        warn_first_page_only("finance requests")

    export_data(
        rows=data.rows,
        fieldnames=[*FINANCE_FIELDS, "group"],
        prefix=f"finance_{slugify_group(group_name)}",
        as_csv=as_csv,
        as_xlsx=as_xlsx,
        as_json=as_json,
        as_sheets=as_sheets,
        summary={"group": group_name, **summary},
    )
