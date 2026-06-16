"""The MCP server — lets an AI assistant (e.g. Claude) fill SU forms for you.

You normally don't run this by hand: `suu mcp setup` connects your AI app, which
then starts this server itself. To run it directly: `suu mcp run`.
"""

from __future__ import annotations

import json
import os

from fastmcp import FastMCP

from suu.forms.executor import FormExecutor
from suu.forms.loader import auth_file_for, definitions_dir, list_form_ids, load_form_definition

mcp = FastMCP(
    "suu",
    instructions="""
    You are an assistant that can fill in UCL Students' Union web forms.

    CONTEXT:
    - Location: London, UK (University College London)
    - Currency: GBP (£)
    - Date Format: DD/MM/YYYY
    - Banking: Uses UK Sort Code (6 digits) and Account Number (8 digits)

    AVAILABLE ACTIONS:
    1. list_available_forms() - See what forms you can fill
    2. run_form_automation(form_id, data) - Fill a form with the user's data

    WORKFLOW:
    1. First call list_available_forms() to see what's available
    2. Ask the user for the required data fields
    3. Call run_form_automation() with the form_id and data as JSON

    IMPORTANT BEHAVIORS:
    - Always confirm with the user before running automation
    - Forms are NEVER submitted - only filled for the user to review
    - A browser window will open so the user can see what's happening
    - The browser stays open after filling so the user can review and submit manually

    AUTHENTICATION:
    - Forms require the user to be logged in to the Students' Union website
    - Their login is saved on their computer and expires after a while (hours to days)

    IF AUTHENTICATION FAILS (you see "Not logged in" or the form redirects to a login page):
    - Tell the user: "Your Students' Union login has expired or isn't set up yet."
    - Ask them to run this in a terminal:  suu forms login
    - That opens a browser where they log in once, then it saves their login
    - After they confirm it's done, retry the form automation
    """,
)


@mcp.tool()
def list_available_forms() -> str:
    """
    Lists all form automations that are ready to use.
    Call this FIRST to see what forms you can help fill.
    Returns form IDs, descriptions, and the data fields required.
    """
    forms = []
    for filename in os.listdir(definitions_dir()):
        if filename.endswith(".json"):
            try:
                with open(definitions_dir() / filename, "r") as f:
                    form_def = json.load(f)
                    form_id = form_def.get("form_id", filename.replace(".json", ""))
                    description = form_def.get("description", "No description")

                    # Build detailed field info
                    fields = form_def.get("fields", [])
                    field_info = []
                    for f in fields:
                        name = f.get("name")
                        desc = f.get("description", "")
                        required = f.get("required", True)
                        options = f.get("options")

                        info = {
                            "name": name,
                            "description": desc,
                            "required": required,
                        }
                        if options:
                            info["allowed_values"] = options
                        field_info.append(info)

                    forms.append(
                        {
                            "form_id": form_id,
                            "description": description,
                            "fields": field_info,
                        }
                    )
            except Exception:
                continue

    if not forms:
        return "No forms configured. The user needs to set up form definitions first."

    result = "AVAILABLE FORMS:\n\n"
    for form in forms:
        result += f"## {form['form_id']}\n"
        result += f"{form['description']}\n\n"
        result += "Required data fields:\n"
        for field in form["fields"]:
            req = "(required)" if field["required"] else "(optional)"
            result += f"  - {field['name']} {req}: {field['description']}\n"
            if "allowed_values" in field:
                result += f"    Allowed values: {field['allowed_values']}\n"
        result += "\n"

    return result


@mcp.resource("logo://png")
def get_logo() -> bytes:
    """Returns the server logo."""
    try:
        with open(os.path.join(os.path.dirname(__file__), "logo.png"), "rb") as f:
            return f.read()
    except FileNotFoundError:
        return b""


@mcp.tool()
async def run_form_automation(form_id: str, data: str) -> str:
    """
    Fills a web form with the provided data. Opens a visible browser window.
    The form is NEVER submitted - it only fills fields for the user to review.

    Args:
        form_id: Which form to fill (get this from list_available_forms)
        data: JSON string with the field values. Example:
              {"club_society": "Chess Club", "description": "Equipment purchase", ...}

    Returns:
        Success or error message.
    """
    try:
        form_def = load_form_definition(form_id)
    except FileNotFoundError:
        return (
            f"Form '{form_id}' not found. Available: {list_form_ids()}. "
            "Call list_available_forms() for details."
        )

    try:
        data_dict = json.loads(data)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}. Data must be a valid JSON string."

    auth_file = str(auth_file_for(form_id))

    # Use visible browser so user can see what's happening
    executor = FormExecutor(headless=False)
    await executor.start()

    if os.path.exists(auth_file):
        await executor.load_auth(auth_file)
    else:
        await executor.stop()
        return "Not logged in. Ask the user to run 'suu forms login' first."

    try:
        await executor.execute(form_def, data_dict)
        # NOTE: We do NOT call executor.stop() here - browser stays open for user to review
        return (
            f"SUCCESS: Form '{form_id}' has been filled. The browser window is open "
            "for review. Close it manually when done. The form was NOT submitted."
        )
    except Exception as e:
        await executor.stop()  # Only close on error
        return f"FAILED: {e}"


if __name__ == "__main__":
    mcp.run()
