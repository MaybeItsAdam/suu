"""Retrieve Students' Union term room booking timetable sheet & bookings."""

from __future__ import annotations

import csv
import io
import re
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional
import click

from suu.core.constants import BASE_URL
from suu.retrieve.browser import check_authenticated, resolve_auth_file
from suu.retrieve.export import export_data


TIMETABLE_NODE_URL = f"{BASE_URL}/node/139269?check_logged_in=1#"


def extract_spreadsheet_id(url: str) -> Optional[str]:
    """Extract Google Sheets ID from URL."""
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if match:
        return match.group(1)
    return None


def fetch_sheet_csv(sheet_url: str) -> Optional[str]:
    """Attempt to download CSV export of a public/shared Google Sheet."""
    sheet_id = extract_spreadsheet_id(sheet_url)
    if not sheet_id:
        return None

    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    req = urllib.request.Request(csv_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        pass
    return None


def parse_sheet_bookings(csv_content: str) -> List[Dict[str, Any]]:
    """Parse booking rows from the timetable Google Sheet CSV content.
    
    Returns a list of dicts with room booking details if present.
    """
    bookings: List[Dict[str, Any]] = []
    if not csv_content:
        return bookings

    lines = [line for line in csv_content.splitlines() if line.strip()]
    if not lines:
        return bookings

    reader = list(csv.reader(lines))
    if len(reader) < 2:
        return bookings

    header_idx = -1
    for i, row in enumerate(reader[:15]):
        row_str = " ".join(row).lower()
        if any(kw in row_str for kw in ["room", "day", "time", "date", "status", "booking"]):
            header_idx = i
            break

    if header_idx != -1:
        headers = [c.strip() for c in reader[header_idx]]
        for row in reader[header_idx + 1:]:
            if not any(row):
                continue
            row_dict = {}
            for col_idx, val in enumerate(row):
                if col_idx < len(headers) and headers[col_idx]:
                    row_dict[headers[col_idx]] = val.strip()
            if row_dict and any(row_dict.values()):
                bookings.append(row_dict)

    return bookings


def fetch_su_timetable(
    auth_file: Optional[str] = None,
    headless: bool = True,
    parse_sheet_content: bool = True,
) -> Dict[str, Any]:
    """Fetch Students' Union UCL term room booking timetable page and sheet link.
    
    Navigates to node 139269 with authentication state. Returns metadata about the
    term, Google sheet URL, guidance PDF URL, and parsed bookings if available.
    """
    check_authenticated(auth_file)

    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        raise click.ClickException(
            "Missing browser support. Run `pip install playwright && playwright install chromium`."
        )

    state_path = resolve_auth_file(auth_file)
    click.echo(f"Accessing Students' Union room timetable page ({TIMETABLE_NODE_URL})...")

    sheet_url: Optional[str] = None
    pdf_url: Optional[str] = None
    term_text: str = ""
    term_number: Optional[int] = None
    academic_year: Optional[str] = None
    page_title: str = ""
    full_text: str = ""

    from suu.core.browser import launch_browser_safe

    with sync_playwright() as p:
        browser = launch_browser_safe(p, headless=headless)
        context = browser.new_context(storage_state=str(state_path))
        page = context.new_page()

        response = page.goto(TIMETABLE_NODE_URL, wait_until="domcontentloaded")
        if response and response.status in (403, 401):
            browser.close()
            raise click.ClickException(
                f"Access denied (HTTP {response.status}). Ensure your login session is active (run `suu login`)."
            )

        page.wait_for_selector("a, body", timeout=10000)
        page_title = page.title()
        full_text = page.inner_text("body")

        for a in page.query_selector_all("a"):
            href = a.get_attribute("href") or ""
            text = a.inner_text().strip()
            if "spreadsheets" in href.lower() or "docs.google.com" in href.lower():
                if not sheet_url or "timetable" in text.lower():
                    sheet_url = href
            elif href.lower().endswith(".pdf") and ("room" in href.lower() or "availability" in href.lower()):
                pdf_url = href

        browser.close()

    combined = f"{page_title}\n{full_text}\n{pdf_url or ''}"
    term_match = re.search(r"Term\s*([1-3])", combined, re.IGNORECASE)
    if term_match:
        term_number = int(term_match.group(1))

    year_match = re.search(r"(20\d{2}[-/]\d{2,4})", combined)
    if year_match:
        academic_year = year_match.group(1)

    if term_number:
        term_text = f"Term {term_number}" + (f" {academic_year}" if academic_year else "")

    bookings: List[Dict[str, Any]] = []
    if sheet_url and parse_sheet_content:
        csv_content = fetch_sheet_csv(sheet_url)
        if csv_content:
            bookings = parse_sheet_bookings(csv_content)

    return {
        "page_url": TIMETABLE_NODE_URL,
        "sheet_url": sheet_url,
        "pdf_url": pdf_url,
        "term_text": term_text,
        "term_number": term_number,
        "academic_year": academic_year,
        "has_sheet": bool(sheet_url),
        "has_bookings": len(bookings) > 0,
        "bookings": bookings,
        "checked_at": datetime.now().isoformat(),
    }


def retrieve_timetable_cmd(
    as_csv: bool = False,
    as_xlsx: bool = False,
    as_json: bool = False,
    as_sheets: bool = False,
    auth_file: Optional[str] = None,
) -> None:
    """CLI handler for `suu retrieve timetable`."""
    result = fetch_su_timetable(auth_file=auth_file)

    if not result.get("sheet_url"):
        click.echo("No Google Sheet timetable link found on the page.")
        return

    click.echo(f"Found room booking timetable sheet: {result['sheet_url']}")
    if result.get("term_text"):
        click.echo(f"Term: {result['term_text']}")

    bookings = result.get("bookings", [])
    if bookings:
        fieldnames = list(bookings[0].keys())
        export_data(
            rows=bookings,
            fieldnames=fieldnames,
            prefix="su_room_timetable",
            as_csv=as_csv,
            as_xlsx=as_xlsx,
            as_json=as_json,
            as_sheets=as_sheets,
        )
    else:
        click.echo("No booked spots / rows extracted from the spreadsheet yet.")
