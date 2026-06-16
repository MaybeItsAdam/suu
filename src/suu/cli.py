"""The `suu` command — one friendly front door for every SU tool.

Run ``suu`` on its own (or ``suu --help``) to see everything it can do.

Subcommands import their heavier machinery only when you actually run them, so
installing just the part you need stays small and fast. If a part isn't
installed yet, we tell you the exact line to copy-paste to add it.
"""

from __future__ import annotations

import sys

import click


def _need_extra(extra: str, error: ModuleNotFoundError) -> "click.ClickException":
    """Build a friendly error telling the user how to install a missing piece."""
    msg = (
        f"This feature needs an extra piece that isn't installed yet "
        f"(missing: {error.name}).\n\n"
        f"Copy-paste this line, press Enter, then try again:\n\n"
        f'    pip install "suu-cli[{extra}]"\n'
    )
    return click.ClickException(msg)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="suu-cli", prog_name="suu")
def cli() -> None:
    """suu — tools for Students' Union UCL.

    Pull data out of the SU website, or have forms filled in for you.
    Pick a command below, or add --help to any command to learn more.
    """


# ---------------------------------------------------------------------------
# scrape  (Phase 1 wires the real commands; stubs keep the tree visible for now)
# ---------------------------------------------------------------------------


@cli.group()
def scrape() -> None:
    """Pull data out of the SU website (election results, and more)."""


@scrape.command()
@click.argument("name", required=False, default=None)
@click.option("--rounds", is_flag=True, help="Include voting rounds data.")
@click.option("--tallies", is_flag=True, help="Include final vote tallies.")
@click.option("--csv", is_flag=True, help="Save the results as a CSV file.")
@click.option("--sheets", is_flag=True, help="Copy the results so you can paste them straight into Google Sheets.")
@click.option("--xlsx", is_flag=True, help="Save the results as an Excel (.xlsx) file.")
@click.option("--upload", is_flag=True, help="Also upload to Supabase (off by default).")
@click.option(
    "--officers-only",
    is_flag=True,
    help="Only union-level officer roles (sabbs + student officers); excludes network committee roles.",
)
@click.option("--key-roles", is_flag=True, help="Only President and Treasurer roles across all groups.")
@click.option("--winners-only", is_flag=True, help="Only winning candidates (drops losers from the output).")
@click.option(
    "--workers",
    type=click.IntRange(1, 32),
    default=6,
    show_default=True,
    help="How many pages to fetch at once (higher is faster).",
)
@click.option("--checkpoint-file", default=None, help="Where to save progress (so an interrupted run can resume).")
@click.option("--resume", is_flag=True, help="Pick up where a previous interrupted run left off.")
def election(
    name: "str | None",
    rounds: bool,
    tallies: bool,
    csv: bool,
    sheets: bool,
    xlsx: bool,
    upload: bool,
    officers_only: bool,
    key_roles: bool,
    winners_only: bool,
    workers: int,
    checkpoint_file: "str | None",
    resume: bool,
) -> None:
    """Scrape an election's candidates and results.

    Give an election NAME (or part of one), or a full URL, or nothing at all to
    browse and pick one. If a NAME matches several, you'll get a numbered list.
    """
    try:
        from suu.scrape.cli import run_election
    except ModuleNotFoundError as e:
        raise _need_extra("scrape", e)
    run_election(
        name=name,
        rounds=rounds,
        tallies=tallies,
        csv=csv,
        sheets=sheets,
        xlsx=xlsx,
        upload=upload,
        officers_only=officers_only,
        key_roles=key_roles,
        winners_only=winners_only,
        workers=workers,
        checkpoint_file=checkpoint_file,
        resume=resume,
    )


