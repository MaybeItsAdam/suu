# su/society — public club and society pages (real)

- **Pages**: `https://studentsunionucl.org/clubs-societies/<slug>` —
  `hiking-club.html`, `chess-society.html`; `not-found.html` is what the SU serves for a
  slug that doesn't exist.
- **Real or synthetic**: real, saved whole (untrimmed).
- **Captured**: 2026-09-18.
- **Redacted**: no — public pages.
- **Read by**: `ucl-suu-pipeline`'s `society-onboard` tests
  (`pipeline/tests/test_society_onboard.py`) through its copy in
  `pipeline/tests/fixtures/su_society/` — sync with `python -m pipeline.tools.sync_samples`
  there; `pipeline/tests/test_samples_drift.py` fails on drift. Its colour cases were
  computed from these exact files, so a re-capture means re-deriving them.
