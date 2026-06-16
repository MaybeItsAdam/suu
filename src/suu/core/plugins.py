"""The little plugin system the scraper uses to export data.

Each exporter (CSV, Excel, clipboard, Supabase, …) is a class that inherits
from :class:`PluginBase` and lives in a folder we scan at runtime. Adding a new
export format is just dropping a new file in that folder — no wiring needed.

Ported from suu-scrape's ``core/base.py`` and ``core/loader.py``.
"""

from __future__ import annotations

import glob
import importlib.util
import os
import sys
from abc import ABC, abstractmethod
from typing import Any, List, Optional, Type


class PluginBase(ABC):
    """Base class for every suu export plugin."""

    @abstractmethod
    def run(self, data: Any, context: dict) -> None:
        """Do the export.

        :param data: The data the scraper produced.
        :param context: Shared settings/flags for this run.
        """
        ...

    def setup(self, config: dict) -> None:
        """Optional one-time setup, called before :meth:`run`."""
        pass


def load_plugin_from_file(file_path: str) -> Optional[Type[PluginBase]]:
    """Load a single :class:`PluginBase` subclass from a Python file."""
    try:
        module_name = os.path.basename(file_path).replace(".py", "")
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        for attribute_name in dir(module):
            attribute = getattr(module, attribute_name)
            if (
                isinstance(attribute, type)
                and issubclass(attribute, PluginBase)
                and attribute is not PluginBase
            ):
                return attribute

        raise ValueError(f"No PluginBase subclass found in {file_path}")
    except Exception as e:
        print(f"Failed to load plugin from {file_path}: {e}")
        return None


def discover_plugins(plugins_dir: str) -> List[Type[PluginBase]]:
    """Find and load every plugin in *plugins_dir*."""
    plugins: List[Type[PluginBase]] = []
    for file_path in glob.glob(os.path.join(plugins_dir, "*.py")):
        if "__init__" in file_path:
            continue
        plugin_class = load_plugin_from_file(file_path)
        if plugin_class:
            plugins.append(plugin_class)
    return plugins
