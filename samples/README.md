# Samples — the one home for pages and payloads

Every saved Students' Union UCL page and every sample of our own data shapes lives
here, once. `suu` is already the source of truth for knowledge about the SU site
(form definitions, retrieval parsers), so it is the source of truth for the pages
those parsers read, too. The other repos (`../adams-campus-toolbox-connector`,
`../ucl-suu-pipeline`, `../adams-campus-toolbox`) keep **copies** in their own test
fixtures so their CI stays self-contained, and a drift test in each fails when a
copy stops matching the file here.

## Layout

```
samples/
  su/<page-kind>/<name>.html        pages the SU (or a service it uses) serves
  native/<shape>/<name>.json|txt    shapes our own code produces
```

Each `<page-kind>/` and `<shape>/` has a `README.md` saying where the file comes
from (URL pattern or the producing repo), when it was captured, whether it is
**real** or **synthetic**, whether it was redacted or trimmed, and who reads it.

| Directory | Real / synthetic | Read by (here) | Copied to |
|---|---|---|---|
| `su/retrieve/` | synthetic | `tests/test_retrieve_parsers.py` | connector `test/fixtures/retrieve/` |
| `su/democracy/` | real, trimmed | `tests/test_democracy.py` | — |
| `su/su-room-sheet/` | real, trimmed | `tests/test_su_room_sheet.py` | — |
| `su/society/` | real | — | pipeline `pipeline/tests/fixtures/su_society/` |
| `native/connector-form-payload/` | synthetic | — | mirrors connector `test/fixtures/fill/payment-request-payload.json` (not drift-tested yet; see its README) |
| `native/governing-document-text/` | real excerpts | — | toolbox `src/lib/__fixtures__/governing-documents/` |

## Real vs synthetic

- **Real**: saved from the live page, then trimmed and/or redacted. Say which in the
  kind's README, and name what was cut. A real page is evidence of what the site
  does; a parser change that breaks one is a parser bug until proven otherwise.
- **Synthetic**: hand-written to encode an assumption nobody has checked against the
  site yet. Label it as such in the kind's README *and* keep the matching parser's
  `UNVERIFIED` block honest. Replace a synthetic page with a real capture as soon as
  one exists; never "fix" a synthetic page to make a failing parser pass without
  saying so.

## Capturing a page

- **Authenticated SU pages (retrievers)**: the Connector, unpacked/development
  builds only (store builds have neither step). Load
  `../adams-campus-toolbox-connector` unpacked, sign in to studentsunionucl.org as a
  committee member, click the society's member count in the popup and run the
  retriever.
  - **Ticket sales** has no page the slug can predict, so link it first: open the
    society's ticket-sales page on the SU site, pick **Ticket sales**, press **Use
    the open SU tab** (or paste the address) and **Link and read**. The link is a
    studentsunionucl.org path kept in that browser only; **Unlink** goes back to
    the guess, Disconnect clears it.
  - Whether it parses or is refused, **Save a redacted capture** downloads
    `capture-<retriever>-<slug>-redacted.html` (first page only for paged lists),
    masked in the browser before the file is written. Text is shape-masked (letters
    `x`/`X`, digits `1`, punctuation kept: "£12.50" → "£11.11") except headings,
    table headers, captions, labels, buttons, `<dt>`, the title and the Drupal
    pager/tabs/breadcrumb — never inside a table body or Views row — and cells that
    are only a status word (`Paid`, `Refunded`, `Checked in`…). Emails become
    `buyer@example.invalid` everywhere. `class`/`id`/`name`/`type` and other
    structural attributes stay (digits turned to `1`); every other attribute value
    is masked; links keep word segments but lose ids, query values and fragments;
    inline script bodies, comments, `on…` handlers and `data:` URLs go.
  - The page then lists the **Text left readable**. Read it — a name in a heading
    is the one case the rules can't catch — and still check the file by eye
    against the redaction rule below before it goes anywhere near a commit.
- **Public SU pages** (democracy, society pages, What's On): fetch them the way the
  consumer does — `curl -L <url>` or the scraper's own session — so the markup is the
  markup the code will see. Pages behind the login can also be saved from a
  `suu login` session (`common.fetch_page_html` returns `page.content()`).
- **Google Sheets** (SU room sheet): the `htmlview` endpoints `suu.rooms.su_room_sheet`
  reads, saved with scripts stripped.
- **Native shapes**: generate them from the producing repo (its types or a test),
  not by hand, so they describe what the code really emits.

Then: redact (below), trim what the parser doesn't need if the file is large (keep
the structure it walks), save it under the right kind, update that kind's README
(captured date, real/synthetic, what was cut), and sync the consumers.

## Redaction rule

**Redact before it goes anywhere near a commit.** Replace every real name, email,
phone number, amount, booking and ticket reference with made-up values of the same
shape, and delete the `SSESS…`/`form_token`/`form_build_id` values and any user id
in links. Keep the markup, classes and attributes exactly as they were — they are
what the fixture is for. A Connector redacted capture does most of this, not all:
mask anything personal it left by hand, same shape.

Public pages the SU itself publishes (officer names in policy registers, society
pages, governing documents) don't need redacting; anything only visible when signed
in does.

## How consumers stay in step

Each consumer has a sync script that copies what it needs from here into its own
fixtures, and a drift test that compares byte for byte. The drift test **skips**
when `../suu` isn't checked out next to the repo (CI), so it only bites on a dev
machine — which is the only place the copies change.

| Consumer | Sync | Drift test |
|---|---|---|
| connector | `node scripts/sync-samples.mjs` | `test/samples-drift.test.mjs` |
| pipeline | `python -m pipeline.tools.sync_samples` | `pipeline/tests/test_samples_drift.py` |
| toolbox | `node scripts/sync-samples.mjs` | `src/lib/samplesDrift.test.ts` |

To change a sample: edit it **here**, run the consumer's sync, run its tests. Never
edit a consumer's copy directly — the drift test will fail until the change is made
here too.
