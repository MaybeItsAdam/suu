"""Connector field map → definition fields (``suu.forms.fieldmap``).

Against ``samples/su/forms/payment_request/fieldmap-synthetic.json``, a
hand-written field map in the probe's shape built from the released payment
request's real selectors. Every real capture saved under ``samples/su/forms/``
is also checked: its draft never presses a button, and the definition it's for
never reaches its Submit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from suu.forms.fieldmap import (
    FINAL_SUBMIT,
    draft_fields,
    load_field_map,
    main_form,
    match_definition,
)
from suu.forms.loader import list_form_ids, load_form_definition
from suu.forms.schema import FormField

FORMS = Path(__file__).resolve().parents[1] / "samples" / "su" / "forms"
SYNTHETIC = FORMS / "payment_request" / "fieldmap-synthetic.json"
CAPTURES = sorted(FORMS.glob("*/fieldmap-*.json"))


@pytest.fixture
def field_map():
    return load_field_map(SYNTHETIC)


def by_name(fields: list[FormField]) -> dict[str, FormField]:
    return {f.name: f for f in fields}


def test_load_refuses_something_that_isnt_a_field_map(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text(json.dumps({"title": "no forms"}))
    with pytest.raises(ValueError):
        load_field_map(bad)


def test_main_form_skips_the_site_search(field_map):
    assert main_form(field_map)["id"] == "webform-submission-payment-request-form-add-form"


def test_draft_maps_each_control_type(field_map):
    fields = by_name(draft_fields(field_map))
    assert fields["webform_access_group"].type == "autocomplete"
    assert fields["webform_access_group"].selector == "input[data-drupal-selector='edit-webform-access-group']"
    assert fields["description"].type == "textarea"
    assert fields["payee_phone_number"].type == "text"
    assert fields["payee_details_changed"].type == "select"
    # The "- Select -" placeholder isn't an option.
    assert fields["payee_details_changed"].options == ["No", "Yes"]
    assert all(f.confirmed for f in fields.values())


def test_draft_splits_a_radio_group_into_one_tick_per_option(field_map):
    fields = by_name(draft_fields(field_map))
    assert fields["urgent__yes"].type == "checkbox"
    assert fields["urgent__yes"].selector == "input[data-drupal-selector='edit-urgent-yes']"
    assert "urgent__no" in fields


def test_draft_marks_a_hidden_field_conditional_not_required(field_map):
    reason = by_name(draft_fields(field_map))["urgent_reason"]
    assert reason.required is False
    assert reason.shown_when


def test_draft_folds_table_rows_into_a_list(field_map):
    fields = by_name(draft_fields(field_map))
    purchases = fields["purchases"]
    assert purchases.type == "list"
    assert purchases.add_button_selector == "[data-drupal-selector='edit-purchases-add-submit']"
    children = by_name(purchases.fields)
    # Row 1's copy of `net` is dropped; row 0 is templated with {i}.
    assert set(children) == {"account_code_nomcod", "account_code_cc", "net", "receipt_upload"}
    assert children["net"].selector == "input[data-drupal-selector='edit-purchases-items-{i}-net']"
    assert children["account_code_nomcod"].type == "chosen_select"
    assert children["account_code_nomcod"].selector.endswith(" + .chosen-container")
    assert children["account_code_nomcod"].options == ["MISCELLANEOUS EXPENDITURE", "TRANSPORT", "FACILITY HIRE"]
    assert children["receipt_upload"].type == "file"


def test_draft_never_presses_a_button(field_map):
    """No button, hidden input or token becomes a field; nothing is a click."""
    def walk(fields):
        for f in fields:
            yield f
            yield from walk(f.fields or [])

    drafted = list(walk(draft_fields(field_map)))
    assert not [f.name for f in drafted if f.type in ("click", "press_enter") or f.is_submit]
    selectors = " ".join(f.selector or "" for f in drafted)
    for word in ("edit-actions-submit", "upload-button", "form_build_id", "edit-submit-search"):
        assert word not in selectors


def test_final_submit_pattern():
    for sel in ("edit-actions-submit", "edit-submit", "edit-preview", "edit-actions-draft", "edit-delete"):
        assert FINAL_SUBMIT.match(sel), sel
    for sel in ("edit-purchases-add-submit", "edit-purchases-items-0-receipt-upload-button", "edit-description"):
        assert not FINAL_SUBMIT.match(sel), sel


def test_released_payment_request_matches_its_synthetic_capture(field_map):
    """The loader agrees with the one definition that has been filled for real."""
    result = match_definition(load_form_definition("payment_request"), field_map)
    found = {m["field"] for m in result["found"]}
    assert {
        "club_society", "description", "activity_registration_form", "payee_name", "phone_number",
        "email", "account_number", "sort_code", "payee_details_changed",
        "receipts[].grant", "receipts[].cost", "receipts[].file",
    } <= found
    # The Chosen dropdown's selectors lean on table nesting a field map doesn't keep.
    assert {m["field"] for m in result["missing"]} == {
        "receipts[].expenditure_type", "receipts[].expenditure_type_search", "receipts[].expenditure_type_select",
    }
    assert result["reaches_submit"] == []


def test_match_flags_an_action_that_reaches_submit(field_map):
    definition = load_form_definition("payment_request").model_copy(deep=True)
    definition.fields.append(FormField(name="oops", selector="input[data-drupal-selector$='submit']", type="click"))
    assert match_definition(definition, field_map)["reaches_submit"] == ["input[data-drupal-selector$='submit']"]


def test_cli_draft_prints_fields_and_the_match():
    from suu.cli import cli

    result = CliRunner().invoke(cli, ["forms", "draft", str(SYNTHETIC), "--against", "payment_request"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert any(f["name"] == "purchases" for f in out["fields"])
    assert out["match"]["reaches_submit"] == []


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_saved_capture_drafts_safely(capture):
    """A real capture's draft presses nothing, and its definition never reaches its Submit."""
    data = load_field_map(capture)
    for field in draft_fields(data):
        assert field.type not in ("click", "press_enter")
    if capture.parent.name in list_form_ids():
        assert match_definition(load_form_definition(capture.parent.name), data)["reaches_submit"] == []
