"""The name ladder that decides link-vs-create for an election group.

The stakes are asymmetric and the tests are written around that: a wrong
CREATE is one duplicate row an admin merges, a wrong LINK silently fuses two
societies' committees, events and access grants. Everything below that asserts
a link is a case seen in the real 2026-27 Leadership Race data.
"""

from __future__ import annotations

import pytest

from suu.seed.organisers import (
    identity_tokens,
    match_organiser,
    organiser_type,
    role_order,
    strip_self_acronym,
)

# A slice of the real Organiser table, chosen to include every trap.
ORGANISERS = [
    {"id": "o_93", "name": "93% Club", "type": "Club"},
    {"id": "o_wheel", "name": "Wheelchair Basketball Club", "type": "Club"},
    {"id": "o_basket", "name": "Basketball Club", "type": "Club"},
    {"id": "o_football", "name": "Football Club", "type": "Club"},
    {"id": "o_music", "name": "Music Society", "type": "Society"},
    {"id": "o_intl", "name": "International Students' Network", "type": "Network"},
    {"id": "o_women", "name": "Women's Students' Network", "type": "Network"},
    {"id": "o_selcs", "name": "School of European Languages and Culture Society", "type": "Society"},
    {"id": "o_ssees", "name": "School of Slavonic and Eastern European Studies Society", "type": "Society"},
    {"id": "o_mature", "name": "Mature, Part-time & Carers Network", "type": "Network"},
    {"id": "o_indian", "name": "Indian Society", "type": "Society"},
]


def _link(name: str) -> str:
    m = match_organiser(name, ORGANISERS)
    assert m.organiser_id is not None, f"{name!r} should link, got: {m.why}"
    return m.organiser_id


def _create(name: str) -> str:
    m = match_organiser(name, ORGANISERS)
    assert m.organiser_id is None, (
        f"{name!r} should create, but linked to {m.organiser_name!r} ({m.why})"
    )
    return m.why


# ---------------------------------------------------------------------------
# Links — the same group under a different name
# ---------------------------------------------------------------------------


def test_links_trailing_decoration_suffix() -> None:
    assert _link("93% Club Society") == "o_93"


def test_links_reordered_words() -> None:
    # The SU writes the qualifier in brackets; the Organiser leads with it.
    assert _link("Basketball Club (Wheelchair)") == "o_wheel"


def test_links_across_a_stray_double_space() -> None:
    assert _link("Women's  Students' Network") == "o_women"


def test_links_a_social_subcommittee_to_its_parent() -> None:
    # The SU registers a committee's social sub-committee as its own election
    # group; it is not a separate society.
    assert _link("International Students' Network Social") == "o_intl"
    assert _link("Women's Students' Network Social") == "o_women"


def test_links_self_acronym_consuming_whole_name() -> None:
    assert _link("School of European Languages and Culture Society (SELCS)") == "o_selcs"


def test_links_self_acronym_shorter_than_the_name() -> None:
    # SSEES predates the "Society" suffix, so the initials are SSEESS and the
    # acronym is a prefix of them.
    assert (
        _link("School of Slavonic and Eastern European Studies Society (SSEES)") == "o_ssees"
    )


def test_links_via_explicit_alias() -> None:
    assert _link("Mature, Part-Time, Parents & Carers Network") == "o_mature"


# ---------------------------------------------------------------------------
# Creates — genuinely distinct groups
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Football Club (Men's)",
        "Football Club (Women's)",
        "Football Club (RUMS Men's)",
        "Football Club (RUMS Women's)",
        "Basketball Club (Men's)",
    ],
)
def test_creates_per_team_sports_splits(name: str) -> None:
    # The SU elects each squad separately and they run their own committees
    # and Instagram accounts, so each gets its own Organiser.
    why = _create(name)
    assert "distinct from" in why


def test_creates_rums_variant_rather_than_fusing_it() -> None:
    """The regression this ladder was rewritten for.

    An earlier substring test matched "RUMS" against the initials "M" of
    "Music Society" and linked the medical school's music society onto the
    main one — two societies, two committees, silently merged.
    """
    _create("Music Society (RUMS)")


def test_creates_a_society_with_no_comparable_organiser() -> None:
    assert _create("Actuarial Society") == "no comparable Organiser"


def test_creates_when_an_extra_word_changes_the_subject() -> None:
    # "Indian Music Society" is neither "Indian Society" nor "Music Society".
    # Both are one token away, so which one the reason names is arbitrary —
    # assert the decision and that it explains itself, not the tie-break.
    why = _create("Indian Music Society")
    assert "distinct from" in why
    assert "'Indian Society'" in why or "'Music Society'" in why


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


def test_strip_self_acronym_only_strips_real_expansions() -> None:
    assert strip_self_acronym("Music Society (RUMS)") == "Music Society (RUMS)"
    assert (
        strip_self_acronym("School of European Languages and Culture Society (SELCS)")
        == "School of European Languages and Culture Society"
    )
    # Two letters is below the minimum — too weak a signal to act on.
    assert strip_self_acronym("Media Society (MS)") == "Media Society (MS)"


def test_identity_tokens_drop_decoration_but_keep_distinguishers() -> None:
    assert identity_tokens("Football Club") == frozenset({"football"})
    assert identity_tokens("Football Club (Men's)") == frozenset({"football", "men's"})
    assert identity_tokens("UCL Chess Society") == frozenset({"chess"})


def test_organiser_type_maps_scraper_group_types() -> None:
    assert organiser_type("NetworkCommittee") == "Network"
    assert organiser_type("Club") == "Club"
    assert organiser_type("Society") == "Society"
    assert organiser_type("Other") == "Society"


def test_role_order_longest_match_wins() -> None:
    # "social secretary" must beat the plain "secretary" inside it, or every
    # social secretary sorts into the secretary slot.
    assert role_order("Social Secretary") == 3
    assert role_order("Secretary") == 2
    assert role_order("President") == 0
    assert role_order("Treasurer") == 1
    assert role_order("Welfare & Wellbeing Officer") == 4
    assert role_order("Kit Secretary") == 2
    assert role_order("Backgammon Captain") == 50


def test_committee_group_type_maps_student_media_to_society() -> None:
    """The 12 "Other" groups are student media — Rare FM, Pi Media, Cheese
    Grater… They ran in the Leadership Race, but the upstream JSON export
    filtered to the three documented values and dropped all 97 of their
    positions, which is why they had no roster and looked defunct."""
    from suu.seed.organisers import committee_group_type

    assert committee_group_type("Other") == "Society"
    assert committee_group_type("Network") == "NetworkCommittee"
    assert committee_group_type("Society") == "Society"
    assert committee_group_type("Club") == "Club"
    assert committee_group_type("NetworkCommittee") == "NetworkCommittee"


def test_organiser_type_handles_a_bare_network() -> None:
    assert organiser_type("Network") == "Network"
