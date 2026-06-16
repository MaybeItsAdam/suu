"""`suu mcp setup` — find your AI apps and connect them to suu automatically.

The whole point is that a student leader runs one command and their AI app can
use the SU tools, without ever opening a settings file.
"""

from __future__ import annotations

import click

from suu.core.clients import detect_installed, manual_instructions


def run_setup(remove: bool = False) -> None:
    """Detect installed AI apps and connect (or disconnect) suu."""
    installed = detect_installed()

    if not installed:
        click.echo("I couldn't find any AI apps I know how to set up automatically.\n")
        click.echo(manual_instructions())
        return

    if remove:
        click.echo("Removing suu from your AI apps...\n")
        for client in installed:
            click.echo("  " + client.disconnect())
        click.echo("\nDone.")
        return

    # Show what we found, in plain language.
    click.echo("Found these AI apps on your computer:\n")
    for client in installed:
        click.echo(f"  ✅ {client.name}")
    click.echo("")

    # Let the user choose; default is "all of them", the safe, common choice.
    if not click.confirm("Connect suu to all of these?", default=True):
        chosen = []
        for client in installed:
            if click.confirm(f"  Connect suu to {client.name}?", default=True):
                chosen.append(client)
    else:
        chosen = installed

    if not chosen:
        click.echo("\nOkay — nothing changed.")
        return

    click.echo("")
    for client in chosen:
        click.echo("  " + client.connect())

    click.echo(
        "\nAll set! One last step: fully QUIT and reopen your AI app "
        "(e.g. quit Claude Desktop completely, then open it again)."
    )
    click.echo("After it restarts, look for the tools/plug icon — you should see 'suu' listed.")
    click.echo("\nIf you haven't logged in to the SU site yet, run:  suu forms login")
