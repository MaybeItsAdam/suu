"""Where suu keeps your saved logins and other files.

Everything lives in one tidy folder in your home directory (``~/.suu``) so you
always know where to look, and so removing it logs you out of everything.
Advanced users can point this somewhere else with the ``SUU_HOME`` env var.
"""

from __future__ import annotations

import os
from pathlib import Path


def suu_home() -> Path:
    """Return the suu home folder, creating it if it doesn't exist yet."""
    override = os.environ.get("SUU_HOME")
    home = Path(override).expanduser() if override else Path.home() / ".suu"
    home.mkdir(parents=True, exist_ok=True)
    return home


def selenium_session_file() -> Path:
    """The saved login used by the scraper (`suu scrape …`)."""
    return suu_home() / "selenium_session.json"


def playwright_state_dir() -> Path:
    """Folder holding the saved logins used by the form filler (`suu forms`/`mcp`)."""
    d = suu_home() / "playwright"
    d.mkdir(parents=True, exist_ok=True)
    return d


def playwright_state_file(form_id: str = "default") -> Path:
    """The saved login for a particular form (defaults to a shared one)."""
    return playwright_state_dir() / f"{form_id}_auth.json"
