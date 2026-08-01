"""The work behind `suu scrape …` and `suu whatson`.

These are plain functions (not Click commands) so the top-level ``suu`` CLI can
declare the options and call in here only once the optional ``scrape`` pieces are
confirmed installed. Ported from suu-scrape's ``main.py``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import click
from dotenv import load_dotenv

from suu.core.plugins import discover_plugins
from suu.scrape.browser import quit_driver
from suu.scrape.scrapers import GenericElectionScraper, get_all_elections

_ = load_dotenv(".env.local")
_ = load_dotenv()


def run_election(
    name: Optional[str],
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
    checkpoint_file: Optional[str],
    resume: bool,
) -> None:
    """Scrape an election by name or direct URL (interactive if ambiguous)."""
    click.echo("Fetching active elections...")

    selected_election: Optional[dict[str, str]] = None

    # Direct URL — skip the search entirely.
    if name and (name.startswith("http://") or name.startswith("https://")):
        selected_election = {"title": name, "url": name}
        click.echo(f"Using direct URL: {name}")

    # If a name was given, search page-by-page and stop as soon as we find
    # a unique match — avoids fetching pages we don't need.
    elif name:
        click.echo(f"Searching for '{name}'...")
        all_elections: list[dict[str, str]] = []
        p = 0
        matches: list[dict[str, str]] = []
        while True:
            page_results = get_all_elections(page=p)
            if not page_results:
                break
            all_elections.extend(page_results)
            matches = [e for e in all_elections if name.lower() in e["title"].lower()]
            # Stop early the moment we have exactly one match
            if len(matches) == 1:
                break
            p += 1

        if not all_elections:
            click.echo("No elections found.")
            quit_driver()
            return

        if len(matches) == 1:
            selected_election = matches[0]
            click.echo(f"Found: {selected_election['title']}")
        elif len(matches) > 1:
            click.echo(f"Multiple matches for '{name}':")
            for i, match in enumerate(matches):
                click.echo(f"  {i + 1}. {match['title']}")
            choice: int = click.prompt(
                "Please enter the number of the election to scrape", type=int
            )
            if 1 <= choice <= len(matches):
                selected_election = matches[choice - 1]
            else:
                click.echo("Invalid selection.")
                quit_driver()
                return
        else:
            click.echo(f"No matches found for '{name}' — listing all elections.")
            # Fall through to interactive mode below with all pages already loaded
            page = 0
            elections = all_elections

    # Interactive mode — page through and let the user pick
    if not selected_election and not name:
        page = 0
        elections = get_all_elections(page=page) if not name else all_elections  # type: ignore[possibly-undefined]

        if not elections:
            click.echo("No elections found on the list page.")
            quit_driver()
            return

        while True:
            if not elections:
                click.echo("No more elections found.")
                break

            click.echo(f"\nAvailable elections (Page {page}):")
            for i, e in enumerate(elections):
                click.echo(f"  {i + 1}. {e['title']}")
            click.echo(f"  {len(elections) + 1}. Next Page")

            choice = click.prompt(
                "Please enter the number of the election to scrape", type=int
            )

            if choice == len(elections) + 1:
                page += 1
                elections = get_all_elections(page=page)
                continue
            elif 1 <= choice <= len(elections):
                selected_election = elections[choice - 1]
                break
            else:
                click.echo("Invalid selection.")
                quit_driver()
                return

    if not selected_election:
        click.echo("Aborted.")
        quit_driver()
        return

    click.echo(
        f"Starting scrape for: {selected_election['title']} ({selected_election['url']})"
    )

    scraper = GenericElectionScraper(selected_election["url"])
    checkpoint_target = checkpoint_file or scraper.default_checkpoint_path()

    filters = []
    if officers_only:
        filters.append("union & network officers only")
    if key_roles:
        filters.append("presidents & treasurers only")
    if winners_only:
        filters.append("winners only")
    if filters:
        click.echo("Filters: " + ", ".join(filters))
    click.echo(f"Checkpoint: {checkpoint_target}")
    if resume:
        click.echo("Resume mode: enabled")
    click.echo(f"Workers: {workers}")
    if upload:
        click.echo("Supabase upload: enabled")

    click.echo("")

    current_page: list[int] = [-1]

    def on_page(page: int) -> None:
        if page != current_page[0]:
            current_page[0] = page
            click.echo(f"  [page {page + 1}] scanning positions...")

    position_count: list[int] = [0]

    def on_position(idx: int, title: str) -> None:
        position_count[0] = idx
        if not winners_only:
            click.echo(f"    [{idx}] {title}")

    def on_winner(role: str, group: str, winner_names: list[str]) -> None:
        label = f"{group}: {role}" if group and group != "Union" else role
        names = ", ".join(winner_names)
        click.echo(f"    WINNER  {label} — {names}")

    scraped_data: dict[str, Any] = scraper.scrape(
        include_rounds=rounds,
        include_tallies=tallies,
        officers_only=officers_only,
        key_roles_only=key_roles,
        winners_only=winners_only,
        progress_callback=on_position,
        page_callback=on_page,
        winner_callback=on_winner if winners_only else None,
        checkpoint_path=checkpoint_target,
        resume=resume,
        max_workers=workers,
    )

    quit_driver()

    count = len(scraped_data.get("positions", []))
    click.echo(f"\nDone — {count} position(s) kept after filters.")

    context: dict[str, Any] = {
        "app_name": "suu",
        "version": "0.1.0",
        "scrape_type": "election",
        "election_name": selected_election["title"],
        "export_csv": csv,
        "export_sheets": sheets,
        "export_xlsx": xlsx,
        "upload_supabase": upload,
    }

    run_plugins(scraped_data, context)


def run_whatson(start: Optional[str], end: Optional[str], upload: bool) -> None:
    """Scrape What's On calendar events."""
    from suu.scrape.whatson import WhatsOnScraper

    click.echo("Starting What's On scraper...")
    scraper = WhatsOnScraper(start_date=start, end_date=end)
    scraped_data: dict[str, Any] = scraper.scrape()

    quit_driver()

    count = len(scraped_data.get("events", []))
    click.echo(f"Scraped {count} events.")

    context: dict[str, Any] = {
        "app_name": "suu",
        "scrape_type": "whatson",
        "upload_supabase": upload,
    }

    run_plugins(scraped_data, context)


