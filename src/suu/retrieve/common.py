"""What every SU page retriever shares: the refusal rule, row reading, and the page fetch.

Kept in step with the Toolbox Connector's ``lib/retrieve/common.js`` and ``run.js``
(``../adams-campus-toolbox-connector``). Fix a parser in both places.

The parsers are pure functions of the page's HTML, so each one is tested against a
fixture under ``tests/fixtures/retrieve/`` with no browser. The fetch only navigates,
checks where it landed, and hands ``page.content()`` to the parser.

The rule: a page that isn't the one expected is **refused** with an error, never read
as an empty result. An empty table is an answer ("no bookings"); a login page or a
redesign is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit

import click

from suu.core.constants import BASE_URL

SIGNED_OUT = (
    "You're not signed in to studentsunionucl.org (or your saved login has expired), "
    "so nothing was read. Run `suu login`, then try again."
)

LOGIN_FORM = "#user-login-form, form[action*='/user/login'], input[name='pass']"
NEXT_PAGE = ".pager__item--next"


class RetrieveError(click.ClickException):
    """A retrieval failure with a message fit to show the officer as it is."""


class SignedOutError(RetrieveError):
    """The SU served its login page (or redirected off-site to single sign-on)."""

    def __init__(self) -> None:
        super().__init__(SIGNED_OUT)


class UnrecognisedPageError(RetrieveError):
    """The page wasn't the one the parser knows: an error page, another page, or a redesign."""

    def __init__(self, what: str) -> None:
        super().__init__(
            f"The SU {what} page didn't look the way suu expects, so nothing was read. "
            "suu may need an update."
        )


@dataclass
class Retrieved:
    """One retriever's result.

    ``rows`` are keyed by suu's export field names. ``has_more`` is True when a Drupal
    pager says there is another page (only the first is read). ``summary`` carries
    non-tabular values, e.g. finance balances.
    """

    rows: List[Dict[str, Any]] = field(default_factory=list)
    has_more: bool = False
    summary: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"rows": self.rows, "has_more": self.has_more}
        if self.summary is not None:
            out["summary"] = self.summary
        return out


def parse_html(html: str) -> Any:
    """Parse a page with BeautifulSoup (imported lazily; it lives in the ``forms`` extra)."""
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError:
        raise click.ClickException("Reading SU pages needs beautifulsoup4. Run `pip install 'suu[forms]'`.")
    return BeautifulSoup(html, "html.parser")


def text(node: Any) -> str:
    """An element's text content, whitespace collapsed (the JS ``text()``); '' for None."""
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text()).strip()


def refuse_login_page(doc: Any) -> None:
    """Refuse Drupal's login form, whichever route served it.

    The fetch usually lands on ``/user/login`` and is caught by its URL; this catches
    the SU rendering the form in place on the page that was asked for.
    """
    if doc.select_one(LOGIN_FORM) is not None:
        raise SignedOutError()


def read_rows(
    doc: Any,
    min_cells: int,
    to_row: Callable[[List[str]], Dict[str, Any]],
    what: str,
) -> List[Dict[str, Any]]:
    """Every ``table tbody tr`` on the page, mapped through ``to_row(cells)`` once it has
    at least ``min_cells`` direct ``<td>`` cells.

    Rows with fewer cells are skipped; but if there were rows and *none* had enough
    cells, the table is some other table and the page is refused rather than read as
    empty. Drupal renders an empty view as one row with a single "No results" cell,
    which counts as empty.
    """
    rows = doc.select("table tbody tr")
    read: List[Dict[str, Any]] = []
    for row in rows:
        cells = [text(td) for td in row.find_all("td", recursive=False)]
        if len(cells) >= min_cells:
            read.append(to_row(cells))
    only_empty_message = len(rows) == 1 and len(rows[0].find_all("td", recursive=False)) == 1
    if rows and not read and not only_empty_message:
        raise UnrecognisedPageError(what)
    return read


def cell_at(cells: List[str], index: int, default: str = "") -> str:
    """``cells[index]`` if present, else ``default`` (the JS ``cells[i] ?? default``)."""
    return cells[index] if index < len(cells) else default


def has_next_page(doc: Any) -> bool:
    """True when a Drupal pager says there is another page. Only the first page is read."""
    return doc.select_one(NEXT_PAGE) is not None


def check_landing(url: str) -> None:
    """Refuse a fetch that landed on the login page, or off the SU site (UCL single sign-on)."""
    landed = urlsplit(url)
    su = urlsplit(BASE_URL)
    if (landed.scheme, landed.netloc) != (su.scheme, su.netloc) or landed.path.startswith("/user/login"):
        raise SignedOutError()


def fetch_page_html(
    path: str,
    what: str,
    auth_file: Optional[str] = None,
    headless: bool = True,
) -> str:
    """Open one SU page in the saved login session and return its HTML.

    Refuses a login landing and turns 403/404 into a permissions message; parsing is
    the caller's (pure) parser's job.
    """
    from suu.retrieve.browser import check_authenticated, resolve_auth_file

    check_authenticated(auth_file)
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        raise click.ClickException("Missing browser support. Run `pip install playwright && playwright install chromium`.")

    from suu.core.browser import launch_browser_safe

    state_path = resolve_auth_file(auth_file)
    target_url = f"{BASE_URL}{path}"

    with sync_playwright() as p:
        browser = launch_browser_safe(p, headless=headless)
        try:
            context = browser.new_context(storage_state=str(state_path))
            page = context.new_page()
            response = page.goto(target_url, wait_until="domcontentloaded")
            check_landing(page.url or target_url)
            status = response.status if response else 200
            if status in (401, 403, 404):
                raise RetrieveError(
                    f"Your SU account can't open this society's {what} page (HTTP {status}). "
                    "Only committee accounts can."
                )
            if status >= 400:
                raise RetrieveError(f"The SU site answered HTTP {status}.")
            return page.content()
        finally:
            browser.close()
