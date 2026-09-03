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
        f'    pip install "suu[{extra}]"\n'
    )
    return click.ClickException(msg)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="suu", prog_name="suu")
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


@cli.command()
@click.argument("scope", type=click.Choice(["byelaws", "cop", "csregs", "all"]), default="all")
@click.option(
    "--output-dir",
    default="./gov-docs",
    show_default=True,
    help="Where to save fetched PDFs and formatted text.",
)
@click.option("--check", is_flag=True, help="Check remote documents against local files to detect updates.")
@click.option("--diff", is_flag=True, help="Display a unified text diff of remote changes vs local files.")
def gov(scope: str, output_dir: str, write_docs: bool, check: bool, diff: bool) -> None:
    """Fetch UCL SU governing documents (Bye-Laws, Code of Practice, Clubs & Societies Regulations) as PDF + text."""
    try:
        from suu.scrape.cli import run_gov
        from suu.scrape.gov import check_gov_docs, diff_gov_docs
    except ModuleNotFoundError as e:
        raise _need_extra("scrape", e)

    if diff:
        res = diff_gov_docs(scope=scope, output_dir=output_dir)
        click.echo(res)
        return

    if check:
        res = check_gov_docs(scope=scope, output_dir=output_dir)
        click.echo(f"Governing documents check ({scope}):")
        for item in res:
            status = "CHANGED" if item["changed"] else "UP TO DATE"
            click.echo(f"  [{status}] {item['title']} ({item['slug']})")
        return

    run_gov(scope=scope, output_dir=output_dir, write_docs=write_docs)


# ---------------------------------------------------------------------------
# rooms (UCL campus room timetables & free room finder)
# ---------------------------------------------------------------------------


try:
    from suu.rooms.cli import rooms
    cli.add_command(rooms)
except Exception:
    pass


# ---------------------------------------------------------------------------
# seed  (non-interactive election -> ucl-tools Officer table)
# ---------------------------------------------------------------------------


@cli.group()
def seed() -> None:
    """Seed ucl-tools' Officer accountability tracker from a live election (non-interactive)."""


@seed.command("election")
@click.argument("name_or_url")
@click.option("--year", required=True, help='Academic year label, e.g. "2026-27".')
@click.option(
    "--election-type",
    type=click.Choice(["leadership", "reps", "by-election"]),
    default=None,
    help="Defaults to a best-effort guess from the election URL — pass explicitly when running unattended.",
)
@click.option(
    "--source-election",
    default=None,
    help="Defaults to the resolved election URL. Scopes --supersede to this election's own rows.",
)
@click.option("--term-starts", "term_starts_at", default=None, help="ISO date (optional).")
@click.option("--term-ends", "term_ends_at", default=None, help="ISO date (optional).")
@click.option(
    "--supersede",
    is_flag=True,
    help="After seeding, delete this election's prior Officer and CommitteeMember rows that this run didn't produce.",
)
@click.option(
    "--no-committees",
    "no_committees",
    is_flag=True,
    help="Seed only union-level Officer rows, skipping every society committee.",
)
@click.option(
    "--displace/--no-displace",
    "displace",
    default=None,
    help=(
        "Remove the previous holder of a seat this election refilled (i.e. a "
        "resignation). Defaults on for --election-type by-election. Acts only "
        "where exactly one prior holder exists; multi-holder seats are "
        "reported rather than guessed at."
    ),
)
@click.option(
    "--resume",
    is_flag=True,
    help=(
        "Reuse the checkpoint from a previous run of this same election instead "
        "of re-scraping it. A full Leadership Race is ~2,100 positions."
    ),
)
@click.option("--dry-run", is_flag=True, help="Scrape and classify, but don't write anything.")
def seed_election_cmd(
    name_or_url: str,
    year: str,
    election_type: "str | None",
    source_election: "str | None",
    term_starts_at: "str | None",
    term_ends_at: "str | None",
    supersede: bool,
    no_committees: bool,
    displace: "bool | None",
    resume: bool,
    dry_run: bool,
) -> None:
    """Seed winners from an election into Officer and CommitteeMember.

    NAME_OR_URL works like `suu scrape election`'s NAME, except it must
    resolve to exactly one election — no interactive disambiguation, since
    this is meant to run unattended too.

    Union-level positions become `Officer` rows; every society, club and
    network committee position becomes a `CommitteeMember` row soft-linked to
    an `Organiser` (created when the group has no row yet).
    """
    try:
        from suu.seed.election import ElectionResolutionError, seed_election
    except ModuleNotFoundError as e:
        raise _need_extra("scrape", e)

    def on_progress(*, role: str, name: str) -> None:
        click.echo(f"  {role}: {name}")

    try:
        result = seed_election(
            name_or_url,
            year=year,
            election_type=election_type,
            source_election=source_election,
            term_starts_at=term_starts_at,
            term_ends_at=term_ends_at,
            supersede=supersede,
            seed_committees=not no_committees,
            displace=displace,
            resume=resume,
            dry_run=dry_run,
            progress=on_progress,
        )
    except ElectionResolutionError as e:
        raise click.ClickException(str(e))
    except (ValueError, RuntimeError) as e:
        raise click.ClickException(str(e))

    click.echo("")
    if dry_run:
        click.echo(f"Dry run — would seed from: {result.election_title} ({result.election_url})")
    else:
        click.echo(f"Seeded from: {result.election_title} ({result.election_url})")
        click.echo(f"  Officers    created {result.created}, updated {result.updated}")
        if not no_committees:
            click.echo(
                f"  Committees  created {result.committee_created}, "
                f"updated {result.committee_updated}"
            )
            click.echo(
                f"  Organisers  linked {result.organisers_linked}, "
                f"created {result.organisers_created}"
            )
        if supersede:
            click.echo(
                f"  Superseded  {result.superseded_removed} officers, "
                f"{result.committee_superseded_removed} committee rows"
            )
        if result.displaced:
            click.echo(f"  Displaced   {result.displaced} previous seat holders")
    if result.positions_skipped_no_winner:
        click.echo(f"  Positions with no declared winner: {result.positions_skipped_no_winner}")
    if result.displacement_ambiguous:
        # Never silently dropped: these are seats a person now has to settle.
        click.echo(
            f"\n  {len(result.displacement_ambiguous)} seat(s) had several prior "
            "holders, so the previous occupant was left in place. Check by hand:"
        )
        for line in result.displacement_ambiguous:
            click.echo(f"    - {line}")


# ---------------------------------------------------------------------------
# login (top-level authenticated session provider)
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("form_id", required=False, default="default")
@click.option("--url", default=None, help="Page to open for logging in (advanced).")
def login(form_id: str, url: "str | None") -> None:
    """Log in to the Students' Union UCL website once and save your session state."""
    try:
        from suu.forms.runner import login as run_login
    except ModuleNotFoundError as e:
        raise _need_extra("forms", e)
    run_login(form_id=form_id, url=url)


# ---------------------------------------------------------------------------
# retrieve (authenticated leadership / committee data)
# ---------------------------------------------------------------------------


try:
    from suu.retrieve.cli import retrieve
    cli.add_command(retrieve)
except Exception:
    pass


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
@click.pass_context
def forms_login(ctx: click.Context, form_id: str, url: "str | None") -> None:
    """Log in to the SU site once and save it (alias to `suu login`)."""
    ctx.invoke(login, form_id=form_id, url=url)


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