def run_gov(scope: str, output_dir: str, write_docs: bool) -> None:
    """Fetch UCL SU governing documents (Bye-Laws, Code of Practice, Clubs & Societies Regulations) as PDF + text.

    Deliberately doesn't tail-call run_plugins() like run_election/run_whatson
    do: the export-plugin system is built for tabular scrape data, and
    JsonExportPlugin has no export-flag gate the way the csv/xlsx/clipboard
    plugins do — it always json.dumps() whatever scrape() returned. If that
    ever held raw PDF bytes, `default=str` would stringify them into a
    garbage multi-MB file dropped in the CWD. Writing straight to disk here
    instead. Also skips quit_driver(): this scraper is plain requests/
    BeautifulSoup, no Selenium driver ever gets created.
    """
    from suu.scrape.gov import GovDocsScraper

    click.echo(f"Fetching governing documents (scope: {scope})...")
    scraper = GovDocsScraper()
    entries = scraper.discover(scope)  # type: ignore[arg-type]
    if not entries:
        click.echo("No documents found for that scope.")
        return

    results = scraper.fetch(entries)

    out_dir = Path(output_dir)
    pdf_dir = out_dir / "pdf"
    text_dir = out_dir / "text"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    doc_targets: list[Path] = []
    if write_docs:
        doc_targets.append(Path("docs/governing-documents"))
        sibling_repo = Path("../ucl-tools")
        if sibling_repo.is_dir():
            doc_targets.append(sibling_repo / "docs" / "governing-documents")

    for result in results:
        (pdf_dir / f"{result.slug}.pdf").write_bytes(result.pdf_bytes)
        (text_dir / f"{result.slug}.md").write_text(result.formatted_text, encoding="utf-8")

        for target in doc_targets:
            try:
                target.mkdir(parents=True, exist_ok=True)
                (target / f"{result.slug}.md").write_text(result.formatted_text, encoding="utf-8")
            except OSError as e:
                click.echo(f"  (skipped writing to {target}: {e})")

        version_suffix = f" ({result.version_label})" if result.version_label else ""
        click.echo(f"  {result.slug}: {result.title}{version_suffix}")

    click.echo(f"\nDone — {len(results)} document(s) saved to {out_dir}/")
    if doc_targets:
        click.echo("Also copied formatted text to: " + ", ".join(str(t) for t in doc_targets))


def run_plugins(data: dict[str, Any], context: dict[str, Any]) -> None:
    """Run every export plugin, honouring the --upload gate for Supabase."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    plugins_dir = os.path.join(base_dir, "plugins")
    plugin_classes = discover_plugins(plugins_dir)

    for PluginClass in plugin_classes:
        try:
            module_name = str(getattr(PluginClass, "__module__", "")).lower()
            class_name = str(getattr(PluginClass, "__name__", "")).lower()
            is_supabase_plugin = "supabase" in module_name or "supabase" in class_name
            if is_supabase_plugin and not context.get("upload_supabase", False):
                click.echo(f"Skipping {PluginClass.__name__} (enable with --upload).")
                continue

            plugin_instance = PluginClass()
            plugin_instance.setup(config={})
            plugin_instance.run(data, context)
        except Exception as e:
            click.echo(f"Error running plugin {PluginClass.__name__}: {e}")
