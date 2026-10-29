import pytest

from suu.scrape.scrapers import GenericElectionScraper


def _classify(title: str) -> tuple[str, str, str]:
    # The method reads nothing from the instance; skip the browser setup.
    return GenericElectionScraper._classify_position(
        object.__new__(GenericElectionScraper), title
    )


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "LGBTQ+ Students' Network Social Secretary",
            ("LGBTQ+ Students' Network", "NetworkCommittee", "Social Secretary"),
        ),
        (
            "Mature, Part-Time, Parents & Carers Network Social Secretary",
            ("Mature, Part-Time, Parents & Carers Network", "NetworkCommittee", "Social Secretary"),
        ),
        ("POC Network Secretary", ("POC Network", "NetworkCommittee", "Secretary")),
        (
            "Commuter Students' Network Campaigns Representative",
            ("Commuter Students' Network", "NetworkCommittee", "Campaigns Representative"),
        ),
        (
            "Disabled Students' Network Neurodivergent Rep",
            ("Disabled Students' Network", "NetworkCommittee", "Neurodivergent Rep"),
        ),
        ("Faculty of Laws UG Rep", ("Union", "Union", "Faculty of Laws UG Rep")),
        ("Chess Society: Treasurer", ("Chess Society", "Society", "Treasurer")),
    ],
)
def test_classify_position(title, expected):
    assert _classify(title) == expected
