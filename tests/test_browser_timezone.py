"""The scraping browser renders pages in London time on any host.

The SU's What's On list view formats each listing's clock in the browser's
zone, and the scraper labels what it reads as Europe/London. Cloud Run runs in
UTC, so without a pin every BST listing was read an hour early.
"""
import pytest

pytest.importorskip("selenium")

import suu.scrape.browser as browser


class _FakeChrome:
    def __init__(self, service=None, options=None):
        self.service = service
        self.cdp = []

    def execute_script(self, *args):
        pass

    def execute_cdp_cmd(self, cmd, params):
        self.cdp.append((cmd, params))


@pytest.fixture
def fake_chrome(monkeypatch):
    monkeypatch.setattr(browser.webdriver, "Chrome", _FakeChrome)
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.delenv("SUU_CHROMEDRIVER", raising=False)


def test_the_browser_process_runs_in_london(fake_chrome):
    driver = browser._make_driver(headless=True)

    assert driver.service.env["TZ"] == "Europe/London"


def test_the_tab_is_pinned_to_london(fake_chrome):
    driver = browser._make_driver(headless=True)

    assert ("Emulation.setTimezoneOverride", {"timezoneId": "Europe/London"}) in driver.cdp


def test_the_pin_keeps_the_rest_of_the_environment(fake_chrome, monkeypatch):
    monkeypatch.setenv("SUU_TEST_MARKER", "kept")

    driver = browser._make_driver(headless=True)

    assert driver.service.env["SUU_TEST_MARKER"] == "kept"
