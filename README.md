<p align="center">
  <img src="https://raw.githubusercontent.com/MaybeItsAdam/suu/main/assets/logo.png" alt="suu logo" width="120" height="120">
</p>

<h1 align="center">suu</h1>

One friendly toolkit for **Students' Union UCL**, made to save student leaders time.
It does two jobs:

- **Get data out** of the SU website — election results and the What's On calendar.
- **Fill SU forms** for you — payment and purchase requests — either from a file, or by
  letting an AI assistant (like Claude) do it through chat.

Everything runs through a single command: `suu`.

> Not affiliated with UCL or the Students' Union UCL.

---

## Install

You only install the parts you need. Pick one:

```bash
pip install "suu[scrape]"   # just the data scraper
pip install "suu[forms]"    # just the form filler (from a file)
pip install "suu[mcp]"      # form filler + AI assistant support
pip install "suu[all]"      # everything
```

New to the command line? `pip` comes with Python. If `pip` isn't found, install Python
first from https://python.org, then try again.

If you installed `forms`, `mcp`, or `all`, run this one extra line to set up the browser
the form filler uses:

```bash
playwright install chromium
```

## First steps

```bash
suu --help          # see everything suu can do
suu scrape --help   # learn about a group of commands
```

The first time you do something that needs the SU website, a browser window opens so you
can log in normally. suu remembers it afterwards, so you only do that once. To forget all
saved logins at any time: `suu logout`.

---

## Getting data out (`scrape`)

```bash
# Browse and pick an election interactively
suu scrape election

# Search by name (you'll get a list if several match)
suu scrape election "Leadership"

# Use a direct link, keep only winners, and save to Excel
suu scrape election https://studentsunionucl.org/election/... --winners-only --xlsx

# What's On events between two dates
suu whatson --start 2026-09-01 --end 2026-09-30
```

Handy options for `scrape election`: `--csv`, `--xlsx`, `--sheets` (copies for pasting into
Google Sheets), `--winners-only`, `--officers-only`, `--key-roles`, `--resume` (continue an
interrupted run). See `suu scrape election --help` for the full list.

To also upload results to Supabase, add `--upload` and set `SUPABASE_URL` / `SUPABASE_KEY`
(see `.env.example`).

---

## Filling forms (`forms`)

```bash
# Log in once (opens a browser; log in, then close the window)
suu forms login

# Fill a form from a data file — opens a browser, fills it in, leaves it for you to check
suu forms fill payment_request --data my_payment.json
```

Built-in forms: `payment_request` (reimbursements) and `purchase_request` (paying invoices /
asking the Union to buy something). suu **never submits** a form — it fills it in and leaves
the browser open so you can review and submit yourself.

---

## Letting an AI assistant fill forms (`mcp`)

```bash
suu mcp setup        # finds your AI apps (Claude Desktop, Claude Code, Cursor…) and connects them
```

That's it — `setup` writes the right settings for you (backing up anything it changes), then
tells you to restart your AI app. To disconnect later: `suu mcp setup --remove`.

If you'd rather wire it up by hand, the server command is `suu mcp run` (it speaks MCP over
stdio). `suu mcp setup` will print a copy-paste snippet if it can't find a known app.

---

## Running the form-filling worker (`poll`)

For the receipt-gatherer web app: `suu poll` claims queued jobs and fills the form for each
one. It needs a couple of environment variables (put them in a `.env` file — see
`.env.example`):

| Variable | What it's for |
| :--- | :--- |
| `APP_URL` | Address of the receipt-gatherer web app (required) |
| `WORKER_AUTH_TOKEN` | Shared secret the worker uses to read jobs |
| `WORKER_DEFAULT_FORM_ID` | Form to use if a job doesn't say (default: `payment_request`) |

The worker uses the same saved login as `suu forms` — run `suu forms login` first.

---

## Where suu keeps things

Everything lives in one folder: `~/.suu` (saved logins, downloads). Delete it, or run
`suu logout`, to start fresh. Advanced users can move it with the `SUU_HOME` env var.

---

## Contributing / releasing

Maintainers: see the **[DevOps guide](docs/DEVOPS.md)** for local setup, the build/test/
publish pipeline, and how to cut a release.
