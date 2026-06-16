"""Knowing about the AI apps we can connect suu to, and connecting them.

This is what powers ``suu mcp setup``. Each known app says how to tell whether
it's installed and how to add/remove the ``suu`` server in its settings, so a
beginner never has to find and hand-edit a JSON file.

Adding another app later means adding one entry to ``KNOWN_CLIENTS`` below.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# The name the server is registered under inside each AI app.
SERVER_NAME = "suu"


def suu_server_command() -> Tuple[str, List[str]]:
    """The exact command an AI app should run to start suu's MCP server.

    We use an **absolute path** to the ``suu`` program, because apps like Claude
    Desktop launch with a bare environment and won't find ``suu`` on the PATH.
    If we somehow can't find it, fall back to running it through Python.
    """
    found = shutil.which("suu")
    if found:
        return found, ["mcp", "run"]
    return sys.executable, ["-m", "suu", "mcp", "run"]


def _server_entry() -> dict:
    command, args = suu_server_command()
    return {"command": command, "args": args}


@dataclass
class Client:
    """One AI app we know how to connect."""

    name: str  # friendly display name

    def is_installed(self) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def connect(self) -> str:
        raise NotImplementedError

    def disconnect(self) -> str:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Apps that store MCP servers in a JSON config file
# ---------------------------------------------------------------------------


@dataclass
class JsonFileClient(Client):
    """An app whose MCP servers live under a ``mcpServers`` key in a JSON file."""

    path: Path = Path()

    def is_installed(self) -> bool:
        # Treat the app as present if its config folder exists.
        return self.path.parent.exists()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _backup(self) -> Optional[Path]:
        if self.path.exists():
            backup = self.path.with_suffix(self.path.suffix + ".suu-backup")
            backup.write_text(self.path.read_text(encoding="utf-8"), encoding="utf-8")
            return backup
        return None

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def connect(self) -> str:
        data = self._load()
        backup = self._backup()
        servers = data.setdefault("mcpServers", {})
        existed = SERVER_NAME in servers
        servers[SERVER_NAME] = _server_entry()
        self._save(data)
        verb = "Updated" if existed else "Added"
        note = f" (your old settings were backed up to {backup.name})" if backup else ""
        return f"{verb} suu in {self.name}{note}."

    def disconnect(self) -> str:
        data = self._load()
        servers = data.get("mcpServers", {})
        if SERVER_NAME in servers:
            self._backup()
            del servers[SERVER_NAME]
            self._save(data)
            return f"Removed suu from {self.name}."
        return f"suu wasn't connected to {self.name} — nothing to remove."


# ---------------------------------------------------------------------------
# Apps driven through their own command-line tool
# ---------------------------------------------------------------------------


@dataclass
class ClaudeCodeClient(Client):
    """Claude Code — configured via its own `claude mcp` command."""

    def is_installed(self) -> bool:
        return shutil.which("claude") is not None

    def connect(self) -> str:
        command, args = suu_server_command()
        entry = json.dumps({"command": command, "args": args})
        result = subprocess.run(
            ["claude", "mcp", "add-json", SERVER_NAME, entry, "-s", "user"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return f"Added suu to {self.name}."
        return f"Couldn't add suu to {self.name}: {result.stderr.strip() or result.stdout.strip()}"

    def disconnect(self) -> str:
        result = subprocess.run(
            ["claude", "mcp", "remove", SERVER_NAME, "-s", "user"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return f"Removed suu from {self.name}."
        return f"suu wasn't connected to {self.name} — nothing to remove."


# ---------------------------------------------------------------------------
# Where each app keeps its config, per operating system
# ---------------------------------------------------------------------------


def _claude_desktop_config() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    if system == "Windows":
        base = os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming"))
        return Path(base) / "Claude/claude_desktop_config.json"
    return Path.home() / ".config/Claude/claude_desktop_config.json"


def _cursor_config() -> Path:
    return Path.home() / ".cursor/mcp.json"


def known_clients() -> List[Client]:
    """Every AI app suu knows how to connect, in a friendly order."""
    return [
        JsonFileClient(name="Claude Desktop", path=_claude_desktop_config()),
        ClaudeCodeClient(name="Claude Code"),
        JsonFileClient(name="Cursor", path=_cursor_config()),
    ]


def detect_installed() -> List[Client]:
    """The known AI apps that actually look installed on this computer."""
    return [c for c in known_clients() if c.is_installed()]


def manual_instructions() -> str:
    """A copy-pasteable snippet for apps we couldn't set up automatically."""
    entry = {"mcpServers": {SERVER_NAME: _server_entry()}}
    return (
        "Add this to your AI app's MCP settings (often a file called "
        "mcpServers / claude_desktop_config.json):\n\n"
        + json.dumps(entry, indent=2)
    )
