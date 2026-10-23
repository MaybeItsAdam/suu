"""Tests for the payload mapping and the form definitions.

The same checks run against the Toolbox's copies (``src/lib/suuForms/*.test.ts``),
which feed the Connector extension; these keep suu — the source of truth — honest
on its own.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import pytest

from suu.forms.loader import definitions_dir, list_form_ids, load_form_definition
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


SCAFFOLDS = {"su_activity_registration", "su_ticket_request", "su_event_listing", "risk_assessment", "room_booking"}
#: Scaffolds whose fields are drafted from public guidance, every one unconfirmed.
DRAFTED = {"su_activity_registration", "su_ticket_request", "su_event_listing"}


@pytest.mark.parametrize("form_id", sorted(SCAFFOLDS))
def test_scaffolds_load_and_say_what_is_unverified(form_id):
    """A scaffold has its URL and no unverified selectors; `_todo` says what's left.

    `_todo` is ignored by the schema (pydantic drops unknown keys), so it's read raw.
    """
    raw = json.loads((definitions_dir() / f"{form_id}.json").read_text(encoding="utf-8"))
    assert raw["_todo"]["status"] == "scaffold"
    assert raw["_todo"]["unverified"]
    assert load_form_definition(form_id).login_required


def _raw(form_id):
    return json.loads((definitions_dir() / f"{form_id}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("form_id", sorted(DRAFTED))
def test_drafted_scaffolds_mark_every_field_unconfirmed(form_id):
    """A drafted field's selector is a guess until a capture shows it."""
    fields = walk(load_form_definition(form_id).fields)
    assert fields
    assert [f.name for f in fields if f.confirmed] == []


@pytest.mark.parametrize("form_id", list_form_ids())
def test_only_scaffolds_carry_unconfirmed_fields(form_id):
    """A form that isn't a scaffold has had every selector seen on the real page."""
    unconfirmed = [f.name for f in walk(load_form_definition(form_id).fields) if not f.confirmed]
    if unconfirmed:
        assert _raw(form_id).get("_todo", {}).get("status") == "scaffold", unconfirmed


#: Every way an SU form is sent: a webform's Submit, Save draft and wizard
#: Next, a node form's Save, Preview and Delete, and a bare submit button.
FINAL_SUBMIT_PAGE = """<form>
  <input type="text" data-drupal-selector="edit-title-0-value">
  <input type="checkbox" data-drupal-selector="edit-field-event-online-value">
  <div id="edit-actions" class="form-actions" data-drupal-selector="edit-actions">
    <input type="submit" id="edit-actions-submit" data-drupal-selector="edit-actions-submit" name="op" value="Submit">
    <input type="submit" id="edit-actions-draft" data-drupal-selector="edit-actions-draft" name="op" value="Save Draft">
    <input type="submit" id="edit-actions-wizard-next" data-drupal-selector="edit-actions-wizard-next" name="op" value="Next">
    <input type="submit" id="edit-submit" data-drupal-selector="edit-submit" name="op" value="Save">
    <input type="submit" id="edit-preview" data-drupal-selector="edit-preview" name="op" value="Preview">
    <a id="edit-delete" data-drupal-selector="edit-delete" href="/node/1/delete">Delete</a>
  </div>
  <button type="submit">Submit</button>
</form>"""


@pytest.mark.parametrize("form_id", list_form_ids())
def test_no_action_selector_reaches_a_submit_button(form_id):
    """Nothing a definition clicks, presses, ticks or adds may land on a way of sending the form."""
    from bs4 import BeautifulSoup

    from suu.forms.fieldmap import action_selectors

    soup = BeautifulSoup(FINAL_SUBMIT_PAGE, "html.parser")
    actions = soup.select("#edit-actions, #edit-actions *, button[type=submit]")
    for selector in action_selectors(load_form_definition(form_id)):
        for index in (0, 1):
            css = selector.replace("{i}", str(index)).replace("{n}", str(index + 1))
            hits = [el for el in soup.select(css) if el in actions]
            assert hits == [], f"{form_id}: {selector}"


@pytest.mark.parametrize("form_id", list_form_ids())
def test_definitions_have_no_submit_step(form_id):
    """`steps` is the other way a definition could act; none may click or submit."""
    for step in load_form_definition(form_id).steps or []:
        assert step.action not in ("submit",), f"{form_id}.{step.name}"
        if step.action == "click" and step.selector:
            assert not re.search(r"submit|edit-actions|preview|edit-delete", step.selector, re.I), f"{form_id}.{step.name}"


def test_every_form_without_fields_is_a_known_scaffold():
    for form_id in list_form_ids():
        if not load_form_definition(form_id).fields:
            assert form_id in SCAFFOLDS, form_id


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
