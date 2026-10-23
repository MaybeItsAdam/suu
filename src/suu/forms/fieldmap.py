"""Turning a Connector field map into form-definition fields.

The Connector's dev-build "Capture this SU page" (``lib/form-probe.js`` in
``../adams-campus-toolbox-connector``) saves ``fieldmap-<page>.json``:

    {"url", "title", "forms": [{"id", "selector", "action", "method",
      "fields": [{"tag", "type", "name", "id", "selector", "label",
                  "required", "hidden", "description"?, "multiple"?,
                  "autocomplete"?, "chosen"?, "options"?: [{"value", "text"}],
                  "text"?}]}],
     "controlsOutsideForms": [...]}

``selector`` there is the control's ``data-drupal-selector``. No value anyone
typed is in it. Field maps live in ``samples/su/forms/<form_id>/``.

Two jobs, both mechanical so a capture turns into a definition without
guesswork:

- :func:`draft_fields` writes a definition's ``fields`` from the main form:
  one field per visible-or-conditional control, repeating table rows
  (``edit-<table>-items-0-<column>``) folded into a ``list`` with ``{i}``,
  selectors by ``data-drupal-selector``. It never emits a button, so it
  can't press Submit; "add another" buttons become a list's
  ``add_button_selector`` only when they name the same table.
- :func:`match_definition` runs an existing definition's selectors against
  the captured controls (rebuilt as a skeleton page) and says which fields
  it finds, which it doesn't, and whether any action selector would reach a
  submit button.

A human still names the fields (the payload builders' keys) and decides what
each one is for; the draft names them after their Drupal keys.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from suu.forms.schema import FormDefinition, FormField

#: Buttons that send the form. Nothing a definition clicks may match one.
FINAL_SUBMIT = re.compile(
    r"^edit-(actions-)?(submit|preview|delete|draft|save|publish)$|^edit-actions-(wizard-next|wizard-prev)$",
)
#: A Drupal multi-value table row: ``edit-<table>-items-<n>-<column...>``.
ROW = re.compile(r"^edit-(?P<table>.+?)-items-(?P<index>\d+)-(?P<column>.+)$")
#: Drupal's "add another item" button for a table.
ADD_BUTTON = re.compile(r"^edit-(?P<table>.+?)-(add-submit|add-more|add-more-add-more)$")
TEXT_INPUTS = {"text", "email", "tel", "number", "url", "date", "time", "datetime-local", "search", "password"}
BUTTON_TYPES = {"submit", "button", "reset", "image"}
#: Forms on every SU page that are never the one being captured.
CHROME_FORMS = re.compile(r"search|user-login|newsletter|feedback|rate", re.I)


def load_field_map(path: str | Path) -> dict:
    """Read a ``fieldmap-*.json`` and check it has the probe's shape."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("forms"), list):
        raise ValueError(f"{path} isn't a Connector field map (no 'forms' list).")
    for form in data["forms"]:
        if not isinstance(form.get("fields"), list):
            raise ValueError(f"{path}: a form has no 'fields' list.")
    return data


def main_form(field_map: dict) -> dict:
    """The form being captured: the one with most fillable controls, ignoring site chrome."""
    candidates = [
        f for f in field_map["forms"]
        if not CHROME_FORMS.search(f"{f.get('id', '')} {f.get('selector', '')}")
    ]
    if not candidates:
        raise ValueError("The field map has no form other than the site's own (search, login).")
    return max(candidates, key=lambda f: sum(1 for c in f["fields"] if _fillable(c)))


def _fillable(control: dict) -> bool:
    return control.get("type") not in BUTTON_TYPES | {"hidden"} and control.get("tag") != "button"


