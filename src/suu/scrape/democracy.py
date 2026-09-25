"""Scraper for UCL SU democracy: zone meetings, their papers, and the policy register.

Three static Drupal sources, all readable with plain ``requests``:

* **Zone pages** (``/make-a-change/zones/<zone>``) carry the current year's
  meeting dates as inline JSON handed to the SU's directory widget
  (``window.suDirectories["su-directory--2"] = { cards: {...}, endpoints: ...``).
  Only upcoming-ish meetings are listed; a meeting drops off once it has run.
* **The archive** (``/democracy-minutes-and-papers-archive``) lists every
  meeting's papers by code (``AZ2501``) under one accordion per body and
  academic year. It is hand-maintained and dirty — see ``parse_archive``.
* **The policy register** (``/policy``) is a Drupal Views table, filtered by
  status, with one node page per policy carrying its text and updates.

The parsers are pure (``html -> dataclasses``) and, following this package's
refusal rule, raise ``DemocracyPageError`` on a page that is not the expected
one (a login wall, a redesign) rather than returning an empty result — "the
SU published nothing" and "we could not read the page" must never look alike.
``DemocracyScraper`` only fetches and hands the HTML over.
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

BASE_URL = "https://studentsunionucl.org"
ARCHIVE_URL = f"{BASE_URL}/democracy-minutes-and-papers-archive"
POLICY_LIST_URL = f"{BASE_URL}/policy"

LONDON = ZoneInfo("Europe/London")

#: Body code -> the zone page slug under /make-a-change/zones/.
ZONE_SLUGS: dict[str, str] = {
    "AZ": "activities-zone",
    "EZ": "education-zone",
    "WCZ": "welfare-community-zone",
    "UE": "union-executive",
}
ZONE_URLS: dict[str, str] = {
    body: f"{BASE_URL}/make-a-change/zones/{slug}" for body, slug in ZONE_SLUGS.items()
}
#: Body code -> the name the SU uses in card titles ("Activities Zone: Meeting 1").
BODY_NAMES: dict[str, str] = {
    "AZ": "Activities Zone",
    "EZ": "Education Zone",
    "WCZ": "Welfare & Community Zone",
    "UE": "Union Executive",
}

#: The register's status filter (``field_policy_status_target_id_verf``) term ids.
POLICY_STATUS_IDS: dict[str, str] = {"CURRENT": "40659", "LAPSED": "40660"}
_POLICY_STATUS_LABELS = {"CURRENT": "current", "LAPSED": "lapsed"}
_POLICY_STATUS_PARAM = "field_policy_status_target_id_verf"

_PROGRESS = {
    "completed": "COMPLETED",
    "ongoing": "ONGOING",
    "pending update": "PENDING_UPDATE",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

_CODE_RE = re.compile(r"\b(AZ|EZ|WCZ|UE)\s?(\d{2})(\d{2})\b", re.IGNORECASE)
_CARDS_RE = re.compile(r"cards:\s*(.*?),\s*\n\s*endpoints:", re.DOTALL)
_MEETING_NUMBER_RE = re.compile(r"\bMeeting\s+(\d+)\b", re.IGNORECASE)
_SUBHEADING_RE = re.compile(
    r"(\d{1,2})/(\d{1,2})/(\d{4})\s*\|\s*(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})"
)
_YEAR_RE = re.compile(r"(20\d{2})\s*[-–/]\s*(\d{2})")


class DemocracyPageError(RuntimeError):
    """A page was not the one we asked for (login wall, redesign, error page)."""


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class MeetingCard:
    """One meeting as announced on its zone page."""

    code: str
    body: str
    academic_year: str
    number: int
    title: str
    starts_at: Optional[datetime]
    ends_at: Optional[datetime]
    event_url: Optional[str]


@dataclass
class ArchiveEntry:
    """One meeting's line in the minutes-and-papers archive."""

    code: str
    body: str
    academic_year: str
    number: int
    papers_url: Optional[str] = None
    papers_label: Optional[str] = None
    cancelled: bool = False
    note: Optional[str] = None
    #: The code exactly as the SU wrote it, when it had to be corrected.
    listed_code: Optional[str] = None


