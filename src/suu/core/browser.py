"""Browser launch utilities with automatic Playwright Chromium installation."""

from __future__ import annotations

import subprocess
import sys
from typing import Any
import click


def launch_browser_safe(p: Any, headless: bool = False) -> Any:
    """Launch Playwright Chromium browser, automatically downloading the binary if missing."""
    try:
        return p.chromium.launch(headless=headless)
    except Exception as e:
        err_msg = str(e)
        if "Executable doesn't exist" in err_msg or "playwright install" in err_msg or "executable" in err_msg.lower():
            click.echo("Downloading Chromium browser for Playwright (one-time setup)...")
            try:
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                return p.chromium.launch(headless=headless)
            except Exception as install_err:
                raise click.ClickException(
                    f"Failed to auto-install Playwright Chromium browser: {install_err}.\n"
                    "Please run manually: `playwright install chromium`"
                )
        raise
