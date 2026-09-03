"""Authenticated browser / HTTP session helpers for suu retrieve."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
import click

from suu.core.browser import launch_browser_safe
from suu.core.paths import playwright_state_file, selenium_session_file
from suu.core.constants import AUTH_COOKIE_PREFIX


def resolve_auth_file(auth_file: Optional[str] = None) -> Path:
    """Return the resolved storage_state file or default login state file.
    
    Checks environment variables (SUU_AUTH_STATE_BASE64, SUU_AUTH_STATE_JSON)
    for headless Cloud Run Jobs.
    """
    if auth_file:
        return Path(auth_file)

    # 1. Cloud Run Support: Base64 JSON in environment variable
    b64_state = os.environ.get("SUU_AUTH_STATE_BASE64")
    if b64_state:
        try:
            decoded = base64.b64decode(b64_state)
            tmp_path = Path(tempfile.gettempdir()) / "suu_cloud_run_auth.json"
            tmp_path.write_bytes(decoded)
            return tmp_path
        except Exception:
            pass

    # 2. Raw JSON string in environment variable
    raw_json = os.environ.get("SUU_AUTH_STATE_JSON")
    if raw_json:
        try:
            tmp_path = Path(tempfile.gettempdir()) / "suu_cloud_run_auth.json"
            tmp_path.write_text(raw_json, encoding="utf-8")
            return tmp_path
        except Exception:
            pass

    # 3. Local state file
    return playwright_state_file("default")


def check_authenticated(auth_file: Optional[str] = None) -> Path:
    """Ensure the user has logged in via suu login, raising a Click error if missing."""
    path = resolve_auth_file(auth_file)
    if not path.exists():
        raise click.ClickException(
            "You are not logged in yet. Please log in to Students' Union UCL first by running:\n\n"
            "    suu login\n"
        )
    return path


def load_storage_state(auth_file: Optional[str] = None) -> Dict[str, Any]:
    """Load JSON storage state (Playwright state format)."""
    path = check_authenticated(auth_file)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise click.ClickException(f"Failed to read saved login state at '{path}': {e}")


def has_valid_auth_cookie(state: Dict[str, Any]) -> bool:
    """Check if storage state contains the Drupal auth session cookie."""
    cookies = state.get("cookies", [])
    return any(str(c.get("name", "")).startswith(AUTH_COOKIE_PREFIX) for c in cookies)
