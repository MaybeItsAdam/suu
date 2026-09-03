"""CLI commands for `suu retrieve`."""

from __future__ import annotations

from typing import Optional
import click


@click.group()
def retrieve() -> None:
    """Retrieve authenticated leadership & committee data for clubs & societies."""


@retrieve.command("members")
@click.argument("group_name")
@click.option("--csv", "as_csv", is_flag=True, help="Save as CSV file.")
@click.option("--xlsx", "as_xlsx", is_flag=True, help="Save as Excel (.xlsx) file.")
@click.option("--json", "as_json", is_flag=True, help="Save as JSON file.")
@click.option("--sheets", "as_sheets", is_flag=True, help="Copy to clipboard in Google Sheets format.")
@click.option("--auth", "auth_file", default=None, help="Use a specific saved-login state file.")
def retrieve_members(
    group_name: str,
    as_csv: bool,
    as_xlsx: bool,
    as_json: bool,
    as_sheets: bool,
    auth_file: Optional[str],
) -> None:
    """Retrieve official member roster for a club or society."""
    from suu.retrieve.members import retrieve_members_cmd
    retrieve_members_cmd(
        group_name,
        as_csv=as_csv,
        as_xlsx=as_xlsx,
        as_json=as_json,
        as_sheets=as_sheets,
        auth_file=auth_file,
    )


@retrieve.command("finance")
@click.argument("group_name")
@click.option("--csv", "as_csv", is_flag=True, help="Save submitted requests as CSV file.")
@click.option("--xlsx", "as_xlsx", is_flag=True, help="Save submitted requests as Excel (.xlsx) file.")
@click.option("--json", "as_json", is_flag=True, help="Save balances & requests as JSON file.")
@click.option("--sheets", "as_sheets", is_flag=True, help="Copy requests to clipboard in Google Sheets format.")
@click.option("--auth", "auth_file", default=None, help="Use a specific saved-login state file.")
def retrieve_finance(
    group_name: str,
    as_csv: bool,
    as_xlsx: bool,
    as_json: bool,
    as_sheets: bool,
    auth_file: Optional[str],
) -> None:
    """Retrieve account balances and submitted payment/purchase requests."""
    from suu.retrieve.finance import retrieve_finance_cmd
    retrieve_finance_cmd(
        group_name,
        as_csv=as_csv,
        as_xlsx=as_xlsx,
        as_json=as_json,
        as_sheets=as_sheets,
        auth_file=auth_file,
    )


@retrieve.command("sales")
@click.argument("group_name")
@click.option("--event", "event_name", default=None, help="Filter to a specific event name.")
@click.option("--csv", "as_csv", is_flag=True, help="Save door list / sales as CSV file.")
@click.option("--xlsx", "as_xlsx", is_flag=True, help="Save door list / sales as Excel (.xlsx) file.")
@click.option("--json", "as_json", is_flag=True, help="Save as JSON file.")
@click.option("--sheets", "as_sheets", is_flag=True, help="Copy to clipboard in Google Sheets format.")
@click.option("--auth", "auth_file", default=None, help="Use a specific saved-login state file.")
def retrieve_sales(
    group_name: str,
    event_name: Optional[str],
    as_csv: bool,
    as_xlsx: bool,
    as_json: bool,
    as_sheets: bool,
    auth_file: Optional[str],
) -> None:
    """Retrieve ticket sales and door list for society events."""
    from suu.retrieve.sales import retrieve_sales_cmd
    retrieve_sales_cmd(
        group_name,
        event_name=event_name,
        as_csv=as_csv,
        as_xlsx=as_xlsx,
        as_json=as_json,
        as_sheets=as_sheets,
        auth_file=auth_file,
    )


@retrieve.command("bookings")
@click.argument("group_name")
@click.option("--csv", "as_csv", is_flag=True, help="Save room booking requests as CSV file.")
@click.option("--xlsx", "as_xlsx", is_flag=True, help="Save room booking requests as Excel (.xlsx) file.")
@click.option("--json", "as_json", is_flag=True, help="Save as JSON file.")
@click.option("--sheets", "as_sheets", is_flag=True, help="Copy to clipboard in Google Sheets format.")
@click.option("--auth", "auth_file", default=None, help="Use a specific saved-login state file.")
def retrieve_bookings(
    group_name: str,
    as_csv: bool,
    as_xlsx: bool,
    as_json: bool,
    as_sheets: bool,
    auth_file: Optional[str],
) -> None:
    """Retrieve room & space booking request statuses."""
    from suu.retrieve.bookings import retrieve_bookings_cmd
    retrieve_bookings_cmd(
        group_name,
        as_csv=as_csv,
        as_xlsx=as_xlsx,
        as_json=as_json,
        as_sheets=as_sheets,
        auth_file=auth_file,
    )


@retrieve.command("committee")
@click.argument("group_name")
@click.option("--csv", "as_csv", is_flag=True, help="Save committee lineup as CSV file.")
@click.option("--xlsx", "as_xlsx", is_flag=True, help="Save committee lineup as Excel (.xlsx) file.")
@click.option("--json", "as_json", is_flag=True, help="Save as JSON file.")
@click.option("--sheets", "as_sheets", is_flag=True, help="Copy to clipboard in Google Sheets format.")
@click.option("--auth", "auth_file", default=None, help="Use a specific saved-login state file.")
def retrieve_committee(
    group_name: str,
    as_csv: bool,
    as_xlsx: bool,
    as_json: bool,
    as_sheets: bool,
    auth_file: Optional[str],
) -> None:
    """Retrieve official registered committee roster."""
    from suu.retrieve.committee import retrieve_committee_cmd
    retrieve_committee_cmd(
        group_name,
        as_csv=as_csv,
        as_xlsx=as_xlsx,
        as_json=as_json,
        as_sheets=as_sheets,
        auth_file=auth_file,
    )
