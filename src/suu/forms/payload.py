"""
Normalise a receipt-gatherer job payload_json into form field data
that the FormExecutor / payment_request.json definition understands.

Kept in step with its TypeScript port, ``buildPaymentRequestData`` in the
Toolbox (``src/lib/suuForms/payload.ts``), which feeds the Connector browser
extension — the same mapping, run in the treasurer's own browser. A fix to
one belongs in the other.

The event builders at the bottom (``build_activity_registration_data``,
``build_ticket_request_data``, ``build_event_listing_data``) map a Toolbox
event onto the scaffold definitions for the ARF, the TRF and the What's On
listing. They have no TypeScript port yet; the definitions' selectors are
unconfirmed, so their keys are the contract, not the page.
"""

from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def first_text(*values: object) -> str:
    """Return the first non-empty string among the given values."""
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def normalize_banking_number(value: str, length: int) -> str:
    """Strip non-digits and zero-pad to *length*."""
    digits = re.sub(r"\D", "", value)
    return digits.zfill(length) if digits else ""


def format_cost(value: object) -> str:
    """Pounds as the SU's cost box wants them, ``12.50``; ``""`` if unreadable."""
    if value is None or value == "" or isinstance(value, bool):
        return ""
    try:
        amount = float(str(value).replace("£", "").replace(",", "").strip())
    except ValueError:
        return str(value)
    return f"{amount:.2f}"


@lru_cache(maxsize=1)
def _expenditure_options() -> tuple[str, ...]:
    from suu.forms.loader import load_form_definition

    receipts = next(
        (f for f in load_form_definition("payment_request").fields if f.name == "receipts"),
        None,
    )
    search = next(
        (f for f in (receipts.fields or []) if f.name == "expenditure_type_search"),
        None,
    ) if receipts else None
    return tuple(o.upper() for o in (search.options or [])) if search else ()


def su_expenditure_type(category: str) -> str:
    """
    The SU's expenditure-type option for a receipt category.

    The two lists are the same items but not the same strings — the Toolbox
    says "Coach/Instructor", the SU "COACH/INSTRUCTORS" — and the Chosen search
    box wants a string that picks exactly one. Exact match first, then either
    being a prefix of the other, then the category as given (the human sees
    the dropdown and can fix it).
    """
    wanted = (category or "").strip().upper() or "MISCELLANEOUS EXPENDITURE"
    options = _expenditure_options()
    if wanted in options:
        return wanted
    for option in options:
        if option.startswith(wanted) or wanted.startswith(option):
            return option
    return wanted


# ---------------------------------------------------------------------------
# Receipt URL resolution
# ---------------------------------------------------------------------------

def resolve_receipt_urls(payload: dict) -> list[str]:
    """
    Extract receipt image URLs from a job payload.

    Handles the three formats used by receipt-gatherer:
      - ReceiptLinks / receiptLinks : comma-separated string
      - imageUrl / image_url        : single URL string
      - imageUrls                   : JSON array of strings
    """
    urls: list[str] = []

    receipt_links = payload.get("ReceiptLinks") or payload.get("receiptLinks") or ""
    if isinstance(receipt_links, str):
        urls.extend(u.strip() for u in receipt_links.split(",") if u.strip())

    for key in ("imageUrl", "image_url"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            urls.append(val.strip())
            break

    image_urls = payload.get("imageUrls") or []
    if isinstance(image_urls, list):
        urls.extend(u for u in image_urls if isinstance(u, str) and u.strip())

    # Deduplicate while preserving order.
    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u))]  # type: ignore[func-returns-value]


