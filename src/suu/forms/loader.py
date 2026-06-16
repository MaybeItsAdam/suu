"""Finding form definitions and the saved login for each form.

Form *definitions* (what fields a form has, how to fill them) ship inside the
package under ``definitions/``. Your saved *login* for a form lives under
``~/.suu`` (see :mod:`suu.core.paths`), kept well away from the code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from suu.core.paths import playwright_state_file
from suu.forms.schema import FormDefinition


def definitions_dir() -> Path:
    """Folder holding the built-in form definitions."""
    return Path(__file__).parent / "definitions"


def list_form_ids() -> List[str]:
    """The ids of every built-in form (e.g. ``payment_request``)."""
    return sorted(p.stem for p in definitions_dir().glob("*.json"))


def load_form_definition(form_id: str) -> FormDefinition:
    """Load a built-in form definition by its id."""
    path = definitions_dir() / f"{form_id}.json"
    if not path.exists():
        available = ", ".join(list_form_ids()) or "(none found)"
        raise FileNotFoundError(
            f"I don't know a form called '{form_id}'. Available forms: {available}."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return FormDefinition(**data)


def auth_file_for(form_id: str = "default") -> Path:
    """Where this form's saved login lives.

    Falls back to the shared ``default`` login if there isn't a form-specific one.
    """
    specific = playwright_state_file(form_id)
    if specific.exists():
        return specific
    return playwright_state_file("default")
