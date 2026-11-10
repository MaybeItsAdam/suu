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
| `su_activity_registration/` | **real, redacted** | 2026-10-24 | ARF (`/webform/activity-registration-form`): `fieldmap-default.json` and `su_activity_registration.html`. Single-page webform (`webform-submission-activity-registration-form-add-form`); `proposed_date_s_and_time_s_` repeating table, `expenditure_details_3` and `incomings_details` 3-column repeating tables (`type`, `details`, `amount`). |
| `su_ticket_request/` | **real, redacted** | 2026-10-24 | TRF (`/forms/ticket-request-form`): `fieldmap-default.json` and `su_ticket_request.html`. Single-page webform (`webform-submission-webform-126302-node-126302-add-form`); event vs product radios, 10-digit account code, `ticket_types` repeating table, What's On URL. |
| `su_event_listing/` | **real, redacted** | 2026-10-24 | What's On "Create event" (`/product/add/event`): `fieldmap-default.json` and `su_event_listing.html`. Drupal Commerce product form (`commerce-product-event-add-form`); `field_event_owner_group` is a `<select>` (society options redacted to `Example Society` / `Example Club`), `field_access_wheelchair` is Yes/No radios, `field_access_family` is a `<select>`, banner/card image uploads, `variations` inline entity form. |
| `su_external_speaker_request/` | **real, redacted** | 2026-10-27 | External Speaker Request Form (`/forms/external-speaker-request-form`): `fieldmap-default.json` and `su_external_speaker_request.html`. Single-page webform (`webform-submission-webform-130362-node-130362-add-form`); requestor type radios, Yes/No radios each with an "If yes" detail field, open-to radios, date/time inputs. Staff mailbox in the help text replaced with `redacted@example.invalid`; user id, tokens and submission link ids zeroed. |
| `su_sales_invoice_request/` | **real, redacted** | 2026-10-27 | Sales Invoice Request Form (`/forms/sales-invoice-request-form`): `fieldmap-default.json` and `su_sales_invoice_request.html`. Webform `webform-submission-webform-138155-node-138155-add-form`; type of income and country are Chosen selects (`chosen: true` added to the field map by hand from the page's `data-once`; the country list stops at 80 options in the capture), company address composite, `invoice_details` repeating table, one contract upload. |
| `su_additional_risk_assessment/` | **real, redacted** | 2026-10-27 | Additional Risk Assessment Form (`/forms/additional-risk-assessment-form`; opened via `/forms/additional-risk-assessment-submission`, which redirects): `fieldmap-default.json` and `su_additional_risk_assessment.html`. Webform `webform-submission-webform-136350-node-136350-add-form`; `proposed_date_s_and_time_s_`, `activity_log_` and `participant_details` repeating tables, three checkbox groups, overnight-stay fields conditional on one tick box, one spreadsheet upload (xls/xlsx/xml, 2 MB). The existing `risk_assessment` scaffold is a different, older guess at this form. |

Redaction: the probe reads no values, and keeps labels, help text, option and button
words, with emails replaced. Read the "none of it is a person" list on the capture tab
and the files themselves before committing (a society list in a select, the
signed-in name in a label); the redaction rule in `../README.md` applies.
