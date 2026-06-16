from __future__ import annotations

import time
from typing import Optional

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException
from selenium.webdriver.chrome.options import Options

from suu.core.auth import selenium_session
from suu.core.constants import BASE_URL, LOGIN_URL

# How long to wait after a navigation for JS / Cloudflare to settle
_SETTLE = 2.0

# Recycle the driver after this many pages to prevent Chrome OOM crashes
# on large elections (70+ listing pages * many result pages each).
_RECYCLE_EVERY = 50

# Running count of pages fetched on the current driver instance
_page_count: int = 0

# Module-level singleton — one driver for the whole process lifetime
_driver: Optional[webdriver.Chrome] = None


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _make_driver(headless: bool) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(service=webdriver.ChromeService(), options=opts)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def get_selenium_driver(headless: bool = True) -> webdriver.Chrome:
    """Create a standalone Chrome driver.

    Used by scrapers (e.g. What's On) that manage their own browser lifecycle
    rather than going through the shared :func:`get_soup` flow.
    """
    return _make_driver(headless=headless)


def get_driver() -> webdriver.Chrome:
    """Return the singleton headless driver, creating it if needed."""
    global _driver
    if _driver is None:
        _driver = _make_driver(headless=True)
        _restore_cookies(_driver)
    return _driver


def recycle_driver() -> webdriver.Chrome:
    """
    Save cookies, quit the current driver, and start a fresh one.

    Called proactively every _RECYCLE_EVERY pages and reactively whenever
    Chrome crashes with an InvalidSessionIdException.
    """
    global _driver, _page_count
    print("[browser] Recycling Chrome driver to free memory...")

    # Harvest cookies before killing the old driver
    cookies: list[dict] = []
    if _driver is not None:
        try:
            cookies = _driver.get_cookies()
        except Exception:
            cookies = selenium_session.load_cookies()
        try:
            _driver.quit()
        except Exception:
            pass
        _driver = None

    if cookies:
        selenium_session.save_cookies(cookies)

    _page_count = 0
    _driver = _make_driver(headless=True)
    _restore_cookies(_driver)
    print("[browser] Fresh driver ready.")
    return _driver


def quit_driver() -> None:
    """Quit and discard the singleton driver."""
    global _driver
    if _driver is not None:
        try:
            _driver.quit()
        except Exception:
            pass
        _driver = None


# ---------------------------------------------------------------------------
# Page fetching  (the one function scrapers should call)
# ---------------------------------------------------------------------------


def get_soup(url: str) -> Optional[BeautifulSoup]:
    """
    Navigate the singleton driver to *url* and return parsed HTML.

    If the site redirects to the login page, a visible browser window is
    opened so the user can log in.  Once authenticated the original URL is
    retried and its HTML returned.  Cookies are persisted so subsequent runs
    skip the login entirely.

    Proactively recycles the driver every _RECYCLE_EVERY pages to prevent
    Chrome OOM crashes on large elections.  Also catches
    InvalidSessionIdException and WebDriverException mid-scrape and
    transparently recovers with a fresh driver.
    """
    global _page_count

    # Proactive recycle before Chrome runs out of memory
    _page_count += 1
    if _page_count > _RECYCLE_EVERY:
        recycle_driver()

    for attempt in range(2):
        try:
            driver = get_driver()
            driver.get(url)
            time.sleep(_SETTLE)

            # Cloudflare / login redirect?
            if _needs_login(driver):
                _do_login(driver)
                # retry the original page now that we're authenticated
                driver.get(url)
                time.sleep(_SETTLE)

            if _needs_login(driver):
                print(
                    f"[browser] Still not authenticated after login — cannot fetch {url}"
                )
                return None

            return BeautifulSoup(driver.page_source, "html.parser")

        except (InvalidSessionIdException, WebDriverException) as exc:
            if attempt == 0:
                print(
                    f"[browser] Driver error ({type(exc).__name__}), recycling and retrying..."
                )
                recycle_driver()
            else:
                print(f"[browser] Driver error on retry — skipping {url}: {exc}")
                return None


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def _needs_login(driver: webdriver.Chrome) -> bool:
    """Return True if the current page is the Drupal login form."""
    return "/user/login" in driver.current_url


def _is_authenticated(driver: webdriver.Chrome) -> bool:
    """Return True if the driver holds a Drupal authenticated session cookie."""
    return selenium_session.has_auth_cookie(driver.get_cookies())


def _do_login(driver: webdriver.Chrome, timeout: int = 300) -> None:
    """
    Make the driver visible, wait for the user to log in, then re-hide it
    and save the session cookies.
    """
    # Switch to a visible window by opening a new one
    # (we can't make an existing headless window visible, so we open a fresh
    # visible driver, log in there, copy the cookies back, then close it)
    print("\n[auth] A browser window is opening so you can log in.")
    print(f"[auth] Please log in to the Students' Union website at: {LOGIN_URL}")
    print(f"[auth] Waiting up to {timeout}s for you to finish...\n")

    vis = _make_driver(headless=False)
    try:
        # Seed any existing cookies so SSO may auto-login
        vis.get(BASE_URL)
        time.sleep(1)
        for c in selenium_session.load_cookies():
            try:
                vis.add_cookie(c)
            except Exception:
                pass

        vis.get(LOGIN_URL)
        time.sleep(_SETTLE)

        deadline = time.time() + timeout
        while time.time() < deadline:
            if _is_authenticated(vis):
                print("[auth] Login detected — thank you!\n")
                break
            time.sleep(1)
        else:
            raise TimeoutError(f"[auth] Login timed out after {timeout}s.")

        cookies = vis.get_cookies()
    finally:
        vis.quit()

    # Copy cookies into the headless driver
    driver.get(BASE_URL)
    time.sleep(1)
    for c in cookies:
        try:
            driver.add_cookie(c)
        except Exception:
            pass

    selenium_session.save_cookies(cookies)
    print("[auth] Login saved — you won't need to do that again for a while.")


# ---------------------------------------------------------------------------
# Cookie restore / session clearing
# ---------------------------------------------------------------------------


def _restore_cookies(driver: webdriver.Chrome) -> None:
    """Seed a fresh driver with any persisted cookies."""
    cookies = selenium_session.load_cookies()
    if not cookies:
        return
    driver.get(BASE_URL)
    time.sleep(1)
    for c in cookies:
        try:
            driver.add_cookie(c)
        except Exception:
            pass
    print("[auth] Restored your saved login.")


def clear_session() -> None:
    """Delete the saved session file and quit the driver."""
    quit_driver()
    if selenium_session.clear():
        print("[auth] Saved login cleared.")
    else:
        print("[auth] No saved login to clear.")