async def download_receipt(url: str, dest_dir: Path, stem: str) -> Path | None:
    """
    Download a receipt image to *dest_dir/<stem><ext>*.
    Returns the local path, or None if the download fails.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
    dest = dest_dir / f"{stem}{ext}"
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            dest.write_bytes(response.content)
            return dest
    except Exception as exc:
        print(f"  ⚠  Failed to download receipt: {exc}")
        return None


# ---------------------------------------------------------------------------
# Payload → form data
# ---------------------------------------------------------------------------

def normalize_payload(payload: dict, downloaded_file: Path | None = None) -> dict:
    """
    Map a receipt-gatherer job payload_json to a form data dict whose keys
    match the field *name* attributes in payment_request.json.

    The returned dict can be passed directly to FormExecutor.execute().
    """
    # --- grant code ---
    grant_raw = (
        payload.get("grant")
        or payload.get("Grant")
        or payload.get("grantCode")
        or "N"
    )
    if isinstance(grant_raw, bool):
        grant = "G" if grant_raw else "N"
    else:
        grant = "G" if str(grant_raw).strip().upper().startswith("G") else "N"

    # --- expenditure type ---
    expenditure_type = su_expenditure_type(first_text(
        payload.get("type"),
        payload.get("category"),
        payload.get("production"),
        payload.get("R1Type"),
    ))

    # --- amount ---
    amount_raw = (
        payload.get("amount")
        or payload.get("R1Expenditure")
        or payload.get("TotalExpensein")
        or ""
    )
    cost = format_cost(amount_raw)

    # The receipts list is a single-item list matching the form's "list" field.
    # Child field names mirror the payment_request.json sub-field names exactly.
    receipt_item = {
        # type=click  — clicks to open the Chosen dropdown; value ignored by executor
        "expenditure_type": expenditure_type,
        # type=type_text — types the search string into the Chosen search box
        "expenditure_type_search": expenditure_type,
        # type=press_enter — presses Enter to confirm the selection; value ignored
        "expenditure_type_select": "",
        "grant": grant,
        "cost": cost,
        # type=file — local filesystem path; empty string means skip upload
        "file": str(downloaded_file) if downloaded_file else "",
    }

    return {
        "club_society": first_text(payload.get("societyId"), payload.get("Show")),
        "description": first_text(
            payload.get("description"),
            payload.get("notes"),
            payload.get("R1Description"),
        ),
        # The payee is whoever holds the account being paid; the submitter is
        # only a fallback for a receipt with no bank details on it.
        "payee_name": first_text(
            payload.get("AccountName"),
            payload.get("accountName"),
            payload.get("submittedBy"),
            payload.get("Submitter"),
        ),
        "phone_number": first_text(
            payload.get("Phonenumber"),
            payload.get("phoneNumber"),
            payload.get("PhoneNumber"),
        ),
        "email": first_text(
            payload.get("UCLEmail"),
            payload.get("uclEmail"),
            payload.get("submittedByEmail"),
        ),
        "account_number": normalize_banking_number(
            first_text(
                payload.get("AccountNumber"),
                payload.get("accountNumber"),
            ),
            8,
        ),
        "sort_code": normalize_banking_number(
            first_text(
                payload.get("SortCode"),
                payload.get("sortCode"),
            ),
            6,
        ),
        "receipts": [receipt_item],
    }


# ---------------------------------------------------------------------------
# Toolbox event → ARF / TRF / What's On listing (scaffold definitions)
# ---------------------------------------------------------------------------
#
# The event is a Toolbox ``AdhocEvent`` as JSON (camelCase): ``title``,
# ``society``, ``description``, ``startTime``/``endTime`` (ISO strings in UTC,
# or datetimes), ``timeKnown``, ``location``, ``imageUrl``. What an AdhocEvent
# doesn't hold yet, the caller adds alongside: ``ticketTiers`` (``name``,
# ``price``, ``quantity``, optional ``projectedSales`` and ``audience``),
# ``expectedAttendance``, ``contactEmail``, ``online``, ``tags``, and the yes/no
# facts the forms ask (``charity``, ``highRisk``, ``externalCollaboration``,
# ``externalSpeaker``, ``overnightOrAbroad``, ``cashDoorSales``,
# ``whoCanAttend``). Missing means "don't fill", never a guess.

LONDON = ZoneInfo("Europe/London")

#: The SU asks for a 15% contingency line in every ARF budget.
ARF_CONTINGENCY = 0.15
#: "Never budget for more than 50% ticket sales."
ARF_MAX_SALES_SHARE = 0.5
#: Cash door sales are allowed only for tickets at this price or less.
CASH_DOOR_SALES_MAX_PRICE = 10.0
#: The balancing income line: whatever tickets and other income don't cover.
ARF_ACCOUNT_LINE = "Club/society non-grant account contribution"


def _amount(value: object) -> float | None:
    """Pounds as a float, or None when unreadable or absent."""
    text = format_cost(value)
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _yes_no(value: object) -> str | None:
    """``"Yes"``/``"No"`` for a known boolean, None when not known."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return "Yes" if value.strip().lower() in ("yes", "true", "1", "y") else "No"
    return "Yes" if value else "No"


