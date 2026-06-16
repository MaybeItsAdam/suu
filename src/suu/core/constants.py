"""Constants shared across suu — the SU website addresses and login details."""

from __future__ import annotations

# The Students' Union UCL website everything here talks to.
BASE_URL = "https://studentsunionucl.org"
LOGIN_URL = f"{BASE_URL}/user/login"

# The site runs on Drupal. When you're logged in, Drupal gives your browser a
# session cookie whose name starts with this. We use that to tell whether a
# saved login is still valid.
AUTH_COOKIE_PREFIX = "SSESS"
