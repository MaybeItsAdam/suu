# su/forms — SU form captures (field maps and redacted pages)

One folder per form definition, named by its `form_id`
(`src/suu/forms/definitions/<form_id>.json`):

```
su/forms/<form_id>/fieldmap-<page>[-<state>].json   the Connector's field map
su/forms/<form_id>/<form_id>[-<state>].html         the Connector's redacted page (downloads as capture-form-<page>-redacted.html)
```

- **Captured with**: the Connector's dev-build **Capture this SU page**
  (`../adams-campus-toolbox-connector`, `lib/form-probe.js`), signed in as a president or
  treasurer, nothing typed, **never submitted**. Steps: `docs/capturing-forms.md`.
- **Field map shape**: `{capturedAt, url, title, forms: [{id, selector, action, method, fields: [{tag,
  type, name, id, selector (data-drupal-selector), label, required, hidden,
  description?, multiple?, autocomplete?, chosen?, options?: [{value, text}], text?}]}],
  controlsOutsideForms}`. No input value is ever in it.
- **Read by**: `suu forms draft <fieldmap> --against <form_id>` and
  `tests/test_forms_fieldmap.py` (`suu.forms.fieldmap`).
- **Copied to**: the Toolbox's `src/lib/suuForms/fixtures/<form_id>.html` takes the
  redacted page, which its contract test loads (by hand for now; no sync script).

| Folder | Real / synthetic | Captured | Notes |
|---|---|---|---|
| `payment_request/fieldmap-synthetic.json` | **synthetic** | — | Hand-written in the probe's shape from the released payment request definition's selectors, plus a search form, a radio pair, a hidden conditional field, a second table row and the final Submit, to test the loader. Not evidence of the live page. |
| `su_activity_registration/` | — | not yet | ARF. |
| `su_ticket_request/` | — | not yet | TRF. |
| `su_event_listing/` | — | not yet | What's On "Create event". |

Redaction: the probe reads no values, and keeps labels, help text, option and button
words, with emails replaced. Read the "none of it is a person" list on the capture tab
and the files themselves before committing (a society list in a select, the
signed-in name in a label); the redaction rule in `../README.md` applies.
