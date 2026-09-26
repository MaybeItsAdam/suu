# su/su-room-sheet — the SU room-booking Google Sheet (real, trimmed)

- **Pages** (Google Sheets, published; no login):
  - `tabs.html` — `https://docs.google.com/spreadsheets/d/<id>/htmlview` (tab list,
    `items.push({name: …, gid: …})`).
  - `key.html`, `week-27.4.26.html` —
    `https://docs.google.com/spreadsheets/d/<id>/htmlview/sheet?headers=false&gid=<gid>`
    (one tab each).
- **Source**: the live Term 3 2025/26 sheet `10yIxgUm-WoIiSGk4w4OXicIMH46CUy2C2k-hm31lS7E`.
- **Real or synthetic**: real. Scripts stripped; the week tab keeps its CSS and header
  rows but only three rooms of Monday and Tuesday (day/date rowspans cut from 32 to 3 to
  match).
- **Captured**: 2026-09-25.
- **Redacted**: no personal data beyond society names on public bookings.
- **Read by**: `tests/test_su_room_sheet.py` (`suu.rooms.su_room_sheet`).
