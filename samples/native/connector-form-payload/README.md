# native/connector-form-payload — what the Toolbox hands the Connector to fill a form

- **Shape**: the `data` object returned by the Toolbox's
  `GET /api/connector/receipts/:id/form-payload`
  (`adams-campus-toolbox/src/app/api/connector/receipts/[id]/form-payload/route.ts`,
  built by `buildPaymentRequestData` in `src/lib/suuForms/payload.ts` — mirrored by
  `src/suu/forms/payload.py` here). Keys are the field `name`s of the SU form
  definition (`src/suu/forms/definitions/payment_request.json`); the Connector looks
  each value up by name.
- **`receipts[].file`** is `{ filename, mimeType }` only. There is no URL: the
  extension always fetches the image from the Toolbox
  (`/api/connector/receipts/:id/image?jobId=`), so no third-party origin ever reaches
  it.
- **Produced by**: `adams-campus-toolbox`. **Consumed by**:
  `adams-campus-toolbox-connector` (`background.js` → form executor).
- **Real or synthetic**: synthetic (Ada Lovelace, an Ofcom drama phone number, the
  documented test sort code).
- **Files**: `payment-request.json` — the same content as the Connector's
  `test/fixtures/fill/payment-request-payload.json`, which its offline end-to-end fill
  test types into a synthetic SU page. The Toolbox's `src/lib/suuForms/contract.test.ts`
  checks that fixture's key shape against `buildPaymentRequestData`, so the shape is
  pinned there; this copy is the reference for anyone else reading the payload. It is
  not yet synced or drift-tested — if it grows consumers, give the Connector a sync and
  drift check like `su/retrieve/`.