def london_date_time(value: object, time_known: bool = True) -> tuple[str, str]:
    """
    ``("YYYY-MM-DD", "HH:MM")`` in Europe/London for a datetime or ISO string.

    A naive value is taken as UTC, which is how the Toolbox stores times. When
    the time isn't known (``timeKnown: false`` — the What's On scraper's
    midnight placeholder), the time comes back empty rather than ``00:00``.
    """
    if value is None or value == "":
        return "", ""
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return "", ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(LONDON)
    return local.strftime("%Y-%m-%d"), (local.strftime("%H:%M") if time_known else "")


def normalize_ticket_tiers(tiers: object) -> list[dict]:
    """
    Ticket tiers as ``{name, price, quantity, projected, audience}``.

    ``price`` is pounds (0.0 for free), ``quantity`` an int or None,
    ``projected`` the sales to budget for: the caller's ``projectedSales``
    capped at half the quantity, else half the quantity rounded down. A tier
    with no name is dropped.
    """
    out: list[dict] = []
    for tier in tiers if isinstance(tiers, list) else []:
        if not isinstance(tier, dict):
            continue
        name = first_text(tier.get("name"), tier.get("title"))
        if not name:
            continue
        price = _amount(tier.get("price")) or 0.0
        quantity_raw = tier.get("quantity", tier.get("capacity"))
        try:
            quantity = int(quantity_raw) if quantity_raw not in (None, "") else None
        except (TypeError, ValueError):
            quantity = None
        cap = math.floor(quantity * ARF_MAX_SALES_SHARE) if quantity is not None else None
        projected_raw = tier.get("projectedSales")
        try:
            projected = int(projected_raw) if projected_raw not in (None, "") else cap
        except (TypeError, ValueError):
            projected = cap
        if projected is not None and cap is not None:
            projected = min(projected, cap)
        on_sale_date, on_sale_time = london_date_time(tier.get("onSaleAt"))
        off_sale_date, off_sale_time = london_date_time(tier.get("offSaleAt"))
        out.append({
            "name": name,
            "price": price,
            "quantity": quantity,
            "projected": projected or 0,
            "audience": first_text(tier.get("audience")),
            "on_sale_date": first_text(tier.get("onSaleDate"), on_sale_date),
            "on_sale_time": first_text(tier.get("onSaleTime"), on_sale_time),
            "off_sale_date": first_text(tier.get("offSaleDate"), off_sale_date),
            "off_sale_time": first_text(tier.get("offSaleTime"), off_sale_time),
        })
    return out


def _cost_line(cost: dict) -> dict | None:
    """One ARF expenditure line from a receipt or a planned cost."""
    amount = _amount(cost.get("amount"))
    if amount is None:
        return None
    category = first_text(cost.get("category"), cost.get("type"))
    what = first_text(cost.get("description"), cost.get("notes"), cost.get("vendor"))
    label = su_expenditure_type(category).capitalize() if category else ""
    exp_type = label or what or "Expenditure"
    description = " - ".join(p for p in (label, what) if p) or "Expenditure"
    return {"type": exp_type, "description": description, "amount": amount}


def _money(value: float) -> str:
    return f"{value:.2f}"


