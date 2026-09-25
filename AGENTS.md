# Students' Union UCL Toolkit (`suu`)

`suu` is the Python library and CLI suite (`suu`) built to automate Students' Union UCL portal tasks for student leaders, society treasurers, and automated data pipelines.

## Subsystems

1. **`suu login` & `suu logout`**: Top-level authentication provider. Saves browser session state in `~/.suu/playwright_state/default.json` and `selenium_session.json`.
2. **`suu retrieve`**: Authenticated leadership & committee data retrieval for executive officers (Presidents, Treasurers, Vice Presidents):
   - `suu retrieve members <group>`: Official member roster (names, UPIs, emails, membership tiers).
   - `suu retrieve finance <group>`: Live account balances (Account 10 Grant / Account 11 Non-Grant) & reimbursement statuses.
   - `suu retrieve sales <group> [--event <name>]`: The buyer table (name, tier, email, code) — unverified; `--event` only labels the rows.
   - `suu retrieve bookings <group>`: Submitted Union room/space booking request statuses.
   - `suu retrieve committee <group>`: Official registered committee lineup.
   - Export options: `--csv`, `--xlsx`, `--json`, and `--sheets` (copies formatted text for Google Sheets).
3. **`suu forms`**: Playwright browser automation for filling out SU financial forms (`payment_request`, `purchase_request`). Forms are **never submitted automatically** — they are pre-filled and left open for human review.
4. **`suu scrape` & `suu whatson`**: Public data scrapers for Union election results and What's On events calendar.
   - `suu.scrape.gov.GovDocsScraper` discovers the four current governing
     documents, nests Bye-Law appendices through stable slugs, and parses the
     separate passed-amendments archive (including multi-file amendments).
   - `suu.scrape.democracy` (`suu democracy meetings|policies [--json]`) reads
     zone meeting dates off the zone pages' inline directory JSON, papers off
     the hand-edited minutes archive, and the policy register plus each
     policy's page. Pure `parse_*` functions over fixtures in
     `tests/fixtures/democracy/`; a login wall or a page missing its markers
     raises `DemocracyPageError` rather than returning nothing. The archive's
     known dirt (links to the wrong meeting, stale `data-id`s, year typos in
     plain-text entries) is handled and pinned in `tests/test_democracy.py`.
     The policy list checks the page's own status filter matches the one
     asked for, so a renamed query parameter can't file lapsed policies as
     current. `ucl-suu-pipeline`'s `democracy-collect` is the consumer.
5. **`suu seed`**: Non-interactive seeding of election winners directly into `society-tracker`'s `/accountability` tracker (`Officer` and `CommitteeMember` tables).
6. **`suu mcp`**: Model Context Protocol (MCP) server over stdio, enabling AI assistants (Claude, Cursor, Antigravity) to fill forms or query committee data.

## Kept in step with the Toolbox and the Connector

The Toolbox Connector browser extension (`../adams-campus-toolbox-connector`, plan in its
`MASTERPLAN.md`) does in the officer's own browser what `suu forms` and `suu retrieve` do
here. Three things are shared, and **suu is the source of truth** for each:

- **Form definitions** (`src/suu/forms/definitions/*.json`). Copied into the Toolbox by
  `node scripts/sync-suu-forms.mjs` (run in `../adams-campus-toolbox`), which serves them to
  the extension; the extension also bundles them in `forms/`. Toolbox tests fail on drift in
  either copy. Definitions are data only — selectors and step types — and must never click
  Submit (`tests/test_forms_payload.py` checks, as do the Toolbox's).
- **The payload mapping** (`src/suu/forms/payload.py`) ↔ `buildPaymentRequestData` in the
  Toolbox's `src/lib/suuForms/payload.ts`. Change both.
- **Retrieval parsers and exports** (`src/suu/retrieve/`) ↔ the extension's
  `lib/retrieve/*.js`: same selectors, same refusal rule (a page that isn't the expected one
  is an error, never an empty result), same export columns and formula defusing, and shared
  HTML fixtures under `tests/fixtures/retrieve/`. Capture real pages with the extension's
  dev-build "Save this page as a fixture"; fix a parser in both places. Parsers are pure
  `parse_<name>(html) -> Retrieved` functions; the Playwright fetch
  (`common.fetch_page_html`) only navigates, checks where it landed and hands over
  `page.content()`. Tests: `tests/test_retrieve_parsers.py` against
  `tests/fixtures/retrieve/` (copied from the connector's `test/fixtures/retrieve/` —
  recopy when a real page is captured there). Finance, committee, bookings and sales are
  **unverified** against real SU pages (see each module's header); `members` still reads
  the guessed `/group/<slug>/members`, not the connector's verified
  `/clubs-societies/<slug>/members` roster parser.

The executors differ on purpose: Playwright here presses real keys; the extension drives the
Chosen dropdown by setting its hidden `<select>` and triggering `chosen:updated`, because
synthetic key events carry no key code in Firefox.

## Environment & Testing

```bash
# Install package & dependencies with uv
uv sync
uv run pytest

# Run CLI
uv run suu --help
uv run suu login
uv run suu retrieve members "Volunteering Society" --xlsx
```

## Cloud Run & Headless Execution

Headless environment authentication (e.g. GCP Cloud Run Jobs) is handled via environment variables:
- `SUU_AUTH_STATE_BASE64`: Base64-encoded Playwright `storage_state.json`.
- `SUU_AUTH_STATE_JSON`: Raw JSON string of Playwright `storage_state.json`.

`suu.retrieve.browser` automatically detects these variables when running unattended in Cloud Run.
