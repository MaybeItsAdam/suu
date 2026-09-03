"""Scraper for UCL SU governing documents (Bye-Laws, Code of Practice, ...).

These are static Drupal pages, not the React-driven What's On calendar, so
plain ``requests`` + BeautifulSoup is enough — no Selenium involved.

Only Bye-Laws and Code of Practice are wired up so far (the two named when
this was built). The source page (``GOVERNING_DOCUMENTS_URL``) also lists a
Memorandum & Articles of Association and Clubs & Societies Regulations —
adding either later is a new ``_discover_<name>`` method plus a branch in
``discover()``, following the shape of ``_discover_byelaws``/``_discover_cop``
below, not a restructure.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from typing import Literal, Optional
from urllib.parse import urljoin, unquote

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

GOVERNING_DOCUMENTS_URL = "https://studentsunionucl.org/governing-documents"
BYE_LAWS_URL = "https://studentsunionucl.org/bye-laws"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

Scope = Literal["byelaws", "cop", "csregs", "all"]


@dataclass
class GovDocEntry:
    """One document discovered on the SU site, ready to fetch."""

    slug: str
    category: str
    title: str
    pdf_url: str
    version_label: Optional[str] = None
    source_page: str = GOVERNING_DOCUMENTS_URL


@dataclass
class GovDocResult:
    """A fetched document: the original PDF plus cleaned, extracted text."""

    slug: str
    category: str
    title: str
    source_url: str
    version_label: Optional[str]
    pdf_bytes: bytes
    formatted_text: str


class GovDocsScraper:
    """Discovers and downloads UCL SU governing documents."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    # -- discovery -----------------------------------------------------

    def discover(self, scope: Scope = "all") -> list[GovDocEntry]:
        """Find current document URLs for *scope*.

        Never hardcodes filenames — the SU re-uploads these PDFs under new,
        dated paths periodically (the Bye-Laws PDF moved within the last
        year), so every run re-parses the live pages.
        """
        entries: list[GovDocEntry] = []
        if scope in ("byelaws", "all"):
            entries.extend(self._discover_byelaws())
        if scope in ("cop", "all"):
            entries.extend(self._discover_cop())
        if scope in ("csregs", "all"):
            entries.extend(self._discover_csregs())
        return entries

    def _get_soup(self, url: str) -> BeautifulSoup:
        resp = self._session.get(url, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")

    def _discover_byelaws(self) -> list[GovDocEntry]:
        soup = self._get_soup(BYE_LAWS_URL)

        version_label = None
        m = re.search(
            r"came into effect on ([0-9]{1,2} \w+ \d{4})",
            soup.get_text(" ", strip=True),
        )
        if m:
            version_label = m.group(1)

        entries: list[GovDocEntry] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.lower().split("?")[0].endswith(".pdf"):
                continue
            pdf_url = urljoin(BYE_LAWS_URL, href)
            if pdf_url in seen:
                continue
            seen.add(pdf_url)

            lowered = href.lower()
            if "appendix%201" in lowered or "appendix 1" in lowered:
                slug, title = "byelaws-appendix-1", "Bye-Laws — Appendix 1 (Disciplinary Standards)"
            elif "appendix%202" in lowered or "appendix 2" in lowered:
                slug, title = "byelaws-appendix-2", "Bye-Laws — Appendix 2 (Disciplinary Outcomes & Sanctions)"
            elif "appendix%203" in lowered or "appendix 3" in lowered:
                slug, title = "byelaws-appendix-3", "Bye-Laws — Appendix 3 (Risk Assessment Procedure)"
            else:
                slug, title = "byelaws-main", "Bye-Laws"

            entries.append(
                GovDocEntry(
                    slug=slug,
                    category="byelaws",
                    title=title,
                    pdf_url=pdf_url,
                    version_label=version_label,
                    source_page=BYE_LAWS_URL,
                )
            )
        return entries

    def _discover_cop(self) -> list[GovDocEntry]:
        soup = self._get_soup(GOVERNING_DOCUMENTS_URL)
        for a in soup.find_all("a", href=True):
            if "code of practice" not in a.get_text(" ", strip=True).lower():
                continue
            href = a["href"]
            if not href.lower().split("?")[0].endswith(".pdf"):
                continue
            pdf_url = urljoin(GOVERNING_DOCUMENTS_URL, href)
            return [
                GovDocEntry(
                    slug="code-of-practice",
                    category="code-of-practice",
                    title="Code of Practice",
                    pdf_url=pdf_url,
                    version_label=self._version_from_filename(pdf_url),
                    source_page=GOVERNING_DOCUMENTS_URL,
                )
            ]
        return []

    def _discover_csregs(self) -> list[GovDocEntry]:
        soup = self._get_soup(GOVERNING_DOCUMENTS_URL)
        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True).lower()
            if "club" not in text or "societ" not in text or "reg" not in text:
                continue
            href = a["href"]
            if not href.lower().split("?")[0].endswith(".pdf"):
                continue
            pdf_url = urljoin(GOVERNING_DOCUMENTS_URL, href)
            return [
                GovDocEntry(
                    slug="clubs-and-societies-regulations",
                    category="clubs-and-societies-regulations",
                    title="Clubs and Societies Regulations",
                    pdf_url=pdf_url,
                    version_label=self._version_from_filename(pdf_url),
                    source_page=GOVERNING_DOCUMENTS_URL,
                )
            ]
        return []

    @staticmethod
    def _version_from_filename(url: str) -> Optional[str]:
        """Best-effort date guess from a filename like '..._5th_february_2014.pdf'."""
        stem = unquote(url.rsplit("/", 1)[-1])
        # Match day-month-year or just month-year, where month is a known month name/abbreviation
        months = r"(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)"
        # Try day-month-year first
        m = re.search(r"(\d{1,2}(?:st|nd|rd|th)?[-_\s]" + months + r"[-_\s]\d{4})", stem, re.IGNORECASE)
        if not m:
            # Fall back to month-year
            m = re.search(r"(" + months + r"[-_\s]\d{4})", stem, re.IGNORECASE)

        if not m:
            return None

        # Clean up separators (spaces, underscores, hyphens) into single spaces
        normalized = re.sub(r"[-_\s]+", " ", m.group(1)).strip()
        # Word-wise .capitalize(), not .title() — .title() mangles ordinals
        # like "5th" into "5Th" by treating the digit/letter boundary as a
        # new word.
        return " ".join(w.capitalize() for w in normalized.split(" "))

    # -- fetch + extract -------------------------------------------------

    def fetch(self, entries: list[GovDocEntry]) -> list[GovDocResult]:
        return [self._fetch_one(e) for e in entries]

    def _fetch_one(self, entry: GovDocEntry) -> GovDocResult:
        resp = self._session.get(entry.pdf_url, timeout=60)
        resp.raise_for_status()
        pdf_bytes = resp.content
        formatted_text = self._extract_text(entry, pdf_bytes)
        return GovDocResult(
            slug=entry.slug,
            category=entry.category,
            title=entry.title,
            source_url=entry.pdf_url,
            version_label=entry.version_label,
            pdf_bytes=pdf_bytes,
            formatted_text=formatted_text,
        )

    @staticmethod
    def _extract_text(entry: GovDocEntry, pdf_bytes: bytes) -> str:
        reader = PdfReader(BytesIO(pdf_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        # Boilerplate stripping needs pypdf's original one-line-per-visual-line
        # shape (it matches on literal first/last lines), so it runs before
        # _join_wrapped_lines reflows those lines into paragraphs.
        pages = _strip_repeated_boilerplate(pages)
        pages = [_join_wrapped_lines(p) for p in pages]

        header = [f"# {entry.title}", "", f"Source: {entry.pdf_url}"]
        if entry.version_label:
            header.append(f"Version: {entry.version_label}")
        header.append("")

        body = "\n\n".join(p.strip() for p in pages if p.strip())
        return "\n".join(header) + "\n" + body + "\n"


_LIST_MARKER_RE = re.compile(r"^(?:[ivxlcdm]+|[a-z]|[0-9]+)\.$", re.IGNORECASE)


def _join_wrapped_lines(page_text: str) -> str:
    """Reflow pypdf's one-newline-per-visual-line output into paragraphs.

    These Bye-Laws/Code of Practice PDFs have no blank-line paragraph
    markers within a page (checked directly against pypdf's raw output) —
    every visual line, including a mid-sentence wrap, gets its own newline.
    Left alone that reads as one word per line for anything in this
    document's heavily indented lettered/numbered clause style. A short
    marker-only line (e.g. "b.", "iii.", "12.") starts a new logical line;
    everything else is joined onto the current one with a single space,
    since it's just a wrapped continuation of the same clause.
    """
    out_lines: list[str] = []
    current: list[str] = []
    for raw in page_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _LIST_MARKER_RE.match(line):
            if current:
                out_lines.append(" ".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        out_lines.append(" ".join(current))
    return "\n".join(out_lines)


def _strip_repeated_boilerplate(pages: list[str]) -> list[str]:
    """Drop lines repeated near-verbatim on most pages (running headers/footers/page numbers).

    ``pypdf``'s ``extract_text()`` has no layout awareness, so a header/footer
    that appears on every page shows up as a stray line interrupting the body
    text on every page too — this is a cheap, blunt cleanup, not real layout
    parsing (multi-column pages can still interleave; see plan notes on
    Appendix 2, which may need a per-document pdfplumber override instead).
    """
    if len(pages) < 3:
        return pages

    line_lists = [p.splitlines() for p in pages]
    first_lines = [lines[0].strip() for lines in line_lists if lines]
    last_lines = [lines[-1].strip() for lines in line_lists if lines]

    def _mostly_repeated(candidates: list[str]) -> set[str]:
        counts = Counter(c for c in candidates if c)
        threshold = max(2, int(len(pages) * 0.6))
        return {c for c, n in counts.items() if n >= threshold}

    boilerplate = _mostly_repeated(first_lines) | _mostly_repeated(last_lines)
    if not boilerplate:
        return pages

    return ["\n".join(l for l in lines if l.strip() not in boilerplate) for lines in line_lists]


def check_gov_docs(scope: Scope = "all", output_dir: str = "./gov-docs") -> list[dict]:
    """Check remote governing documents against local files to detect updates."""
    import hashlib
    from pathlib import Path

    scraper = GovDocsScraper()
    entries = scraper.discover(scope=scope)
    out_path = Path(output_dir)
    changes = []

    for entry in entries:
        txt_file = out_path / f"{entry.slug}.txt"
        pdf_file = out_path / f"{entry.slug}.pdf"

        res = scraper._fetch_one(entry)
        remote_hash = hashlib.md5(res.pdf_bytes).hexdigest()

        local_hash = None
        if pdf_file.exists():
            local_hash = hashlib.md5(pdf_file.read_bytes()).hexdigest()

        is_changed = local_hash != remote_hash
        changes.append(
            {
                "slug": entry.slug,
                "title": entry.title,
                "url": entry.pdf_url,
                "version": entry.version_label,
                "changed": is_changed,
                "local_exists": pdf_file.exists(),
            }
        )
    return changes


def diff_gov_docs(scope: Scope = "all", output_dir: str = "./gov-docs") -> str:
    """Generate a unified git-style text diff of local vs remote governing documents."""
    import difflib
    from pathlib import Path

    scraper = GovDocsScraper()
    entries = scraper.discover(scope=scope)
    out_path = Path(output_dir)
    diff_lines: list[str] = []

    for entry in entries:
        txt_file = out_path / f"{entry.slug}.txt"
        res = scraper._fetch_one(entry)

        if not txt_file.exists():
            diff_lines.append(f"--- /dev/null\n+++ {txt_file}\n@@ -0,0 +1 @@\n+[NEW DOCUMENT] {entry.title}\n")
            continue

        local_text = txt_file.read_text(encoding="utf-8").splitlines()
        remote_text = res.formatted_text.splitlines()

        diff = list(
            difflib.unified_diff(
                local_text,
                remote_text,
                fromfile=f"a/{entry.slug}.txt",
                tofile=f"b/{entry.slug}.txt",
                lineterm="",
            )
        )
        if diff:
            diff_lines.extend(diff)

    return "\n".join(diff_lines) if diff_lines else "No changes detected — all governing documents match local files."
