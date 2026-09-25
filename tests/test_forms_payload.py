"""Tests for the payload mapping and the form definitions.

The same checks run against the Toolbox's copies (``src/lib/suuForms/*.test.ts``),
which feed the Connector extension; these keep suu — the source of truth — honest
on its own.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import pytest

from suu.forms.loader import list_form_ids, load_form_definition
from suu.forms.payload import (
    format_cost,
    normalize_banking_number,
    normalize_payload,
    su_expenditure_type,
)
from suu.forms.schema import FormField


def walk(fields: list[FormField]) -> list[FormField]:
    out: list[FormField] = []
    for field in fields:
        out.append(field)
        out.extend(walk(field.fields or []))
    return out


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("form_id", list_form_ids())
def test_definitions_never_click_submit(form_id):
    """Filling never submits — a definition that clicks Submit would."""
    for field in walk(load_form_definition(form_id).fields):
        assert not field.is_submit, f"{form_id}.{field.name}"
        if field.type == "click" and field.selector:
            assert not re.search(
                r"type=['\"]?submit|edit-actions-submit|edit-submit", field.selector, re.I
            ), f"{form_id}.{field.name}"


@pytest.mark.parametrize("form_id", list_form_ids())
def test_definitions_are_keyed_by_id_and_point_at_the_su(form_id):
    definition = load_form_definition(form_id)
    assert definition.form_id == form_id
    assert urlparse(definition.url).hostname == "studentsunionucl.org"


def test_payload_keys_match_the_payment_request_fields():
    """Every key the mapping produces is a field, and every field it should fill has a key."""
    definition = load_form_definition("payment_request")
    data = normalize_payload({})
    top = {f.name for f in definition.fields}
    receipts = next(f for f in definition.fields if f.name == "receipts")
    item = {f.name for f in receipts.fields or []}

    assert set(data) <= top
    assert set(data["receipts"][0]) == item
    # Fields the mapping leaves alone carry their own value or aren't from a receipt.
    unfilled = {f.name for f in definition.fields if f.name not in data and f.value is None}
    assert unfilled <= {"activity_registration_form"}


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------

def test_expenditure_type_maps_toolbox_categories_onto_su_options():
    assert su_expenditure_type("Coach/Instructor") == "COACH/INSTRUCTORS"
    assert su_expenditure_type("transport") == "TRANSPORT"
    assert su_expenditure_type("") == "MISCELLANEOUS EXPENDITURE"
    # Unknown stays as typed; the treasurer sees the dropdown.
    assert su_expenditure_type("Llama hire") == "LLAMA HIRE"


def test_format_cost():
    assert format_cost(4) == "4.00"
    assert format_cost("12.5") == "12.50"
    assert format_cost("£1,234.5") == "1234.50"
    assert format_cost(None) == ""
    assert format_cost("") == ""


def test_banking_numbers_are_zero_padded():
    assert normalize_banking_number("4-00-04", 6) == "040004"
    assert normalize_banking_number("1234567", 8) == "01234567"
    assert normalize_banking_number("", 8) == ""


def test_payee_is_the_account_holder_before_the_submitter():
    data = normalize_payload({"AccountName": "A LOVELACE", "submittedBy": "Ada Lovelace"})
    assert data["payee_name"] == "A LOVELACE"
    assert normalize_payload({"submittedBy": "Ada Lovelace"})["payee_name"] == "Ada Lovelace"


def test_normalize_payload_end_to_end(tmp_path):
    receipt = tmp_path / "r1.png"
    data = normalize_payload(
        {
            "Show": "Volunteering Society",
            "notes": "Train",
            "accountName": "A LOVELACE",
            "PhoneNumber": "07700 900000",
            "uclEmail": "ada@ucl.ac.uk",
            "accountNumber": "12345678",
            "sortCode": "04-00-04",
            "category": "Transport",
            "amount": 4,
        },
        receipt,
    )
    assert data == {
        "club_society": "Volunteering Society",
        "description": "Train",
        "payee_name": "A LOVELACE",
        "phone_number": "07700 900000",
        "email": "ada@ucl.ac.uk",
        "account_number": "12345678",
        "sort_code": "040004",
        "receipts": [
            {
                "expenditure_type": "TRANSPORT",
                "expenditure_type_search": "TRANSPORT",
                "expenditure_type_select": "",
                "grant": "N",
                "cost": "4.00",
                "file": str(receipt),
            }
        ],
    }
