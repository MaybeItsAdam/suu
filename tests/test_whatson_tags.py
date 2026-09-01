"""What's On event tags: the SU's own taxonomy, off the listing page.

The list view the calendar is scraped from carries a title, a time, a venue
and a group — nothing that says what *kind* of thing an event is. The tags
are on each listing's own page, in a Drupal taxonomy field, and they are the
only structured signal of the sort ("Social Impact", "Free", "Careers").
"""
import pytest

pytest.importorskip("bs4")

from bs4 import BeautifulSoup

from suu.scrape.whatson import parse_event_tags


def soup(html):
    return BeautifulSoup(html, "html.parser")


TAGS_FIELD = """
<div class="field field--name-field-event-tags field--type-entity-reference">
  <ul class="links field__items">
    <li><a href="/tags/community-research-initiative">Community Research Initiative</a></li>
    <li><a href="/tags/content/social-impact">Social Impact</a></li>
    <li><a href="/tags/volunteering">Volunteering</a></li>
    <li><a href="/tags/free">Free</a></li>
  </ul>
</div>
"""


def test_reads_slug_and_label_for_each_tag():
    assert parse_event_tags(soup(TAGS_FIELD)) == [
        {"slug": "community-research-initiative", "label": "Community Research Initiative"},
        {"slug": "social-impact", "label": "Social Impact"},
        {"slug": "volunteering", "label": "Volunteering"},
        {"slug": "free", "label": "Free"},
    ]


def test_slug_is_the_last_segment_because_the_taxonomy_is_not_flat():
    """`/tags/content/social-impact` and `/tags/volunteering` sit at different
    depths. Matching on a `/tags/<slug>` prefix sees one and misses the other,
    which is exactly the tag anything cares about."""
    slugs = [t["slug"] for t in parse_event_tags(soup(TAGS_FIELD))]
    assert "social-impact" in slugs
    assert "volunteering" in slugs


def test_ignores_links_outside_the_tag_field():
    html = """
    <a href="/tags/not-mine">Nav tag</a>
    """ + TAGS_FIELD
    slugs = [t["slug"] for t in parse_event_tags(soup(html))]
    assert "not-mine" not in slugs


def test_ignores_non_tag_hrefs_inside_the_field():
    html = """
    <div class="field--name-field-event-tags">
      <ul><li><a href="/whats-on/venue/marshgate-ucl-east">Marshgate</a></li>
          <li><a href="/tags/free">Free</a></li></ul>
    </div>
    """
    assert parse_event_tags(soup(html)) == [{"slug": "free", "label": "Free"}]


def test_deduplicates_a_slug_listed_twice():
    html = """
    <div class="field--name-field-event-tags">
      <ul><li><a href="/tags/free">Free</a></li>
          <li><a href="/tags/free/">Free</a></li></ul>
    </div>
    """
    assert len(parse_event_tags(soup(html))) == 1


def test_a_page_with_no_tag_field_is_empty_not_an_error():
    """A login-gated volunteering listing answers the login page. Empty is
    "the page said nothing", never "this event is untagged"."""
    assert parse_event_tags(soup("<div>Log in</div>")) == []
