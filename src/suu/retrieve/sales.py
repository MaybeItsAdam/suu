"""Retrieve ticket sales and door lists for Students' Union UCL events."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import click

from suu.core.constants import BASE_URL
from suu.retrieve.browser import check_authenticated, resolve_auth_file
from suu.retrieve.export import export_data
from suu.retrieve.members import slugify_group


def fetch_sales(
    group_name: str,
    event_name: Optional[str] = None,
    auth_file: Optional[str] = None,
    headless: bool = True,
) -> List[Dict[str, Any]]:
    """Fetch ticket purchaser / door list records for an event."""
    check_authenticated(auth_file)
    slug = slugify_group(group_name)

    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        raise click.ClickException("Missing browser support. Run `pip install playwright && playwright install chromium`.")

    state_path = resolve_auth_file(auth_file)
    target_url = f"{BASE_URL}/group/{slug}/events"

    click.echo(f"Fetching sales and door list for '{group_name}'...")

    tickets: List[Dict[str, Any]] = []

    from suu.core.browser import launch_browser_safe

    with sync_playwright() as p:
        browser = launch_browser_safe(p, headless=headless)
        context = browser.new_context(storage_state=str(state_path))
        page = context.new_page()

        response = page.goto(target_url, wait_until="domcontentloaded")
        if response and response.status in (403, 401):
            browser.close()
            raise click.ClickException(
                f"Access denied (HTTP {response.status}). Ensure you have event admin rights "
                f"for '{group_name}' and your login session is active (run `suu login`)."
            )

        page.wait_for_selector("table, .event-list, body", timeout=10000)

        rows = page.query_selector_all("table tbody tr")
        for r in rows:
            cols = r.query_selector_all("td")
            if len(cols) >= 3:
                buyer_name = cols[0].inner_text().strip()
                ticket_tier = cols[1].inner_text().strip()
                email = cols[2].inner_text().strip() if len(cols) > 2 else ""
                code = cols[3].inner_text().strip() if len(cols) > 3 else ""

                tickets.append(
                    {
                        "buyer_name": buyer_name,
                        "ticket_tier": ticket_tier,
                        "email": email,
                        "ticket_code": code,
                        "group": group_name,
                        "event": event_name or "All Events",
                    }
                )

        browser.close()

    return tickets


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
    tickets = fetch_sales(group_name, event_name=event_name, auth_file=auth_file)
    fieldnames = ["buyer_name", "ticket_tier", "email", "ticket_code", "group", "event"]
    slug = slugify_group(group_name)
    event_slug = slugify_group(event_name) if event_name else "all"

    export_data(
        rows=tickets,
        fieldnames=fieldnames,
        prefix=f"sales_{slug}_{event_slug}",
        as_csv=as_csv,
        as_xlsx=as_xlsx,
        as_json=as_json,
        as_sheets=as_sheets,
    )
