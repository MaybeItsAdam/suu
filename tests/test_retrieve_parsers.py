"""Retrieval parsers and exports, mirroring the Connector's test/retrieve.test.mjs.

The HTML fixtures under tests/fixtures/retrieve/ are copied from the Connector's
test/fixtures/retrieve/ and are synthetic: each encodes suu's assumptions about a page
nobody has captured yet. See the UNVERIFIED block at the top of each parser.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import click
import pytest

from suu.retrieve import export as export_mod
from suu.retrieve.bookings import parse_bookings
from suu.retrieve.common import (
    SignedOutError,
    UnrecognisedPageError,
    check_landing,
)
from suu.retrieve.committee import parse_committee
from suu.retrieve.export import (
    defuse_formula,
    export_data,
    format_google_sheets,
    to_csv,
    write_xlsx,
)
from suu.retrieve.finance import parse_finance
from suu.retrieve.members import parse_members
from suu.retrieve.sales import parse_sales

FIXTURES = Path(__file__).parent / "fixtures" / "retrieve"
RETRIEVE_SRC = Path(__file__).parent.parent / "src" / "suu" / "retrieve"


def html(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


PARSERS = {
    "finance": parse_finance,
    "committee": parse_committee,
    "bookings": parse_bookings,
    "sales": parse_sales,
}


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_finance_reads_balances_and_rows_skipping_short_rows():
    result = parse_finance(html("finance"))
    assert result.summary == {"grant_account_balance": "£1,234.56", "subs_account_balance": "£78.90"}
    assert result.rows == [
        {"request_id": "PR-1001", "title": 'Room hire, "Welcome" social', "amount": "£45.00", "status": "Approved", "date": "01/10/2026"},
        {"request_id": "PR-1002", "title": "Printing", "amount": "-£12.50", "status": "Submitted", "date": ""},
    ]
    assert result.has_more is False


def test_finance_empty_requests_view_is_an_answer_not_a_refusal():
    result = parse_finance(html("finance-no-requests"))
    assert result.summary == {"grant_account_balance": "£0.00", "subs_account_balance": "£10.00"}
    assert result.rows == []


def test_finance_missing_balance_is_none_never_a_made_up_zero():
    result = parse_finance('<div class="grant-account-balance">£5.00</div>')
    assert result.summary == {"grant_account_balance": "£5.00", "subs_account_balance": None}


def test_committee_role_name_and_optional_email():
    assert parse_committee(html("committee")).rows == [
        {"role": "President", "name": "Ada Lovelace", "email": "ada.lovelace.25@ucl.ac.uk"},
        {"role": "Treasurer", "name": "Charles Babbage", "email": ""},
    ]


def test_bookings_defaults_status_and_reports_pager():
    result = parse_bookings(html("bookings"))
    assert result.rows == [
        {"booking_ref": "RB-77", "title": "Weekly rehearsal", "room": "Bloomsbury Theatre Studio", "date": "03/10/2026 18:00", "status": "Confirmed"},
        {"booking_ref": "RB-78", "title": "AGM", "room": "Cruciform LT1", "date": "", "status": "Requested"},
    ]
    assert result.has_more is True


def test_sales_buyer_tier_email_and_optional_code():
    rows = parse_sales(html("sales")).rows
    assert len(rows) == 2
    assert rows[0] == {"buyer_name": "Grace Hopper", "ticket_tier": "Member", "email": "grace.hopper.24@ucl.ac.uk", "ticket_code": "TKT-0001"}
    assert rows[1]["ticket_code"] == ""


@pytest.mark.parametrize("name", PARSERS)
def test_refuses_login_page_as_signed_out(name):
    with pytest.raises(SignedOutError) as exc_info:
        PARSERS[name](html("login"))
    assert isinstance(exc_info.value, click.ClickException)
    assert "not signed in" in exc_info.value.message
    assert "suu login" in exc_info.value.message


@pytest.mark.parametrize("name", PARSERS)
def test_refuses_unrelated_page_rather_than_returning_nothing(name):
    with pytest.raises(UnrecognisedPageError):
        PARSERS[name](html("unrelated"))


@pytest.mark.parametrize("name", PARSERS)
def test_refuses_page_whose_only_table_is_the_wrong_shape(name):
    with pytest.raises(UnrecognisedPageError):
        PARSERS[name](html("layout-table"))


def test_members_uses_the_same_refusal_rule():
    page = "<table><tbody><tr><td>Ada Lovelace</td><td>Standard</td><td>ada@ucl.ac.uk</td></tr></tbody></table>"
    assert parse_members(page).rows == [
        {"name": "Ada Lovelace", "email": "ada@ucl.ac.uk", "membership_type": "Standard", "purchase_date": ""}
    ]
    for name, error in (("login", SignedOutError), ("unrelated", UnrecognisedPageError), ("layout-table", UnrecognisedPageError)):
        with pytest.raises(error):
            parse_members(html(name))


@pytest.mark.parametrize("name", PARSERS)
def test_every_unverified_parser_still_says_so_at_the_top(name):
    source = (RETRIEVE_SRC / f"{name}.py").read_text(encoding="utf-8")
    assert "UNVERIFIED against a real SU page" in source
    assert f"lib/retrieve/{name}.js" in source


# ---------------------------------------------------------------------------
# Landing URL
# ---------------------------------------------------------------------------


def test_landing_on_login_or_off_site_is_signed_out():
    for url in (
        "https://studentsunionucl.org/user/login?destination=/group/chess/finance",
        "https://login.microsoftonline.com/x",
    ):
        with pytest.raises(SignedOutError):
            check_landing(url)
    check_landing("https://studentsunionucl.org/group/chess/finance")


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

FIELDS = ["name", "amount"]


def test_csv_crlf_rfc4180_quoting_and_headers():
    csv_text = to_csv([{"name": 'Room hire, "Welcome"', "amount": "£45.00"}, {"name": "Line\nbreak", "amount": None}], FIELDS)
    assert csv_text == 'name,amount\r\n"Room hire, ""Welcome""",£45.00\r\n"Line\nbreak",\r\n'


