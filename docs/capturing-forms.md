# Capturing an SU form

The SU's forms only render for a signed-in president or treasurer, so their
fields can't be fetched by a script. A capture is a **field map** (every
control's selector, label, options and whether it's required or hidden; never
a value) plus a **redacted copy** of the page, saved in
`samples/su/forms/<form_id>/`. From those, `suu forms draft` writes the
definition's fields mechanically.

| Form | `form_id` | Open this, signed in |
|---|---|---|
| Activity Registration Form (ARF) | `su_activity_registration` | https://studentsunionucl.org/webform/activity-registration-form |
| Ticket Request Form (TRF) | `su_ticket_request` | https://studentsunionucl.org/forms/ticket-request-form |
| What's On "Create event" | `su_event_listing` | https://studentsunionucl.org/whats-on → **Create event** (top left). Note the address it opens: the definition needs it. |

## Never

- **Never press Submit, Save, Publish, Preview or Save draft.** The capture
  reads the page; nothing needs sending. Close the tab when done.
- Don't type real details. Fill nothing unless a section only appears after an
  answer; then pick the answer (a select, a radio, a tick box) and type nothing.
- Don't save the page with the browser's own "Save as" or DevTools: that copy
  has your name, session tokens and form tokens in it. Only the Connector's
  two downloads go in the repo.

## Steps

1. Use a **development build** of the Connector 1.3
   (`../adams-campus-toolbox-connector`, branch `feat/connector-1.3` or later).
   Store builds have no capture button.
   - Chrome: `chrome://extensions` → Developer mode → **Load unpacked** → the
     connector folder.
   - Safari: the dev build in /Applications, or
     `cd ../adams-campus-toolbox-connector && scripts/release-safari.sh --install`.
2. Sign in to https://studentsunionucl.org as a president or treasurer.
3. Open the form's address from the table above in a tab.
4. With that tab in front, open the Connector popup → **Capture this SU page**
   (footer). A new tab opens.
5. On that tab press **Download field map (JSON)** and **Download redacted
   page (HTML)**. Read both "check none of it is a person" lists.
6. Capture each state that shows more fields, once per state (repeat 4–5):
   - **ARF**: as it opens; then with each criterion ticked and each yes/no set
     to Yes (overnight or abroad, external speaker, charity); if the budget
     has an **Add** button, press it once so a second row exists (it's not
     Submit). If the form has pages (a progress bar or **Next**), capture each
     page; reaching the next page may need the required boxes filled — type
     `TEST` and pick anything, then **close the tab without submitting**.
   - **TRF**: as event tickets; then as a product (kit or merchandise) if it
     asks; then with any cash-sales / ARF / speaker / charity question set to
     Yes; press a ticket table's **Add** once if it has one.
   - **Create event**: as it opens; then with **Online** ticked; then with
     **Access to event and sales** (and any ticket or variation section)
     opened. Don't add a venue or ticket for real.
7. Move the downloads into this repo, one folder per form, naming each file
   for its state:

   ```bash
   cd "$HOME/Projects/Code For SUU/suu"
   F=su_ticket_request   # or su_activity_registration, su_event_listing
   mkdir -p samples/su/forms/$F
   mv ~/Downloads/fieldmap-*.json samples/su/forms/$F/
   mv ~/Downloads/capture-form-*-redacted.html samples/su/forms/$F/
   ls samples/su/forms/$F
   ```

8. Rename them by state (`fieldmap-default.json`, `fieldmap-product.json`,
   `<form_id>-default.html`…), open each and check it by eye for a name, an
   email or your societies' list; mask anything personal by hand, same shape
   (see `samples/README.md`, "Redaction rule").
9. Check the draft and the current definition against it:

   ```bash
   uv run suu forms draft samples/su/forms/$F/fieldmap-default.json --against $F
   ```

   `fields` is the definition drafted from the capture; `match.missing` is
   what the current definition guessed wrong; `match.reaches_submit` must be
   `[]`.
10. Hand it over (or do it): copy the drafted selectors into
    `src/suu/forms/definitions/$F.json`, keep the field names the payload
    builders use, set `"confirmed": true` on each field the capture shows,
    update the `_todo`, note the capture in `samples/su/forms/README.md`, then
    `uv run pytest`. In the Toolbox: `node scripts/sync-suu-forms.mjs`, copy
    the redacted page to `src/lib/suuForms/fixtures/$F.html`, run
    `npx vitest run src/lib/suuForms`; copy the JSON to the Connector's
    `forms/`.
