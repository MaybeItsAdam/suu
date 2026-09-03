# Students' Union UCL Toolkit (`suu`)

`suu` is the Python library and CLI suite (`suu`) built to automate Students' Union UCL portal tasks for student leaders, society treasurers, and automated data pipelines.

## Subsystems

1. **`suu login` & `suu logout`**: Top-level authentication provider. Saves browser session state in `~/.suu/playwright_state/default.json` and `selenium_session.json`.
2. **`suu retrieve`**: Authenticated leadership & committee data retrieval for executive officers (Presidents, Treasurers, Vice Presidents):
   - `suu retrieve members <group>`: Official member roster (names, UPIs, emails, membership tiers).
   - `suu retrieve finance <group>`: Live account balances (Account 10 Grant / Account 11 Non-Grant) & reimbursement statuses.
   - `suu retrieve sales <group> [--event <name>]`: Event ticket sales, revenue metrics, and door lists.
   - `suu retrieve bookings <group>`: Submitted Union room/space booking request statuses.
   - `suu retrieve committee <group>`: Official registered committee lineup.
   - Export options: `--csv`, `--xlsx`, `--json`, and `--sheets` (copies formatted text for Google Sheets).
3. **`suu forms`**: Playwright browser automation for filling out SU financial forms (`payment_request`, `purchase_request`). Forms are **never submitted automatically** — they are pre-filled and left open for human review.
4. **`suu scrape` & `suu whatson`**: Public data scrapers for Union election results and What's On events calendar.
5. **`suu seed`**: Non-interactive seeding of election winners directly into `society-tracker`'s `/accountability` tracker (`Officer` and `CommitteeMember` tables).
6. **`suu mcp`**: Model Context Protocol (MCP) server over stdio, enabling AI assistants (Claude, Cursor, Antigravity) to fill forms or query committee data.
7. **`suu poll`**: Background worker polling the web app receipt gatherer queue (`/api/receipts`) to pre-fill reimbursement forms.

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
