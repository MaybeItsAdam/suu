# su/retrieve — authenticated society-admin pages (synthetic)

- **Pages**: `https://studentsunionucl.org/group/<slug>/{finance,committee,room-bookings,events}`
  as signed-in committee members see them; the members roster the Connector verified
  lives at `/clubs-societies/<slug>/members?page=<n>`.
- **Real or synthetic**: **all synthetic.** Each file encodes the parser's guess at a
  page nobody has captured yet; see the `UNVERIFIED` block at the top of each parser
  (`src/suu/retrieve/*.py`, Connector `lib/retrieve/*.js`).
  `login.html` stands in for the SU login wall, `unrelated.html` for some other page,
  `layout-table.html` for a layout table that must not be read as data.
- **Captured**: written 2026-09-25 in the Connector (`test/fixtures/retrieve/`), moved
  here as the original.
- **Redacted**: n/a (invented values). A real capture replacing one of these comes from
  the Connector's **Save a redacted capture** (dev builds; ticket sales needs its SU
  page linked first) and must still be checked by hand against the redaction rule in
  `../../README.md`. Save it here as `<retriever>.html`, not under its download name.
- **Read by**: `tests/test_retrieve_parsers.py` here; the Connector's
  `test/retrieve.test.mjs` via its synced copy (`node scripts/sync-samples.mjs` there,
  drift-checked by `test/samples-drift.test.mjs`).
- Keep the file names: both test suites load them by name (`<retriever>.html`).