@cli.command()
@click.option("--start", default=None, help="Start date (YYYY-MM-DD).")
@click.option("--end", default=None, help="End date (YYYY-MM-DD).")
@click.option("--upload", is_flag=True, help="Also upload to Supabase (off by default).")
def whatson(start: "str | None", end: "str | None", upload: bool) -> None:
    """Scrape the SU 'What's On' events calendar."""
    try:
        from suu.scrape.cli import run_whatson
    except ModuleNotFoundError as e:
        raise _need_extra("scrape", e)
    run_whatson(start=start, end=end, upload=upload)


# ---------------------------------------------------------------------------
# forms
# ---------------------------------------------------------------------------


@cli.group()
def forms() -> None:
    """Fill in SU forms (payment / purchase requests) for you."""


@forms.command("fill")
@click.argument("form_id")
@click.option("--data", "data_path", default=None, help="Path to a JSON file with the form's values.")
@click.option("--auth", "auth_file", default=None, help="Use a specific saved-login file (advanced).")
def forms_fill(form_id: str, data_path: "str | None", auth_file: "str | None") -> None:
    """Fill a form from a data file (leaves it open for you to check & submit).

    FORM_ID is a built-in form like 'payment_request', or a path to your own
    form definition file.
    """
    try:
        from suu.forms.runner import fill
    except ModuleNotFoundError as e:
        raise _need_extra("forms", e)
    fill(form_id=form_id, data_path=data_path, auth_file=auth_file)


@forms.command("login")
@click.argument("form_id", required=False, default="default")
@click.option("--url", default=None, help="Page to open for logging in (advanced).")
def forms_login(form_id: str, url: "str | None") -> None:
    """Log in to the SU site once and save it, so forms can be filled for you."""
    try:
        from suu.forms.runner import login
    except ModuleNotFoundError as e:
        raise _need_extra("forms", e)
    login(form_id=form_id, url=url)


# ---------------------------------------------------------------------------
# mcp
# ---------------------------------------------------------------------------


@cli.group(invoke_without_command=True)
@click.pass_context
def mcp(ctx: click.Context) -> None:
    """Let an AI assistant like Claude fill SU forms.

    Run `suu mcp setup` once to connect your AI apps, or `suu mcp run` to start
    the server yourself.
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@mcp.command("run")
def mcp_run() -> None:
    """Start the MCP server (your AI app normally does this for you)."""
    try:
        from suu.mcp.server import mcp as server
    except ModuleNotFoundError as e:
        raise _need_extra("mcp", e)
    server.run()


@mcp.command("setup")
@click.option("--remove", is_flag=True, help="Disconnect suu from your AI apps instead.")
def mcp_setup(remove: bool) -> None:
    """Find your installed AI apps and connect them to suu automatically."""
    try:
        from suu.mcp.setup import run_setup
    except ModuleNotFoundError as e:
        raise _need_extra("mcp", e)
    run_setup(remove=remove)


# ---------------------------------------------------------------------------
# worker
# ---------------------------------------------------------------------------


@cli.command()
def poll() -> None:
    """Run as a background worker for the receipt-gatherer web app."""
    import asyncio

    try:
        from suu.worker.poll import run_worker
    except ModuleNotFoundError as e:
        raise _need_extra("mcp", e)
    asyncio.run(run_worker())


# ---------------------------------------------------------------------------
# logout  (clears every saved login)
# ---------------------------------------------------------------------------


@cli.command()
def logout() -> None:
    """Forget all saved logins. You'll log in again next time you need to."""
    import shutil

    from suu.core.paths import (
        playwright_state_dir,
        selenium_session_file,
    )

    removed = False

    session = selenium_session_file()
    if session.exists():
        session.unlink()
        removed = True

    pw_dir = playwright_state_dir()
    if any(pw_dir.iterdir()):
        shutil.rmtree(pw_dir)
        removed = True

    if removed:
        click.echo("Done — you've been logged out. You'll be asked to log in next time.")
    else:
        click.echo("You weren't logged in to anything, so there was nothing to clear.")


def main() -> None:
    cli()


if __name__ == "__main__":
    sys.exit(main())
