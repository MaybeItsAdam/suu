"""Retrieve financial account balances and payment request statuses from Students' Union UCL."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
import click

from suu.core.constants import BASE_URL
from suu.retrieve.browser import check_authenticated, resolve_auth_file
from suu.retrieve.export import export_data
from suu.retrieve.members import slugify_group


def fetch_finance(
    group_name: str,
    auth_file: Optional[str] = None,
    headless: bool = True,
) -> Dict[str, Any]:
    """Fetch live balances and submitted financial requests for a club or society."""
    check_authenticated(auth_file)
    slug = slugify_group(group_name)

    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        raise click.ClickException("Missing browser support. Run `pip install playwright && playwright install chromium`.")

    state_path = resolve_auth_file(auth_file)
    target_url = f"{BASE_URL}/group/{slug}/finance"

    click.echo(f"Fetching financial balances and requests for '{group_name}' ({target_url})...")

    result: Dict[str, Any] = {
        "group": group_name,
        "grant_account_balance": "£0.00",
        "subs_account_balance": "£0.00",
        "requests": [],
    }

    from suu.core.browser import launch_browser_safe

    with sync_playwright() as p:
        browser = launch_browser_safe(p, headless=headless)
        context = browser.new_context(storage_state=str(state_path))
        page = context.new_page()

        response = page.goto(target_url, wait_until="domcontentloaded")
        if response and response.status in (403, 401):
            browser.close()
            raise click.ClickException(
                f"Access denied (HTTP {response.status}). Ensure you are a registered President/Treasurer "
                f"for '{group_name}' and your login session is active (run `suu login`)."
            )

        page.wait_for_selector("table, .account-balance, .view-content, body", timeout=10000)

        # Parse balance elements if found
        grant_el = page.query_selector(".grant-account-balance, [data-account='grant']")
        subs_el = page.query_selector(".subs-account-balance, [data-account='subs']")
        if grant_el:
            result["grant_account_balance"] = grant_el.inner_text().strip()
        if subs_el:
            result["subs_account_balance"] = subs_el.inner_text().strip()

        # Parse submitted request table rows
        rows = page.query_selector_all("table tbody tr")
        for r in rows:
            cols = r.query_selector_all("td")
            if len(cols) >= 3:
                req_id = cols[0].inner_text().strip()
                title = cols[1].inner_text().strip()
                amount = cols[2].inner_text().strip() if len(cols) > 2 else ""
                status = cols[3].inner_text().strip() if len(cols) > 3 else "Submitted"
                date = cols[4].inner_text().strip() if len(cols) > 4 else ""

                result["requests"].append(
                    {
                        "request_id": req_id,
                        "title": title,
                        "amount": amount,
                        "status": status,
                        "date": date,
                        "group": group_name,
                    }
                )

        browser.close()

    return result


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

    click.echo("\n------------------------------------------------")
    click.echo(f"  Financial Summary for: {data['group']}")
    click.echo(f"  Account 10 (Grant Account):    {data['grant_account_balance']}")
    click.echo(f"  Account 11 (Non-Grant Subs):  {data['subs_account_balance']}")
    click.echo("------------------------------------------------\n")

    requests = data.get("requests", [])
    fieldnames = ["request_id", "title", "amount", "status", "date", "group"]
    slug = slugify_group(group_name)

    export_data(
        rows=requests,
        fieldnames=fieldnames,
        prefix=f"finance_{slug}",
        as_csv=as_csv,
        as_xlsx=as_xlsx,
        as_json=as_json,
        as_sheets=as_sheets,
    )