def build_activity_registration_data(event: dict, costs: list | tuple = ()) -> dict:
    """
    Form data for ``su_activity_registration.json`` from an event and its costs.

    ``costs`` are Toolbox receipts (``category``, ``vendor``, ``notes``,
    ``amount``) or planned costs (``description``, ``amount``). Expenditure is
    one line per cost plus the SU's 15% contingency; income is one line per
    paid ticket tier at its projected sales ("Early Bird - £10.00 x 15 =
    £150.00"), then the society account covering whatever is left, so the
    budget breaks even as the SU requires. Yes/no radios are ticked only when
    the answer is known (from the budget or from ``event``).
    """
    expenditure = [line for line in (_cost_line(c) for c in costs if isinstance(c, dict)) if line]
    spend = round(sum(line["amount"] for line in expenditure), 2)
    if spend > 0:
        expenditure.append({
            "type": "Contingency",
            "description": "Contingency (15%)",
            "amount": round(spend * ARF_CONTINGENCY, 2),
        })
    spend_total = round(sum(line["amount"] for line in expenditure), 2)

    income = []
    for tier in normalize_ticket_tiers(event.get("ticketTiers")):
        if tier["price"] <= 0 or tier["projected"] <= 0:
            continue
        subtotal = round(tier["price"] * tier["projected"], 2)
        income.append({
            "type": "Ticket sales",
            "description": f"{tier['name']} - £{_money(tier['price'])} x {tier['projected']} = £{_money(subtotal)}",
            "amount": subtotal,
        })
    shortfall = round(spend_total - sum(line["amount"] for line in income), 2)
    if shortfall > 0:
        income.append({
            "type": "Non-Grant Funds",
            "description": ARF_ACCOUNT_LINE,
            "amount": shortfall,
        })
    income_total = round(sum(line["amount"] for line in income), 2)

    time_known = event.get("timeKnown") is not False
    start_date, start_time = london_date_time(event.get("startTime"), time_known)
    end_date, end_time = london_date_time(event.get("endTime"), time_known)
    location = first_text(event.get("location"))
    attendance = event.get("expectedAttendance")
    member_attendance = event.get("memberAttendance")

    proposed_dates = [
        {
            "date": start_date,
            "start_time": start_time,
            "end_time": end_time,
            "location": location,
        }
    ]
    if end_date and end_date != start_date:
        proposed_dates.append({
            "date": end_date,
            "start_time": start_time,
            "end_time": end_time,
            "location": location,
        })

    data: dict = {
        "club_society": first_text(event.get("society"), event.get("organiserName")),
        "lead_name": first_text(event.get("leadName"), event.get("submittedByName"), event.get("submittedBy")),
        "lead_email": first_text(event.get("leadEmail"), event.get("contactEmail"), event.get("submittedByEmail")),
        "lead_phone": first_text(event.get("leadPhone"), event.get("contactPhone"), event.get("phoneNumber")),
        "activity_name": first_text(event.get("title")),
        "activity_description": first_text(event.get("description")),
        "proposed_dates": proposed_dates,
        "member_attendance": str(int(member_attendance)) if isinstance(member_attendance, (int, float)) and not isinstance(member_attendance, bool) else "",
        "expected_attendance": str(int(attendance)) if isinstance(attendance, (int, float)) and not isinstance(attendance, bool) else "",
        "costs_money_yes": spend_total > 0,
        "costs_money_no": spend_total == 0,
        "expenditure": [
            {"type": l["type"], "description": l["description"], "amount": _money(l["amount"])}
            for l in expenditure
        ],
        "total_expenditure": _money(spend_total) if spend_total > 0 else "",
        "generates_income_yes": income_total > 0,
        "generates_income_no": income_total == 0,
        "income": [
            {"type": l["type"], "description": l["description"], "amount": _money(l["amount"])}
            for l in income
        ],
        "total_income": _money(income_total) if income_total > 0 else "",
    }
    for yes_key, no_key, source in (
        ("on_campus_yes", "on_campus_no", "onCampus"),
        ("raising_for_charity_yes", "raising_for_charity_no", "charity"),
        ("previous_event_yes", "previous_event_no", "previousEvent"),
        ("risk_assessment_additional", "risk_assessment_core", "highRisk"),
        ("under_18s_yes", "under_18s_no", "under18s"),
        ("external_speaker_yes", "external_speaker_no", "externalSpeaker"),
    ):
        answer = _yes_no(event.get(source))
        if answer == "Yes":
            data[yes_key] = True
        elif answer == "No":
            data[no_key] = True
    if first_text(event.get("charityName")):
        data["charity_name"] = first_text(event.get("charityName"))
    if first_text(event.get("charityRegistrationNumber")):
        data["charity_registration_number"] = first_text(event.get("charityRegistrationNumber"))
    if first_text(event.get("fundraisingDetail")):
        data["fundraising_detail"] = first_text(event.get("fundraisingDetail"))
    return data


