"""Saving/restoring the scraper's SU login (Selenium cookies).

The scraper logs in once in a real browser window, then we save the resulting
cookies to ``~/.suu/selenium_session.json`` so future runs skip the login.

Ported from suu-scrape's ``core/browser.py`` cookie helpers, with the file
location now centralised in :mod:`suu.core.paths`.
"""

from __future__ import annotations

import json
from typing import Dict, List

from suu.core.constants import AUTH_COOKIE_PREFIX
from suu.core.paths import selenium_session_file


def normalise(cookies: List[dict]) -> List[Dict[str, str]]:
    """Strip leading dots from domains and stringify values for safe re-import."""
    out: List[Dict[str, str]] = []
    for c in cookies:
        out.append(
            {
                "name": str(c.get("name", "")),
                "value": str(c.get("value", "")),
                "domain": str(c.get("domain", "")).lstrip("."),
                "path": str(c.get("path", "/")),
            }
        )
    return out


def save_cookies(cookies: List[dict]) -> None:
    """Write cookies to the saved-login file."""
    selenium_session_file().write_text(
        json.dumps(normalise(cookies), indent=2), encoding="utf-8"
    )


def load_cookies() -> List[Dict[str, str]]:
    """Read cookies from the saved-login file (empty list if none/unreadable)."""
    path = selenium_session_file()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def has_auth_cookie(cookies: List[dict]) -> bool:
    """True if these cookies include a logged-in SU (Drupal) session cookie."""
    return any(str(c.get("name", "")).startswith(AUTH_COOKIE_PREFIX) for c in cookies)


def clear() -> bool:
    """Delete the saved login. Returns True if there was one to delete."""
    path = selenium_session_file()
    if path.exists():
        path.unlink()
        return True
    return False
