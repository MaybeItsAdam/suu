"""
Normalise a receipt-gatherer job payload_json into form field data
that the FormExecutor / payment_request.json definition understands.

Kept in step with its TypeScript port, ``buildPaymentRequestData`` in the
Toolbox (``src/lib/suuForms/payload.ts``), which feeds the Connector browser
extension — the same mapping, run in the treasurer's own browser. A fix to
one belongs in the other.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

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