def build_ticket_request_data(
    event: dict,
    whats_on_url: str | None = None,
    activity_registration_ref: str | None = None,
) -> dict:
    """
    Form data for ``su_ticket_request.json``: the paid tiers of an event.

    Free tiers are left out (the society makes those on the SU site itself).
    The What's On URL is required by the SU and comes from the event's linked
    listing (which already carries the event's title, date, time and venue);
    an ARF reference is sent when given, and selects ``expenditure_over_200_yes``.
    """
    paid = [t for t in normalize_ticket_tiers(event.get("ticketTiers")) if t["price"] > 0]
    quantities = [t["quantity"] for t in paid if t["quantity"] is not None]
    total_tickets = str(sum(quantities)) if quantities else ""

    data: dict = {
        "club_society": first_text(event.get("society"), event.get("organiserName")),
        "lead_name": first_text(event.get("leadName"), event.get("treasurerName"), event.get("submittedByName"), event.get("submittedBy")),
        "lead_email": first_text(event.get("leadEmail"), event.get("contactEmail"), event.get("submittedByEmail")),
        "lead_phone": first_text(event.get("leadPhone"), event.get("contactPhone"), event.get("phoneNumber")),
        "selling_for_event": True,
        "account_code": first_text(event.get("accountCode"), event.get("accountNumber")),
        "whats_on_url": first_text(whats_on_url, event.get("whatsOnUrl")),
        "ticket_tiers": [
            {
                "name": t["name"],
                "audience": t["audience"],
                "quantity": "" if t["quantity"] is None else str(t["quantity"]),
                "price": _money(t["price"]),
                "on_sale_date": t["on_sale_date"],
                "on_sale_time": t["on_sale_time"],
                "off_sale_date": t["off_sale_date"],
                "off_sale_time": t["off_sale_time"],
            }
            for t in paid
        ],
        "total_tickets": total_tickets,
        "additional_information": first_text(event.get("additionalInformation"), event.get("notes")),
    }
    reference = first_text(activity_registration_ref, event.get("activityRegistrationRef"))
    if reference:
        data["expenditure_over_200_yes"] = True
        data["activity_registration_form"] = reference
    for yes_key, no_key, source in (
        ("raising_for_charity_yes", "raising_for_charity_no", "charity"),
        ("linked_to_external_speaker_yes", "linked_to_external_speaker_no", "externalSpeaker"),
        ("involves_coach_yes", "involves_coach_no", "involvesCoach"),
    ):
        answer = _yes_no(event.get(source))
        if answer == "Yes":
            data[yes_key] = True
        elif answer == "No":
            data[no_key] = True
    if first_text(event.get("charityName")):
        data["charity_name"] = first_text(event.get("charityName"))
    return data


def build_event_listing_data(event: dict, image_file: Path | None = None) -> dict:
    """
    Form data for ``su_event_listing.json`` (What's On "Create event", ``/product/add/event``).

    Only free tiers go on the listing; paid tickets are the TRF's. The image
    is a downloaded local file, like a payment request's receipt — the
    payload never carries a URL for a file. An online event gets no venue.
    """
    time_known = event.get("timeKnown") is not False
    start_date, start_time = london_date_time(event.get("startTime"), time_known)
    end_date, end_time = london_date_time(event.get("endTime"), time_known)
    online = bool(event.get("online"))
    tags = event.get("tags")
    all_tiers = normalize_ticket_tiers(event.get("ticketTiers"))
    free = [t for t in all_tiers if t["price"] <= 0]
    has_paid = any(t["price"] > 0 for t in all_tiers)
    if has_paid:
        ticketing_type = "Club & Society event as part of a Ticket Request Form submission"
    elif free:
        ticketing_type = "Free tickets bookable on this website"
    else:
        ticketing_type = "No tickets"
    image_path = str(image_file) if image_file else ""
    data: dict = {
        "title": first_text(event.get("title")),
        "owner_group": first_text(event.get("society"), event.get("organiserName")),
        "event_category": first_text(event.get("eventCategory"), "Clubs & Societies"),
        "start_date": start_date,
        "start_time": start_time,
        "end_date": end_date or start_date,
        "end_time": end_time,
        "online": online,
        "venue": "" if online else first_text(event.get("location")),
        "body": first_text(event.get("description")),
        "banner_image": image_path,
        "card_image": image_path,
        "contact_email": first_text(event.get("contactEmail")),
        "contact_phone": first_text(event.get("contactPhone"), event.get("leadPhone")),
        "tags": ", ".join(t.strip() for t in tags if isinstance(t, str) and t.strip()) if isinstance(tags, list) else "",
        "ticketing_type": ticketing_type,
        "ticket_tiers": [
            {"name": t["name"], "price": _money(0), "quantity": "" if t["quantity"] is None else str(t["quantity"])}
            for t in free
        ],
    }
    if event.get("postgraduate") is not None:
        data["postgraduate"] = bool(event.get("postgraduate"))
    if first_text(event.get("familyFriendly")):
        data["family_friendly"] = first_text(event.get("familyFriendly"))
    wheelchair = _yes_no(event.get("wheelchairAccess"))
    if wheelchair == "Yes":
        data["wheelchair_access_yes"] = True
    elif wheelchair == "No":
        data["wheelchair_access_no"] = True
    return data
