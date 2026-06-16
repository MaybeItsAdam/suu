"""The work behind `suu forms fill` and `suu forms login`.

`fill`  opens a browser, fills a form from your data, and leaves it open for you
        to check and submit yourself (it never submits for you).
`login` opens a browser so you can log in to the SU site once; your login is
        then saved so the form filler can reuse it.

Ported from SUU-MCP's ``scripts/run_form.py`` and ``scripts/save_auth.py``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import click

from suu.core.constants import LOGIN_URL
from suu.core.paths import playwright_state_file
from suu.forms.executor import FormExecutor
from suu.forms.loader import auth_file_for, list_form_ids, load_form_definition
from suu.forms.schema import FormDefinition


async def _run_form(form_def: FormDefinition, data: dict, auth_file: Optional[str]) -> None:
    executor = FormExecutor(headless=False)
    try:
        await executor.start()
        if auth_file:
            click.echo(f"Using your saved login: {auth_file}")
            await executor.load_auth(auth_file)
        await executor.execute(form_def, data)
        click.echo("\nAll done — the form is filled in.")
        click.echo("Check it over in the browser window, then submit it yourself if it looks right.")
        click.echo("(Nothing has been submitted for you.)")
        click.echo("\nPress Enter here to close the browser...")
        input()
    except Exception as e:
        click.echo(f"Something went wrong while filling the form: {e}", err=True)
    finally:
        await executor.stop()


def fill(form_id: str, data_path: Optional[str], auth_file: Optional[str]) -> None:
    """Fill a built-in form (e.g. ``payment_request``) from a JSON data file."""
    # form_id may be a built-in id, or a path to a custom definition file.
    if Path(form_id).exists():
        form_def = FormDefinition.model_validate_json(Path(form_id).read_text())
    else:
        try:
            form_def = load_form_definition(form_id)
        except FileNotFoundError as e:
            raise click.ClickException(str(e))

    data: dict = {}
    if data_path:
        try:
            data = json.loads(Path(data_path).read_text())
        except Exception as e:
            raise click.ClickException(f"Couldn't read your data file '{data_path}': {e}")

    # Check you're logged in before making you type anything.
    resolved_auth = auth_file or str(auth_file_for(form_def.form_id))
    if not Path(resolved_auth).exists():
        raise click.ClickException(
            "You're not logged in yet. Run this first, then try again:\n\n"
            "    suu forms login\n"
        )

    click.echo(f"Filling form: {form_def.form_id}")
    click.echo("This form will NOT be submitted — you'll get to check it first.")
    click.echo("------------------------------------------------")

    # Ask for any required values the data file didn't provide.
    for field in form_def.fields:
        if field.type == "click":
            continue
        if field.name not in data and field.required:
            prompt = f"Enter value for '{field.name}'"
            if field.description:
                prompt += f" ({field.description})"
            try:
                val = click.prompt(prompt, default="", show_default=False)
            except (KeyboardInterrupt, click.Abort):
                click.echo("\nCancelled — nothing was changed.")
                sys.exit(1)
            if val.strip():
                data[field.name] = val

    click.echo("\nOpening the browser...")
    asyncio.run(_run_form(form_def, data, resolved_auth))


def login(form_id: str = "default", url: Optional[str] = None) -> None:
    """Open a browser, let the user log in to the SU site, and save the login."""
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as e:  # pragma: no cover - guarded by CLI extra check
        raise click.ClickException(f"Missing browser support ({e.name}).")

    auth_path = playwright_state_file(form_id)

    # Prefer the form's own URL if we know this form; otherwise the SU login page.
    target = url
    if not target:
        try:
            target = load_form_definition(form_id).url
        except FileNotFoundError:
            target = LOGIN_URL

    click.echo("A browser window is opening so you can log in.")
    click.echo("Log in to the Students' Union website the normal way.")
    click.echo("When you're logged in, just CLOSE THE BROWSER WINDOW — your login will be saved.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(target)
        try:
            page.wait_for_event("close", timeout=0)
        except KeyboardInterrupt:
            click.echo("\nSaving your login...")
        except Exception:
            pass  # browser closed

        try:
            context.storage_state(path=str(auth_path))
            click.echo(f"\nDone — your login is saved ({auth_path}).")
            click.echo("You can now use `suu forms fill` and the AI assistant.")
        except Exception as e:
            click.echo(
                f"\nCouldn't save your login (did the window close too quickly?): {e}",
                err=True,
            )
        finally:
            browser.close()
