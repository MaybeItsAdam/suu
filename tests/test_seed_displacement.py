"""By-election displacement: refilling a seat whose holder resigned.

A resignation is invisible in the scraped data — the Leadership Race says
Alice is Treasurer, Alice resigns, the by-election says Bob is Treasurer, and
nothing records that Alice left. Displacement is therefore an inference, and
these tests pin down that it is only drawn where it is safe.

The unsafe case is real: 180 of the 2,286 (society, role) pairs in the 2026-27
data have more than one holder, and Badminton Club runs six Social
Secretaries. Removing "the previous holder" of a six-person seat would delete
five serving committee members.
"""

from __future__ import annotations

from typing import Any

from suu.seed.election import SeedResult, _displace_prior_holders


class FakeDb:
    """Stands in for `suu.seed.db` — records deletes, serves canned holders."""

    def __init__(self, holders: list[dict[str, Any]]) -> None:
        self._holders = holders
        self.deleted: list[str] = []

    def list_committee_holders(self, client, *, society_name, role, year):
        return list(self._holders)

    def delete_committee_members(self, client, ids):
        self.deleted.extend(ids)


def _run(monkeypatch, holders, *, keep_ids=frozenset(), source="BY-2027") -> tuple:
    fake = FakeDb(holders)
    monkeypatch.setattr("suu.seed.election.db", fake)
    result = SeedResult(
        election_title="t", election_url="u", year="2026-27",
        election_type="by-election", source_election=source,
    )
    _displace_prior_holders(
        None,
        society_name="Chess Society",
        role="Treasurer",
        year="2026-27",
        source_election=source,
        keep_ids=set(keep_ids),
        result=result,
    )
    return fake, result


def test_displaces_the_single_prior_holder(monkeypatch) -> None:
    """The ordinary resignation: one person held the seat, now someone else does."""
    fake, result = _run(
        monkeypatch,
        [
            {"id": "old", "memberName": "Alice", "sourceElection": "LEADERSHIP-2026"},
            {"id": "new", "memberName": "Bob", "sourceElection": "BY-2027"},
        ],
        keep_ids={"new"},
    )
    assert fake.deleted == ["old"]
    assert result.displaced == 1
    assert result.displacement_ambiguous == []


def test_refuses_to_guess_when_several_prior_holders_exist(monkeypatch) -> None:
    """Badminton Club's six Social Secretaries must all survive."""
    fake, result = _run(
        monkeypatch,
        [
            {"id": "a", "memberName": "Alice", "sourceElection": "LEADERSHIP-2026"},
            {"id": "b", "memberName": "Bella", "sourceElection": "LEADERSHIP-2026"},
            {"id": "c", "memberName": "Cara", "sourceElection": "LEADERSHIP-2026"},
            {"id": "new", "memberName": "Bob", "sourceElection": "BY-2027"},
        ],
        keep_ids={"new"},
    )
    assert fake.deleted == []
    assert result.displaced == 0
    assert len(result.displacement_ambiguous) == 1
    # The report must name the people, or it's not actionable.
    assert "Chess Society" in result.displacement_ambiguous[0]
    assert "Alice" in result.displacement_ambiguous[0]
    assert "Cara" in result.displacement_ambiguous[0]


def test_never_displaces_this_election_own_winners(monkeypatch) -> None:
    """A genuine two-seat by-election must not have its winners evict each other."""
    fake, result = _run(
        monkeypatch,
        [
            {"id": "new1", "memberName": "Bob", "sourceElection": "BY-2027"},
            {"id": "new2", "memberName": "Carla", "sourceElection": "BY-2027"},
        ],
        keep_ids={"new1", "new2"},
    )
    assert fake.deleted == []
    assert result.displaced == 0


def test_ignores_rows_from_the_same_election_even_if_not_seen(monkeypatch) -> None:
    """Same-election rows are supersede's business, not displacement's.

    Deleting them here would double-handle a row `--supersede` has already
    decided to keep or remove, on a different rule.
    """
    fake, result = _run(
        monkeypatch,
        [{"id": "stale", "memberName": "Old Bob", "sourceElection": "BY-2027"}],
        keep_ids=set(),
    )
    assert fake.deleted == []


def test_no_prior_holder_is_a_no_op(monkeypatch) -> None:
    """The "extra roles" case — a seat nobody held before. Purely additive."""
    fake, result = _run(
        monkeypatch,
        [{"id": "new", "memberName": "Bob", "sourceElection": "BY-2027"}],
        keep_ids={"new"},
    )
    assert fake.deleted == []
    assert result.displaced == 0
    assert result.displacement_ambiguous == []


def test_untagged_prior_rows_are_still_displaced(monkeypatch) -> None:
    """A row predating the sourceElection backfill has NULL provenance.

    It differs from this election's source, so it counts as a prior holder —
    which is right: the alternative is a resigned officer lingering forever
    because nobody stamped their row.
    """
    fake, result = _run(
        monkeypatch,
        [
            {"id": "old", "memberName": "Alice", "sourceElection": None},
            {"id": "new", "memberName": "Bob", "sourceElection": "BY-2027"},
        ],
        keep_ids={"new"},
    )
    assert fake.deleted == ["old"]
    assert result.displaced == 1
