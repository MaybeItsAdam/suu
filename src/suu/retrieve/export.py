"""Export utilities for suu retrieve commands (CSV, Excel, JSON, Google Sheets).

Kept in step with the Toolbox Connector's ``lib/retrieve/export.js``: same headers
(suu's field names), same CSV shape and the same formula defusing, so a file from
either lines up with the other.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import click

_FORMULA_START = re.compile(r"^[=+\-@\t\r]")
_SIGNED_AMOUNT = re.compile(r"^[+-][£$€]?[0-9.,\s]+$")
_CSV_NEEDS_QUOTES = re.compile(r'[",\r\n]')
_TSV_BREAKS = re.compile(r"[\t\r\n]+")


def defuse_formula(value: str) -> str:
    """Prefix ``'`` to a cell a spreadsheet would run as a formula.

    Names and titles are typed by members, and a member called ``=HYPERLINK(…)``
    shouldn't get to run it in the treasurer's spreadsheet. Signed amounts
    ("-£12.50") and phone numbers ("+44 20 …") are data, not formulas, and are left
    alone. Same rule as the Connector's ``defuseFormula``.
    """
    if not _FORMULA_START.match(value):
        return value
    if _SIGNED_AMOUNT.match(value):
        return value
    return f"'{value}"


def _cell(row: Dict[str, Any], field: str) -> str:
    value = row.get(field)
    return "" if value is None else defuse_formula(str(value))


def _csv_quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"' if _CSV_NEEDS_QUOTES.search(value) else value


def to_csv(rows: List[Dict[str, Any]], fieldnames: List[str]) -> str:
    """RFC 4180 text with CRLF line ends and defused formulas (no BOM; the writer adds it)."""
    lines = [",".join(_csv_quote(f) for f in fieldnames)]
    for row in rows:
        lines.append(",".join(_csv_quote(_cell(row, f)) for f in fieldnames))
    return "\r\n".join(lines) + "\r\n"


def format_google_sheets(rows: List[Dict[str, Any]], fieldnames: List[str]) -> str:
    """Format rows as tab-separated values ready for pasting into Google Sheets.

    Tabs and newlines inside a cell become one space; formulas are defused.
    """
    lines = ["\t".join(fieldnames)]
    for row in rows:
        lines.append("\t".join(_TSV_BREAKS.sub(" ", _cell(row, f)) for f in fieldnames))
    return "\n".join(lines)


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    """Write CSV with a byte-order mark: without it Excel reads the system code page and mangles accented names."""
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        f.write(to_csv(rows, fieldnames))


def write_xlsx(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    """Write an .xlsx with suu's headers and defused cells (openpyxl runs a leading ``=`` as a formula)."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(fieldnames)
    for row in rows:
        ws.append([_cell(row, f) for f in fieldnames])
    wb.save(path)


def warn_first_page_only(what: str) -> None:
    """Say that a paged SU list was only read as far as its first page."""
    click.echo(
        f"Warning: the SU {what} list has more than one page; only the first page was read.",
        err=True,
    )


def export_data(
    rows: List[Dict[str, Any]],
    fieldnames: List[str],
    prefix: str,
    as_csv: bool = False,
    as_xlsx: bool = False,
    as_json: bool = False,
    as_sheets: bool = False,
    output_dir: Optional[str] = None,
    summary: Optional[Dict[str, Any]] = None,
) -> None:
    """Export structured retrieved data according to user flags.

    JSON keeps raw values (no defusing — it isn't opened in a spreadsheet); with a
    ``summary`` it is ``{"summary": …, "rows": […]}``.
    """
    if not rows:
        click.echo("No data to export.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(output_dir) if output_dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)

    if as_json:
        json_path = out_dir / f"{prefix}_{timestamp}.json"
        payload: Any = {"summary": summary, "rows": rows} if summary is not None else rows
        json_path.write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=False) + "\n", encoding="utf-8")
        click.echo(f"Saved {len(rows)} records to JSON: {json_path}")

    if as_csv:
        csv_path = out_dir / f"{prefix}_{timestamp}.csv"
        write_csv(csv_path, rows, fieldnames)
        click.echo(f"Saved {len(rows)} records to CSV: {csv_path}")

    if as_xlsx:
        try:
            xlsx_path = out_dir / f"{prefix}_{timestamp}.xlsx"
            write_xlsx(xlsx_path, rows, fieldnames)
            click.echo(f"Saved {len(rows)} records to Excel: {xlsx_path}")
        except ModuleNotFoundError:
            click.echo(
                "Excel export needs openpyxl. Install it via `pip install openpyxl`.",
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
        # Display first 10 rows in console
        for i, row in enumerate(rows[:10]):
            formatted = ", ".join(f"{k}: {v}" for k, v in list(row.items())[:4])
            click.echo(f" [{i+1}] {formatted}")
        if len(rows) > 10:
            click.echo(f" ... and {len(rows) - 10} more records.")
        click.echo("\nTip: Pass --csv, --xlsx, --json, or --sheets to save or copy the full dataset.")
