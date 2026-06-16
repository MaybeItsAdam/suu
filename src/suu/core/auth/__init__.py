"""Saving and restoring your SU login so you only sign in once.

Two flavours, because the two halves of suu use different browser tools:

- :mod:`suu.core.auth.selenium_session` — for the scraper (Selenium).
- :mod:`suu.core.auth.playwright_state` — for the form filler (Playwright).

Both store their files under ``~/.suu`` (see :mod:`suu.core.paths`).
"""