def test_csv_file_has_bom_and_crlf(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    export_data([{"name": "Zoë", "amount": "£1"}], FIELDS, prefix="finance_chess", as_csv=True, output_dir=str(tmp_path))
    [path] = tmp_path.glob("finance_chess_*.csv")
    assert path.read_bytes() == "﻿name,amount\r\nZoë,£1\r\n".encode("utf-8")


def test_csv_and_tsv_defuse_formulas_but_leave_signed_amounts_and_phone_numbers():
    rows = [
        {"name": '=HYPERLINK("http://x","y")', "amount": "-£12.50"},
        {"name": "@SUM(A1)", "amount": "+44 20 7679 2000"},
        {"name": "-cmd", "amount": "+1"},
    ]
    assert format_google_sheets(rows, FIELDS).split("\n") == [
        "name\tamount",
        "'=HYPERLINK(\"http://x\",\"y\")\t-£12.50",
        "'@SUM(A1)\t+44 20 7679 2000",
        "'-cmd\t+1",
    ]
    assert '"\'=HYPERLINK(""http://x"",""y"")",-£12.50' in to_csv(rows, FIELDS)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=1+1", "'=1+1"),
        ("+SUM(A1)", "'+SUM(A1)"),
        ("\tx", "'\tx"),
        ("\rx", "'\rx"),
        ("-£12.50", "-£12.50"),
        ("+$3", "+$3"),
        ("-€1.234,56", "-€1.234,56"),
        ("-", "'-"),
        ("plain", "plain"),
    ],
)
def test_defuse_formula_rule(value, expected):
    assert defuse_formula(value) == expected


def test_tsv_flattens_tabs_and_newlines_inside_a_cell():
    assert format_google_sheets([{"name": "a\tb\nc", "amount": ""}], FIELDS) == "name\tamount\na b c\t"


def test_xlsx_cells_are_defused(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "out.xlsx"
    write_xlsx(path, [{"name": "=HYPERLINK(\"http://x\")", "amount": "-£12.50"}], FIELDS)
    ws = openpyxl.load_workbook(path).active
    assert [c.value for c in ws[1]] == FIELDS
    assert [c.value for c in ws[2]] == ["'=HYPERLINK(\"http://x\")", "-£12.50"]
    assert ws["A2"].data_type == "s"


def test_json_keeps_raw_values_with_summary_when_given(tmp_path):
    rows = [{"name": "=raw", "amount": "£1"}]
    export_data(rows, FIELDS, prefix="plain", as_json=True, output_dir=str(tmp_path))
    export_data(rows, FIELDS, prefix="summary", as_json=True, output_dir=str(tmp_path), summary={"grant": "£2"})
    [plain] = tmp_path.glob("plain_*.json")
    [with_summary] = tmp_path.glob("summary_*.json")
    assert json.loads(plain.read_text(encoding="utf-8")) == rows
    assert json.loads(with_summary.read_text(encoding="utf-8")) == {"summary": {"grant": "£2"}, "rows": rows}


def test_export_filenames_are_prefix_timestamp(tmp_path, monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 25, 14, 3, 7)

    monkeypatch.setattr(export_mod, "datetime", FixedDatetime)
    export_data([{"name": "a", "amount": "b"}], FIELDS, prefix="finance_chess", as_csv=True, output_dir=str(tmp_path))
    assert [p.name for p in tmp_path.iterdir()] == ["finance_chess_20260925_140307.csv"]
