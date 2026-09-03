"""Export utilities for suu retrieve commands (CSV, Excel, JSON, Google Sheets)."""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import click


def format_google_sheets(rows: List[Dict[str, Any]], fieldnames: List[str]) -> str:
    """Format rows as tab-separated values ready for pasting into Google Sheets."""
    lines = ["\t".join(fieldnames)]
    for row in rows:
        line_items = [str(row.get(field, "") or "").replace("\t", " ").replace("\n", " ") for field in fieldnames]
        lines.append("\t".join(line_items))
    return "\n".join(lines)


def export_data(
    rows: List[Dict[str, Any]],
    fieldnames: List[str],
    prefix: str,
    as_csv: bool = False,
    as_xlsx: bool = False,
    as_json: bool = False,
    as_sheets: bool = False,
    output_dir: Optional[str] = None,
) -> None:
    """Export structured retrieved data according to user flags."""
    if not rows:
        click.echo("No data to export.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(output_dir) if output_dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)

    if as_json:
        json_path = out_dir / f"{prefix}_{timestamp}.json"
        json_path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
        click.echo(f"Saved {len(rows)} records to JSON: {json_path}")

    if as_csv:
        csv_path = out_dir / f"{prefix}_{timestamp}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        click.echo(f"Saved {len(rows)} records to CSV: {csv_path}")

    if as_xlsx:
        try:
            import pandas as pd
            xlsx_path = out_dir / f"{prefix}_{timestamp}.xlsx"
            df = pd.DataFrame(rows)
            df.to_excel(xlsx_path, index=False)
            click.echo(f"Saved {len(rows)} records to Excel: {xlsx_path}")
        except ModuleNotFoundError:
            click.echo(
                "Excel export needs openpyxl and pandas. Install them via `pip install pandas openpyxl`.",
                err=True,
            )

    if as_sheets:
        try:
            import pyperclip
            tsv_text = format_google_sheets(rows, fieldnames)
            pyperclip.copy(tsv_text)
            click.echo(f"Copied {len(rows)} records to your clipboard in Google Sheets format!")
            click.echo("Open Google Sheets and press Cmd+V / Ctrl+V to paste.")
        except ModuleNotFoundError:
            click.echo(
                "Clipboard export needs pyperclip. Install it via `pip install pyperclip`.",
                err=True,
            )
        except Exception as e:
            click.echo(f"Could not copy to clipboard: {e}", err=True)

    # Print summary if no specific export flag was passed
    if not (as_csv or as_xlsx or as_json or as_sheets):
        click.echo(f"\nRetrieved {len(rows)} records for {prefix}:")
        click.echo("-" * 50)
        # Display first 5 rows in console
        for i, row in enumerate(rows[:10]):
            formatted = ", ".join(f"{k}: {v}" for k, v in list(row.items())[:4])
            click.echo(f" [{i+1}] {formatted}")
        if len(rows) > 10:
            click.echo(f" ... and {len(rows) - 10} more records.")
        click.echo("\nTip: Pass --csv, --xlsx, --json, or --sheets to save or copy the full dataset.")
