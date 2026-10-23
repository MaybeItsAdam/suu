# native/toolbox-event — a Toolbox event, as the SU event-form builders read it

- **Shape**: a Toolbox `AdhocEvent` as JSON (camelCase, times in UTC) under `event`,
  plus the facts an AdhocEvent doesn't hold yet but the SU forms ask for
  (`ticketTiers`, `expectedAttendance`, `contactEmail`, `online`, `tags`, `charity`,
  `highRisk`, `externalSpeaker`, `overnightOrAbroad`, `cashDoorSales`, `whoCanAttend`),
  and `costs`: Toolbox receipts (`category`, `vendor`, `notes`, `amount`) and planned
  costs (`description`, `amount`) for the Activity Registration Form's budget.
- **Read by**: `tests/test_forms_event_payloads.py`, through
  `build_activity_registration_data`, `build_ticket_request_data` and
  `build_event_listing_data` in `src/suu/forms/payload.py`.
- **Produced by**: nothing yet. The Toolbox has no event-form payload route; when it
  gets one (Phase 5 of the Connector-in-events plan), generate this from it and keep the
  keys.
- **Real or synthetic**: synthetic. The Toolbox's own time zone rule applies — the
  times are UTC and the builders turn them into Europe/London.
- **Files**: `winter-ball.json` — paid and free tiers, a receipt with no amount (skipped),
  and a cost total over £350.
