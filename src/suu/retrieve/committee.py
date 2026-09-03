"""Retrieve registered committee roster for a Students' Union UCL club or society."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import click

from suu.core.constants import BASE_URL
from suu.retrieve.browser import check_authenticated, resolve_auth_file
from suu.retrieve.export import export_data
from suu.retrieve.members import slugify_group


def fetch_committee(
    group_name: str,
    auth_file: Optional[str] = None,
    headless: bool = True,
) -> List[Dict[str, Any]]:
    """Fetch registered committee members for a club or society."""
    check_authenticated(auth_file)
    slug = slugify_group(group_name)

    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        raise click.ClickException("Missing browser support. Run `pip install playwright && playwright install chromium`.")

    state_path = resolve_auth_file(auth_file)
    target_url = f"{BASE_URL}/group/{slug}/committee"

    click.echo(f"Fetching committee lineup for '{group_name}'...")

    committee: List[Dict[str, Any]] = []

    from suu.core.browser import launch_browser_safe

    with sync_playwright() as p:
        browser = launch_browser_safe(p, headless=headless)
        context = browser.new_context(storage_state=str(state_path))
        page = context.new_page()

        response = page.goto(target_url, wait_until="domcontentloaded")
        if response and response.status in (403, 401):
            browser.close()
            raise click.ClickException(
                f"Access denied (HTTP {response.status}). Ensure you have committee view access "
                f"for '{group_name}' and your login session is active (run `suu login`)."
            )

        page.wait_for_selector("table, .committee-list, body", timeout=10000)

        rows = page.query_selector_all("table tbody tr")
        for r in rows:
            cols = r.query_selector_all("td")
            if len(cols) >= 2:
                role = cols[0].inner_text().strip()
                name = cols[1].inner_text().strip()
                email = cols[2].inner_text().strip() if len(cols) > 2 else ""

                committee.append(
                    {
                        "role": role,
                        "name": name,
                        "email": email,
                        "group": group_name,
                    }
                )

        browser.close()

    return committee


def retrieve_committee_cmd(
    group_name: str,
    as_csv: bool = False,
    as_xlsx: bool = False,
    as_json: bool = False,
    as_sheets: bool = False,
    auth_file: Optional[str] = None,
) -> None:
    """CLI handler for `suu retrieve committee`."""
    committee = fetch_committee(group_name, auth_file=auth_file)
    fieldnames = ["role", "name", "email", "group"]
    slug = slugify_group(group_name)

    export_data(
        rows=committee,
        fieldnames=fieldnames,
        prefix=f"committee_{slug}",
        as_csv=as_csv,
        as_xlsx=as_xlsx,
        as_json=as_json,
        as_sheets=as_sheets,
    )
