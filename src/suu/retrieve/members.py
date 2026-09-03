"""Retrieve society member rosters from Students' Union UCL."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
import click

from suu.core.constants import BASE_URL
from suu.retrieve.browser import check_authenticated, resolve_auth_file
from suu.retrieve.export import export_data


def slugify_group(group_name: str) -> str:
    """Convert group title or URL into a web slug."""
    if group_name.startswith("http://") or group_name.startswith("https://"):
        match = re.search(r"/(?:group|user|organisation|content)/([^/]+)", group_name)
        if match:
            return match.group(1)
    return re.sub(r"[^a-z0-9]+", "-", group_name.lower()).strip("-")


def fetch_members(
    group_name: str,
    auth_file: Optional[str] = None,
    headless: bool = True,
) -> List[Dict[str, Any]]:
    """Fetch official member roster for a club or society using Playwright session."""
    check_authenticated(auth_file)
    slug = slugify_group(group_name)

    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        raise click.ClickException("Missing browser support. Run `pip install playwright && playwright install chromium`.")

    state_path = resolve_auth_file(auth_file)
    target_url = f"{BASE_URL}/group/{slug}/members"

    click.echo(f"Fetching member roster for '{group_name}' ({target_url})...")

    members: List[Dict[str, Any]] = []

    from suu.core.browser import launch_browser_safe

    with sync_playwright() as p:
        browser = launch_browser_safe(p, headless=headless)
        context = browser.new_context(storage_state=str(state_path))
        page = context.new_page()

        response = page.goto(target_url, wait_until="domcontentloaded")
        if response and response.status in (403, 401):
            browser.close()
            raise click.ClickException(
                f"Access denied (HTTP {response.status}). Ensure you have committee access for '{group_name}' "
                "and your login session is active (run `suu login`)."
            )

        page.wait_for_selector("table, .view-content, .empty-message, body", timeout=10000)

        # Parse table rows if present
        rows = page.query_selector_all("table tbody tr")
        for r in rows:
            cols = r.query_selector_all("td")
            if len(cols) >= 2:
                name = cols[0].inner_text().strip()
                membership_type = cols[1].inner_text().strip() if len(cols) > 1 else "Standard"
                email = cols[2].inner_text().strip() if len(cols) > 2 else ""
                purchase_date = cols[3].inner_text().strip() if len(cols) > 3 else ""

                members.append(
                    {
                        "name": name,
                        "email": email,
                        "membership_type": membership_type,
                        "purchase_date": purchase_date,
                        "group": group_name,
                    }
                )

        browser.close()

    return members


def retrieve_members_cmd(
    group_name: str,
    as_csv: bool = False,
    as_xlsx: bool = False,
    as_json: bool = False,
    as_sheets: bool = False,
    auth_file: Optional[str] = None,
) -> None:
    """CLI handler for `suu retrieve members`."""
    members = fetch_members(group_name, auth_file=auth_file)
    fieldnames = ["name", "email", "membership_type", "purchase_date", "group"]
    slug = slugify_group(group_name)
    export_data(
        rows=members,
        fieldnames=fieldnames,
        prefix=f"members_{slug}",
        as_csv=as_csv,
        as_xlsx=as_xlsx,
        as_json=as_json,
        as_sheets=as_sheets,
    )
