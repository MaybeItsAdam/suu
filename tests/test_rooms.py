"""Tests for suu rooms (UCL campus room timetable & free room query)."""

from __future__ import annotations

from datetime import datetime, timezone
from click.testing import CliRunner

from suu.cli import cli
from suu.rooms.expansion import parse_weeks, london_wall_clock_to_utc, expand_event
from suu.rooms.query import list_rooms, find_free_rooms


def test_parse_weeks():
    assert parse_weeks("wks 20-25, 27") == [20, 21, 22, 23, 24, 25, 27]
    assert parse_weeks("wks 10") == [10]
    assert parse_weeks("") == []


def test_london_wall_clock_to_utc():
    dt = london_wall_clock_to_utc("2026-09-01", "09:00")
    assert dt.tzinfo == timezone.utc
    assert dt.year == 2026
    assert dt.month == 9
    assert dt.day == 1


def test_expand_event():
    ev = {
        "day": "Monday",
        "start_time": "09:00",
        "end_time": "10:00",
        "weeks": "wks 1-2",
        "title": "Test Class",
    }
    cal = {
        1: {1: "2026-09-07"},
        2: {1: "2026-09-14"},
    }
    occs = expand_event(ev, cal)
    assert len(occs) == 2
    assert occs[0]["date"] == "2026-09-07"
    assert occs[1]["date"] == "2026-09-14"


def test_list_rooms():
    all_rms = list_rooms()
    assert len(all_rms) > 0
    sc_rms = list_rooms("Student Centre")
    assert len(sc_rms) > 0
    assert all("Student Centre" in r["building"] for r in sc_rms)


def test_cli_rooms_help():
    runner = CliRunner()
    res = runner.invoke(cli, ["rooms", "--help"])
    assert res.exit_code == 0
    assert "free" in res.output
    assert "query" in res.output
    assert "list" in res.output
