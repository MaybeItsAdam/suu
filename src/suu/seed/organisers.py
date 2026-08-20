"""Match a scraped election group name onto a ucl-tools `Organiser` row.

`CommitteeMember.organiserId` is a soft link that gives a roster its logo,
colour and society page. It used to be set by exact `name.trim().lower()`
comparison in ucl-tools' `scripts/seed_committees.ts`, which for the 2026-27
Leadership Race left 81 of 395 groups unlinked — and not one of those 81 was
an exact match, so the whole gap was naming. Two flavours:

  1. The same group under a different name. The SU writes `93% Club Society`
     where the Organiser is `93% Club`, `Basketball Club (Wheelchair)` where
     it's `Wheelchair Basketball Club`, `… Studies Society (SSEES)` where it's
     `… Studies Society`. One even carried a double space. These must LINK.

  2. No Organiser row at all — the per-team sports splits the SU elects
     separately (`Football Club (Men's)`, `(RUMS Women's)`) and roughly fifty
     ordinary societies that never got a row. These must CREATE.

`match_organiser` draws that line deliberately conservatively: it links only
when two names differ by decoration, and creates otherwise. A wrong CREATE is
one duplicate row an admin can merge; a wrong LINK silently fuses two
different societies' committees, events and access grants together.

Kept in step with `ucl-tools/scripts/reconcile_committee_organisers.ts`, which
does the same job as a one-off backfill for a year already seeded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

# Words carrying no identity — two names differing only by these are the same
# group. `social` is here because the SU registers a committee's social
# sub-committee as its own election group ("International Students' Network
# Social"), which is not a separate society.
#
# Note what is deliberately absent: `men's`, `women's`, `rums` and anything
# else distinguishing one squad from another. Those differences are real and
# must produce separate Organisers.
DECORATION = frozenset(
    {"society", "soc", "club", "network", "committee", "social", "the", "of", "and", "ucl"}
)

# Grammatical filler an acronym skips over. Narrower than DECORATION on
# purpose: SELCS expands to "School of European Languages and Culture
# **S**ociety", so "society" contributes its initial and must stay.
ACRONYM_SKIP = frozenset({"of", "and", "the", "for"})

_ACRONYM_RE = re.compile(r"^(.*?)\s*\(([A-Z]{3,})\)\s*$")
_PUNCT_RE = re.compile(r"[^a-z0-9'%\s]")

# Names the token rules can't reconcile but a human can. Keep this short and
# explicit — it is the escape hatch, not the mechanism.
ALIASES: dict[str, str] = {
    # The SU renamed this network; "Parents" was added and "Part-time" recased.
    "Mature, Part-Time, Parents & Carers Network": "Mature, Part-time & Carers Network",
}


def _tokens(name: str) -> list[str]:
    """Lowercase, curly apostrophes straightened, punctuation to spaces, runs of
    whitespace collapsed. The whitespace collapse alone fixes
    `Women's  Students' Network`, which differs from the Organiser by one
    stray space."""
    lowered = name.lower().replace("‘", "'").replace("’", "'")
    return [t for t in _PUNCT_RE.sub(" ", lowered).split() if t]


def strip_self_acronym(name: str) -> str:
    """Drop a trailing parenthesised acronym that expands to the name itself.

    Matched as a **prefix** of the initials, minimum three letters, because the
    SU appends "Society" to names whose acronym predates it: SSEES is "School
    of Slavonic and East European Studies", so the Organiser "… Studies
    Society" yields initials SSEES*S*. SELCS consumes the whole name. A prefix
    rule covers both without a per-name exception.

    Not a substring test, which is what this was first: "RUMS" *contains* the
    "M" of "Music Society", so `Music Society (RUMS)` linked onto the main
    Music Society — two different societies with different committees, quietly
    fused. With the prefix rule, initials "MS" doesn't start with "RUMS", so it
    creates. (`Football Club (RUMS Men's)` never reaches here — not all-caps.)
    """
    m = _ACRONYM_RE.match(name)
    if not m:
        return name
    base, acronym = m.group(1), m.group(2)
    initials = "".join(t[0] for t in _tokens(base) if t not in ACRONYM_SKIP).upper()
    return base if initials.startswith(acronym) else name


def identity_tokens(name: str) -> frozenset[str]:
    """The tokens that actually distinguish this group from another."""
    return frozenset(t for t in _tokens(strip_self_acronym(name)) if t not in DECORATION)


def organiser_type(group_type: str) -> str:
    """`GenericElectionScraper`'s `group_type` -> `Organiser.type`."""
    if group_type == "NetworkCommittee":
        return "Network"
    if group_type == "Club":
        return "Club"
    return "Society"


@dataclass
class OrganiserMatch:
    """`organiser_id` is None when the caller should create one."""

    organiser_id: Optional[str]
    organiser_name: Optional[str]
    why: str


def match_organiser(
    group_name: str, organisers: Iterable[dict[str, Any]]
) -> OrganiserMatch:
    """Find the Organiser this election group belongs to, or signal a create.

    Links on an explicit alias or on identity-token equality (after decoration
    and self-acronyms are removed). Everything else creates — including every
    per-team sports split, which is the intended outcome: those squads run
    separate committees and usually separate Instagram accounts.
    """
    organisers = list(organisers)

    aliased = ALIASES.get(group_name)
    if aliased:
        for o in organisers:
            if o["name"] == aliased:
                return OrganiserMatch(o["id"], o["name"], "explicit alias")

    mine = identity_tokens(group_name)
    if not mine:
        return OrganiserMatch(None, None, "no identity tokens")

    for o in organisers:
        if identity_tokens(o["name"]) == mine:
            return OrganiserMatch(o["id"], o["name"], "same identity tokens")

    # Report the nearest miss so a log line says *why* it created, rather than
    # leaving "create" to be taken on trust.
    nearest: Optional[tuple[str, list[str]]] = None
    for o in organisers:
        theirs = identity_tokens(o["name"])
        if theirs - mine:
            continue  # not a subset — not comparable
        extra = sorted(mine - theirs)
        if extra and (nearest is None or len(extra) < len(nearest[1])):
            nearest = (o["name"], extra)

    why = (
        f"distinct from {nearest[0]!r} by {', '.join(repr(e) for e in nearest[1])}"
        if nearest
        else "no comparable Organiser"
    )
    return OrganiserMatch(None, None, why)


# ---------------------------------------------------------------------------
# Role display ordering
# ---------------------------------------------------------------------------

# Mirrors ROLE_PRIORITY in ucl-tools' scripts/seed_committees.ts — the two must
# agree or a re-seed silently reorders every committee page.
_ROLE_PRIORITY: list[tuple[str, int]] = [
    ("president", 0),
    ("treasurer", 1),
    ("secretary", 2),
    ("social secretary", 3),
    ("welfare", 4),
    ("vice president", 5),
]


def role_order(role: str) -> int:
    """Display order for a committee role; 50 for anything unrecognised.

    Longest match wins, so "social secretary" beats the plain "secretary"
    substring inside it.
    """
    lowered = role.lower()
    best, best_len = 50, -1
    for needle, order in _ROLE_PRIORITY:
        if needle in lowered and len(needle) > best_len:
            best, best_len = order, len(needle)
    return best