def _key(selector: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", re.sub(r"^edit-", "", selector).lower()).strip("_")


def _css(control: dict, selector: str | None = None) -> str:
    tag = control.get("tag") or ""
    if selector or control.get("selector"):
        return f"{tag}[data-drupal-selector='{selector or control['selector']}']"
    if control.get("id"):
        return f"{tag}[id='{control['id']}']"
    return f"{tag}[name='{control.get('name', '')}']"


def _options(control: dict) -> list[str] | None:
    texts = [o.get("text", "") for o in control.get("options") or []]
    texts = [t for t in texts if t and not re.match(r"^-\s*(select|none|choose)", t, re.I)]
    return texts or None


def _describe(control: dict) -> str:
    return " — ".join(p for p in (control.get("label"), control.get("description")) if p)


def _field(control: dict, name: str, selector: str | None = None) -> FormField | None:
    """One definition field for a control, or None for what a definition never touches."""
    tag, kind = control.get("tag"), control.get("type")
    if not _fillable(control):
        return None
    css = _css(control, selector)
    if tag == "textarea":
        ftype = "textarea"
    elif tag == "select":
        if control.get("chosen"):
            css = f"{css} + .chosen-container"
            ftype = "chosen_select"
        else:
            ftype = "select"
    elif kind == "file":
        ftype = "file"
    elif kind in ("checkbox", "radio"):
        ftype = "checkbox"
    elif control.get("autocomplete"):
        ftype = "autocomplete"
    elif kind in TEXT_INPUTS:
        ftype = "text"
    else:
        return None
    hidden = bool(control.get("hidden"))
    return FormField(
        name=name,
        selector=css,
        type=ftype,
        description=_describe(control) or None,
        # A control hidden at capture time is behind a condition, so never required up front.
        required=bool(control.get("required")) and not hidden,
        options=_options(control) if ftype in ("select", "chosen_select") else None,
        confirmed=True,
        shown_when="hidden when captured: behind a condition (capture each state)" if hidden else None,
    )


def draft_fields(field_map: dict) -> list[FormField]:
    """
    The main form's controls as definition fields, in page order.

    A checkbox or radio becomes one ``checkbox`` field per option (Playwright's
    ``check()`` takes a radio too), named ``<group>__<value>``. Rows of a
    multi-value table become one ``list`` field (row 0's columns, with
    ``{i}``); later rows in the capture are dropped. Buttons, hidden inputs and
    Drupal's form tokens are left out.
    """
    form = main_form(field_map)
    controls = form["fields"]
    add_buttons = {
        m.group("table"): c["selector"]
        for c in controls
        if (m := ADD_BUTTON.match(c.get("selector") or "")) and not FINAL_SUBMIT.match(c["selector"])
    }
    out: list[FormField] = []
    tables: dict[str, FormField] = {}
    seen: set[str] = set()
    for control in controls:
        selector = control.get("selector") or ""
        if FINAL_SUBMIT.match(selector) or not _fillable(control):
            continue
        row = ROW.match(selector)
        if row:
            table, column = row.group("table"), row.group("column")
            if row.group("index") != "0":
                continue
            templated = f"edit-{table}-items-{{i}}-{column}"
            child = _field(control, _key(column), templated)
            if child is None:
                continue
            if table not in tables:
                tables[table] = FormField(
                    name=_key(table),
                    type="list",
                    description=f"Rows of the '{table}' table",
                    required=False,
                    add_button_selector=(
                        f"[data-drupal-selector='{add_buttons[table]}']" if table in add_buttons else None
                    ),
                    fields=[],
                )
                out.append(tables[table])
            tables[table].fields.append(child)
            continue
        name = _key(selector or control.get("name") or control.get("id") or "")
        if control.get("type") in ("checkbox", "radio") and control.get("name"):
            group = _key(control["name"])
            value = _key(control.get("label") or selector or "")
            name = f"{group}__{value}" if value and value != group else group
        if not name or name in seen:
            continue
        field = _field(control, name)
        if field:
            seen.add(name)
            out.append(field)
    return out


# ---------------------------------------------------------------------------
# Checking a definition against a capture
# ---------------------------------------------------------------------------

def skeleton_html(field_map: dict) -> str:
    """
    The captured controls as a bare page, so CSS selectors can be tried on them.

    Each control keeps its tag, ``type``, ``name``, ``id`` and
    ``data-drupal-selector``; a Chosen select gets the ``#<id>_chosen``
    container Chosen draws after it. Nesting and classes aren't in a field
    map, so a selector that leans on them won't match here — use the redacted
    page for those.
    """
    def attrs(control: dict) -> str:
        pairs = [("name", control.get("name")), ("id", control.get("id")), ("data-drupal-selector", control.get("selector"))]
        if control.get("tag") == "input" or control.get("tag") == "button":
            pairs.insert(0, ("type", control.get("type")))
        return "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in pairs if v)

    parts = []
    for form in field_map["forms"]:
        form_id = form.get("id")
        parts.append(f'<form id="{html.escape(form_id, quote=True)}">' if form_id else "<form>")
        for control in form["fields"]:
            tag = control.get("tag") or "input"
            if tag == "input":
                parts.append(f"<input{attrs(control)}>")
            else:
                parts.append(f"<{tag}{attrs(control)}></{tag}>")
            if tag == "select" and control.get("chosen") and control.get("id"):
                parts.append(
                    f'<div id="{html.escape(control["id"])}_chosen" class="chosen-container">'
                    '<a></a><div class="chosen-drop"><input type="text"></div></div>'
                )
        parts.append("</form>")
    return "<html><body>" + "".join(parts) + "</body></html>"


def _interpolate(selector: str, index: int = 0) -> str:
    return selector.replace("{i}", str(index)).replace("{n}", str(index + 1))


def _walk(fields: list[FormField], prefix: str = "") -> list[tuple[str, FormField]]:
    out = []
    for field in fields:
        path = f"{prefix}{field.name}"
        out.append((path, field))
        out.extend(_walk(field.fields or [], f"{path}[]."))
    return out


def action_selectors(definition: FormDefinition) -> list[str]:
    """Everything a definition clicks, presses or ticks — the executors' list."""
    out = []
    for _path, field in _walk(definition.fields):
        if field.type in ("click", "press_enter", "checkbox") and field.selector:
            out.append(field.selector)
        if field.add_button_selector:
            out.append(field.add_button_selector)
    return out


def match_definition(definition: FormDefinition, field_map: dict) -> dict[str, Any]:
    """
    ``{"found": [...], "missing": [...], "reaches_submit": [...]}`` for a definition
    tried against a capture's controls.

    ``missing`` lists required fields first. ``reaches_submit`` must be empty:
    it names any action selector that lands on a button whose
    ``data-drupal-selector`` is a final submit (``FINAL_SUBMIT``) or whose words
    are "Submit".
    """
    from bs4 import BeautifulSoup  # the `forms` extra

    soup = BeautifulSoup(skeleton_html(field_map), "html.parser")
    found, missing = [], []
    for path, field in _walk(definition.fields):
        if not field.selector:
            continue
        hit = soup.select(_interpolate(field.selector))
        (found if hit else missing).append({"field": path, "required": field.required, "selector": field.selector})
    missing.sort(key=lambda m: not m["required"])

    submit_selectors = {
        c.get("selector")
        for form in field_map["forms"]
        for c in form["fields"]
        if c.get("selector")
        and (FINAL_SUBMIT.match(c["selector"]) or (c.get("text") or "").strip().lower() == "submit")
    }
    reaches = []
    for selector in action_selectors(definition):
        for index in (0, 1):
            for element in soup.select(_interpolate(selector, index)):
                if element.get("data-drupal-selector") in submit_selectors:
                    reaches.append(selector)
    return {"found": found, "missing": missing, "reaches_submit": sorted(set(reaches))}
