"""Tests for suu retrieve commands and login functionality."""

from __future__ import annotations

import json
from pathlib import Path
from click.testing import CliRunner

from suu.cli import cli
from suu.retrieve.browser import has_valid_auth_cookie, check_authenticated
from suu.retrieve.export import format_google_sheets, export_data
from suu.retrieve.members import slugify_group
import pytest
import click


def test_slugify_group():
    assert slugify_group("Volunteering Society") == "volunteering-society"
    assert slugify_group("Chess Club!") == "chess-club"
    assert slugify_group("https://studentsunionucl.org/group/film-society/members") == "film-society"


def test_format_google_sheets():
    rows = [
        {"name": "Alice Smith", "email": "alice@ucl.ac.uk", "role": "President"},
        {"name": "Bob Jones", "email": "bob@ucl.ac.uk", "role": "Treasurer"},
    ]
    tsv = format_google_sheets(rows, ["name", "email", "role"])
    assert "name\temail\trole" in tsv
    assert "Alice Smith\talice@ucl.ac.uk\tPresident" in tsv


def test_has_valid_auth_cookie():
    valid_state = {"cookies": [{"name": "SSESS12345", "value": "abc"}]}
    invalid_state = {"cookies": [{"name": "analytics", "value": "xyz"}]}
    assert has_valid_auth_cookie(valid_state) is True
    assert has_valid_auth_cookie(invalid_state) is False


def test_check_authenticated_unauthenticated(tmp_path, monkeypatch):
    missing_file = tmp_path / "missing.json"
    with pytest.raises(click.ClickException) as exc_info:
        check_authenticated(str(missing_file))
    assert "You are not logged in yet" in str(exc_info.value)


def test_cli_login_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["login", "--help"])
    assert result.exit_code == 0
    assert "Log in to the Students' Union UCL website" in result.output


def test_cli_forms_login_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["forms", "login", "--help"])
    assert result.exit_code == 0
    assert "Log in to the SU site once" in result.output


def test_cli_retrieve_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["retrieve", "--help"])
    assert result.exit_code == 0
    assert "Retrieve authenticated leadership & committee data" in result.output
    assert "members" in result.output
    assert "finance" in result.output
    assert "sales" in result.output
    assert "bookings" in result.output
    assert "committee" in result.output