@dataclass
class PolicyRow:
    """One row of the policy register table."""

    code: str
    title: str
    source_url: str
    status: str
    progress: Optional[str]
    origin: Optional[str]
    officer_name: Optional[str]
    officer_slug: Optional[str]
    date_lapses: Optional[str]


@dataclass
class PolicyUpdate:
    date: Optional[str]
    title: str
    body_html: str


@dataclass
class PolicyPage:
    """A policy's own page: its text, updates, and sidebar facts."""

    code: Optional[str]
    title: Optional[str]
    status: Optional[str]
    body_html: Optional[str]
    updates: list[PolicyUpdate] = field(default_factory=list)
    date_passed: Optional[str] = None
    date_lapses: Optional[str] = None
    origin: Optional[str] = None
    officer_name: Optional[str] = None
    officer_slug: Optional[str] = None
    pdf_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _clean(text: Optional[str]) -> str:
    return " ".join((text or "").split())


def academic_year_label(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def academic_year_of(value: date) -> int:
    """UCL SU academic years run August to July."""
    return value.year if value.month >= 8 else value.year - 1


def meeting_code(body: str, start_year: int, number: int) -> str:
    return f"{body}{start_year % 100:02d}{number:02d}"


def body_from_name(name: Optional[str]) -> Optional[str]:
    """Map an SU body name ('The Welfare & Community Zone') onto its code."""
    lowered = _clean(name).lower()
    if not lowered:
        return None
    if "activities" in lowered:
        return "AZ"
    if "education" in lowered:
        return "EZ"
    if "welfare" in lowered or "community" in lowered:
        return "WCZ"
    if "union executive" in lowered:
        return "UE"
    return None


def _refuse_wrong_page(soup: BeautifulSoup, what: str) -> None:
    title = _clean(soup.title.get_text()) if soup.title else ""
    if title.lower().startswith("log in") or soup.select_one("form#user-login-form"):
        raise DemocracyPageError(f"{what}: got the SU login page, not {what}")
    if title.lower().startswith(("page not found", "access denied")):
        raise DemocracyPageError(f"{what}: got '{title}'")


def _absolute(href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    url = urljoin(BASE_URL + "/", href.strip())
    # Some card links carry a stray Drupal front controller.
    return url.replace("studentsunionucl.org/index.php/", "studentsunionucl.org/")


def _iso_datetime(tag: Optional[Tag]) -> Optional[str]:
    if tag is None:
        return None
    time_tag = tag if tag.name == "time" else tag.find("time")
    if time_tag is None or not time_tag.get("datetime"):
        return None
    return time_tag["datetime"].strip() or None


# ---------------------------------------------------------------------------
# HTML sanitising
# ---------------------------------------------------------------------------

_KEEP_TAGS = {"p", "strong", "em", "ul", "ol", "li", "a", "h2", "h3", "h4", "br"}
_RENAME_TAGS = {"b": "strong", "i": "em"}
_DROP_TAGS = {"script", "style", "iframe", "object", "embed", "form", "noscript", "svg", "img"}


def sanitise_html(fragment: Any) -> str:
    """Reduce SU-authored HTML to a small safe subset.

    Keeps p/strong/em/ul/ol/li/a/h2-h4/br. Every attribute is dropped except an
    ``<a>``'s ``href``, which is made absolute and must be http(s) or mailto —
    anything else unwraps the link to its text. Other tags are unwrapped (their
    text survives); scripts, styles and embeds are removed with their content.
    """
    if fragment is None:
        return ""
    source = fragment.decode_contents() if isinstance(fragment, Tag) else str(fragment)
    soup = BeautifulSoup(source, "html.parser")
    for tag in soup.find_all(list(_DROP_TAGS)):
        tag.decompose()
    for tag in list(soup.find_all(True)):
        name = _RENAME_TAGS.get(tag.name, tag.name)
        if name not in _KEEP_TAGS:
            tag.unwrap()
            continue
        tag.name = name
        href = tag.get("href") if name == "a" else None
        tag.attrs = {}
        if name == "a":
            url = urljoin(BASE_URL + "/", href.strip()) if href else None
            if not url or urlsplit(url).scheme not in ("http", "https", "mailto"):
                tag.unwrap()
                continue
            tag.attrs = {"href": url}
    return str(soup).strip()


# ---------------------------------------------------------------------------
# Zone pages
# ---------------------------------------------------------------------------


def _card_times(card: dict) -> tuple[Optional[datetime], Optional[datetime]]:
    """Start/end as aware London datetimes.

    The subheading ("27/10/2026 | 18:00 - 20:00") is the only source of the
    end time, and it is wall-clock London, so both ends come from it. The
    ISO ``calendar_start_field`` is the fallback for a start with no subheading.
    """
    m = _SUBHEADING_RE.search(card.get("card_subheading_1") or "")
    if m:
        day, month, year, sh, sm, eh, em = (int(g) for g in m.groups())
        start = datetime(year, month, day, sh, sm, tzinfo=LONDON)
        end = datetime(year, month, day, eh, em, tzinfo=LONDON)
        if end <= start:
            end += timedelta(days=1)
        return start, end
    raw = card.get("calendar_start_field")
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S%z").astimezone(LONDON), None
        except ValueError:
            pass
    return None, None


def parse_zone_cards(html: str, body: str) -> list[MeetingCard]:
    """Read the meeting cards off one zone page.

    Raises ``DemocracyPageError`` when the page carries no directory JSON at
    all — a zone page with its widget gone is a changed page, not a zone with
    no meetings. A widget that is present but lists nothing returns ``[]``.
    """
    body = body.upper()
    if body not in BODY_NAMES:
        raise ValueError(f"unknown body {body!r}")
    soup = BeautifulSoup(html, "html.parser")
    _refuse_wrong_page(soup, f"{body} zone page")
    match = _CARDS_RE.search(html)
    if not match:
        raise DemocracyPageError(f"{body} zone page: no su-directory cards JSON found")
    try:
        raw_cards = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise DemocracyPageError(f"{body} zone page: cards JSON did not parse ({exc})") from exc
    cards = raw_cards.values() if isinstance(raw_cards, dict) else raw_cards

    meetings: list[MeetingCard] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        title = _clean(html_lib.unescape(card.get("card_title_field") or ""))
        number_match = _MEETING_NUMBER_RE.search(title)
        if not number_match:
            logger.info("%s zone page: skipping non-meeting card %r", body, title)
            continue
        number = int(number_match.group(1))
        starts_at, ends_at = _card_times(card)
        if starts_at is None:
            logger.warning("%s zone page: card %r has no readable date — skipped", body, title)
            continue
        start_year = academic_year_of(starts_at.date())
        meetings.append(MeetingCard(
            code=meeting_code(body, start_year, number),
            body=body,
            academic_year=academic_year_label(start_year),
            number=number,
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
            event_url=_absolute(card.get("card_link")),
        ))
    return meetings


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


def _label_from_pdf(url: str) -> Optional[str]:
    """'…/2025-12/AZ2502%20Minutes%20%26%20Papers.pdf' -> 'Minutes & Papers'.

    Some filenames lack the code ('Agenda and Papers with Minutes.pdf'); the
    rest of the name is the label either way.
    """
    stem = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    stem = re.sub(r"\.pdf$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"_\d+$", "", stem)  # Drupal's duplicate-upload suffix
    stem = re.sub(r"^\s*(?:AZ|EZ|WCZ|UE)\s?\d{4}\b[\s_\-–:]*", "", stem, flags=re.IGNORECASE)
    stem = _clean(stem.replace("_", " "))
    return stem or None


def _split_lines(dd: Tag) -> list[list[Any]]:
    """Group a <dd>'s children into lines separated by <br>."""
    lines: list[list[Any]] = [[]]
    for child in dd.children:
        if isinstance(child, Tag) and child.name == "br":
            lines.append([])
        elif isinstance(child, Tag) and child.name in ("p", "div"):
            lines.append([])
            lines.extend(_split_lines(child))
            lines.append([])
        else:
            lines[-1].append(child)
    return [line for line in lines if any(_clean(_node_text(n)) for n in line)]


def _node_text(node: Any) -> str:
    return node.get_text() if isinstance(node, Tag) else str(node)


def _line_items(line: list[Any]) -> list[dict]:
    """The meetings named on one archive line: a code link each, or plain text."""
    items: list[dict] = []
    for node in line:
        if isinstance(node, Tag):
            anchors = [node] if node.name == "a" else node.find_all("a")
            for a in anchors:
                text = _clean(a.get_text())
                if _CODE_RE.search(text):
                    items.append({"listed": text, "href": a.get("href"), "text": ""})
    if items:
        return items
    # No link on the line: "4) - WCZ2404 - There are no minutes for WCZ2504 …"
    text = _clean("".join(_node_text(n) for n in line))
    m = re.match(r"^(?:\d+\)\s*)?[-–]?\s*((?:AZ|EZ|WCZ|UE)\s?\d{4})\s*(?:[-–:]\s*(.*))?$", text, re.IGNORECASE)
    if m:
        return [{"listed": m.group(1), "href": None, "text": (m.group(2) or "").strip()}]
    return []


def parse_archive(html: str) -> list[ArchiveEntry]:
    """Read every meeting's papers link off the archive page.

    The page is hand-edited, and several kinds of dirt are handled here rather
    than trusted:

    * The **link text** is the key, never ``data-id`` (stale copies of other
      meetings' URLs) and never the target (AZ2101's link points at AZ2102).
      A target naming a different meeting is logged and noted on the entry.
    * A code whose year disagrees with its accordion's year
      ("WCZ2404" under 2025-26) is a typo: the accordion year and the
      entry's position win, with a warning.
    * An entry with no link carries its text as a note; one saying the
      meeting was cancelled sets ``cancelled``.
    """
    soup = BeautifulSoup(html, "html.parser")
    _refuse_wrong_page(soup, "democracy archive")
    headings = [h for h in soup.select("h2") if body_from_name(h.get_text())]
    if not headings:
        raise DemocracyPageError("democracy archive: no zone headings found")

    entries: list[ArchiveEntry] = []
    seen: set[str] = set()
    for heading in headings:
        body = body_from_name(heading.get_text())
        accordion = heading.find_next("dl")
        if accordion is None:
            continue
        # The accordion must belong to this heading, not to the next body's.
        owner = accordion.find_previous(lambda t: t.name == "h2" and body_from_name(t.get_text()))
        if owner is not heading:
            continue
        for dt in accordion.find_all("dt"):
            year_match = _YEAR_RE.search(_clean(dt.get_text()))
            dd = dt.find_next_sibling("dd")
            if not year_match or dd is None:
                continue
            start_year = int(year_match.group(1))
            position = 0
            for line in _split_lines(dd):
                for item in _line_items(line):
                    position += 1
                    entry = _archive_entry(body, start_year, position, item)
                    if entry is None:
                        continue
                    if entry.code in seen:
                        logger.warning("democracy archive: %s listed twice — keeping the first", entry.code)
                        continue
                    seen.add(entry.code)
                    entries.append(entry)
    if not entries:
        raise DemocracyPageError("democracy archive: headings found but no meeting entries")
    return entries


def _archive_entry(body: str, start_year: int, position: int, item: dict) -> Optional[ArchiveEntry]:
    listed = item["listed"].replace(" ", "").upper()
    m = _CODE_RE.fullmatch(listed)
    listed_code = None
    if m and m.group(1).upper() == body and int(m.group(2)) == start_year % 100:
        number = int(m.group(3))
        code = listed
    else:
        number = position
        code = meeting_code(body, start_year, number)
        listed_code = listed
        logger.warning(
            "democracy archive: %r listed under %s %s — filed as %s (accordion year + position)",
            item["listed"], body, academic_year_label(start_year), code,
        )

    entry = ArchiveEntry(
        code=code,
        body=body,
        academic_year=academic_year_label(start_year),
        number=number,
        listed_code=listed_code,
    )
    href = _absolute(item.get("href"))
    if href:
        entry.papers_url = href
        if urlsplit(href).path.lower().endswith(".pdf"):
            entry.papers_label = _label_from_pdf(href)
        else:
            target = _CODE_RE.search(urlsplit(href).path.rsplit("/", 1)[-1].replace("-", " "))
            target_code = "".join(target.groups()).upper() if target else None
            if target_code and target_code != code:
                logger.warning("democracy archive: %s links to %s's page", code, target_code)
                entry.note = f"The SU archive links this entry to {target_code}'s page."
    text = item.get("text") or ""
    if text:
        entry.note = text
        entry.cancelled = bool(re.search(r"\bcancel", text, re.IGNORECASE))
    return entry


# ---------------------------------------------------------------------------
# Policy register
# ---------------------------------------------------------------------------


def _selected_status(soup: BeautifulSoup) -> Optional[str]:
    select = soup.select_one(f'select[name="{_POLICY_STATUS_PARAM}"]')
    if select is None:
        return None
    option = select.find("option", selected=True)
    if option is None:
        return None
    label = _clean(option.get_text()).lower()
    for status, expected in _POLICY_STATUS_LABELS.items():
        if label == expected:
            return status
    return "ALL" if option.get("value") == "All" else None


def parse_policy_list(html: str, status: Optional[str] = None) -> tuple[list[PolicyRow], bool]:
    """One page of the register -> (rows, has_next_page).

    ``status`` is what the page was asked for. The page's own status filter
    must agree — a renamed query parameter would otherwise hand back the
    unfiltered register and file every lapsed policy as current.
    """
    soup = BeautifulSoup(html, "html.parser")
    _refuse_wrong_page(soup, "policy register")
    shown = _selected_status(soup)
    if shown is None and soup.select_one("table.views-table") is None:
        raise DemocracyPageError("policy register: neither the status filter nor the table is on the page")
    if status is not None and shown is not None and shown != status:
        raise DemocracyPageError(f"policy register: asked for {status}, page is filtered to {shown}")
    row_status = status or (shown if shown in POLICY_STATUS_IDS else None)

    rows: list[PolicyRow] = []
    for tr in soup.select("table.views-table tbody tr"):
        code = _clean(_text_of(tr, ".views-field-field-policy-reference-code")).upper()
        link = tr.select_one(".views-field-title a[href]")
        if not code or link is None:
            continue
        officer = tr.select_one(".views-field-field-policy-officer a[href]")
        rows.append(PolicyRow(
            code=code,
            title=_clean(link.get_text()),
            source_url=_absolute(link["href"]),
            status=row_status,
            progress=_PROGRESS.get(_clean(_text_of(tr, ".views-field-field-policy-progress")).lower()),
            origin=body_from_name(_text_of(tr, ".views-field-field-policy-origin")),
            officer_name=_clean(officer.get_text()) or None if officer else None,
            officer_slug=_officer_slug(officer),
            date_lapses=_iso_datetime(tr.select_one(".views-field-field-policy-date-lapses")),
        ))
    has_next = soup.select_one("li.pager__item--next a[href]") is not None
    return rows, has_next


def _text_of(root: Tag, selector: str) -> str:
    node = root.select_one(selector)
    return node.get_text() if node else ""


def _officer_slug(anchor: Optional[Tag]) -> Optional[str]:
    if anchor is None:
        return None
    m = re.search(r"/officer/([^/?#]+)", anchor.get("href") or "")
    return m.group(1) if m else None


def _parse_update_date(text: str) -> Optional[str]:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_policy_page(html: str) -> PolicyPage:
    """A policy node page -> its text, updates and sidebar facts."""
    soup = BeautifulSoup(html, "html.parser")
    _refuse_wrong_page(soup, "policy page")
    article = soup.select_one("article.node--type-policy.node--view-mode-full") or soup.select_one(
        "article.node--type-policy"
    )
    if article is None:
        raise DemocracyPageError("policy page: no policy article on the page")

    body = article.select_one(".field--name-body")
    updates: list[PolicyUpdate] = []
    section = soup.select_one("section.field--name-field-updates")
    if section is not None:
        for h3 in section.find_all("h3"):
            link = h3.find("a")
            title = _clean(link.get_text()) if link else _clean(re.sub(r"^[\d/\s\-–]+", "", h3.get_text()))
            body_div = h3.find_next_sibling(
                lambda t: isinstance(t, Tag) and (t.name == "h3" or "field--name-comment-body" in (t.get("class") or []))
            )
            comment = body_div if body_div is not None and body_div.name != "h3" else None
            updates.append(PolicyUpdate(
                date=_parse_update_date(h3.get_text()),
                title=title,
                body_html=sanitise_html(comment) if comment is not None else "",
            ))

    side = soup.select_one("#block-entityviewcontent article.node--view-mode-sidebar-extra-information") or article
    status_text = _clean(_text_of(side, ".field--name-field-policy-status .field__items")).lower()
    officer = side.select_one(".field--name-field-policy-officer a[href]")
    pdf = side.select_one(".field--name-field-policy-file-pdf a[href]") or article.select_one(
        ".field--name-field-policy-file-pdf a[href]"
    )
    h1 = soup.select_one("h1")
    return PolicyPage(
        code=_clean(_text_of(side, ".field--name-field-policy-reference-code .field__item")).upper() or None,
        title=_clean(h1.get_text()) if h1 else None,
        status={"current": "CURRENT", "lapsed": "LAPSED"}.get(status_text),
        body_html=sanitise_html(body) if body is not None else None,
        updates=updates,
        date_passed=_iso_datetime(side.select_one(".field--name-field-policy-date-passed")),
        date_lapses=_iso_datetime(side.select_one(".field--name-field-policy-date-lapses")),
        origin=body_from_name(_text_of(side, ".field--name-field-policy-origin .field__items")),
        officer_name=_clean(officer.get_text()) or None if officer else None,
        officer_slug=_officer_slug(officer),
        pdf_url=_absolute(pdf["href"]) if pdf else None,
    )


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class DemocracyScraper:
    """Fetches the democracy pages and hands them to the pure parsers."""

    def __init__(self, delay: float = 0.5, session: Optional[requests.Session] = None) -> None:
        self.delay = delay
        self._session = session or requests.Session()
        self._session.headers.update(_HEADERS)

    def _get_html(self, url: str, params: Optional[dict] = None) -> str:
        resp = self._session.get(url, params=params, timeout=30)
        if "/user/login" in resp.url:
            raise DemocracyPageError(f"{url}: redirected to the SU login page")
        if resp.status_code != 200:
            raise DemocracyPageError(f"{url}: HTTP {resp.status_code}")
        return resp.text

    def fetch_zone_cards(self, body: str) -> list[MeetingCard]:
        return parse_zone_cards(self._get_html(ZONE_URLS[body]), body)

    def fetch_all_zone_cards(self) -> list[MeetingCard]:
        cards: list[MeetingCard] = []
        for body in ZONE_URLS:
            cards.extend(self.fetch_zone_cards(body))
        return cards

    def fetch_archive(self) -> list[ArchiveEntry]:
        return parse_archive(self._get_html(ARCHIVE_URL))

    def fetch_policy_list(self, status: str, max_pages: int = 20) -> list[PolicyRow]:
        status = status.upper()
        rows: list[PolicyRow] = []
        for page in range(max_pages):
            params = {_POLICY_STATUS_PARAM: POLICY_STATUS_IDS[status]}
            if page:
                params["page"] = str(page)
                time.sleep(self.delay)
            page_rows, has_next = parse_policy_list(self._get_html(POLICY_LIST_URL, params), status)
            rows.extend(page_rows)
            if not page_rows or not has_next:
                break
        return rows

    def fetch_policy_rows(self) -> list[PolicyRow]:
        rows: list[PolicyRow] = []
        seen: set[str] = set()
        for status in POLICY_STATUS_IDS:
            for row in self.fetch_policy_list(status):
                if row.code in seen:
                    logger.warning("policy register: %s listed under two statuses — keeping the first", row.code)
                    continue
                seen.add(row.code)
                rows.append(row)
        return rows

    def fetch_policy_page(self, url: str) -> PolicyPage:
        return parse_policy_page(self._get_html(url))

    def fetch_policies(self) -> list[tuple[PolicyRow, Optional[PolicyPage], Optional[str]]]:
        """Every policy row with its page, or the error that page raised.

        A page that fails is reported alongside its row rather than dropping
        the row: the register is still the authority on status and progress.
        """
        results = []
        for index, row in enumerate(self.fetch_policy_rows()):
            if index:
                time.sleep(self.delay)
            try:
                results.append((row, self.fetch_policy_page(row.source_url), None))
            except (DemocracyPageError, requests.RequestException) as exc:
                logger.warning("policy page %s unreadable: %s", row.code, exc)
                results.append((row, None, str(exc)))
        return results


def to_jsonable(value: Any) -> Any:
    """Dataclasses / datetimes -> plain JSON types, for ``--json`` output."""
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        return {k: to_jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
