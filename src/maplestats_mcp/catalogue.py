"""The tool catalogue: what every module tool lists as, without importing it.

Importing every module's tools.py took about 11 of the 17 s the server
needed to import on 2026-10-22, and Render's free tier starts it cold after
each idle spell. tool_catalogue.json holds, per module, its component files
and each tool's listing (name, title, description, input and output schemas,
annotations, meta), so server.py lists and searches tools from it and imports
a module's code only when one of its tools is first resolved.

`uv run python scripts/build_tool_catalogue.py` regenerates the file;
tests/test_tool_catalogue.py fails when it no longer matches the code.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from fastmcp.prompts.base import Prompt
from fastmcp.resources.base import Resource
from fastmcp.resources.template import ResourceTemplate
from fastmcp.server.providers.filesystem_discovery import (
    extract_components,
    import_module_from_file,
)
from fastmcp.tools import Tool
from fastmcp.tools.base import ToolResult
from fastmcp.utilities.components import FastMCPComponent
from pydantic import Field

from maplestats_mcp import config

MODULES_ROOT = Path(__file__).parent / "modules"
CATALOGUE_PATH = Path(__file__).parent / "tool_catalogue.json"
CATALOGUE_FORMAT = 1
TOOL_FILES = frozenset({"tools.py"})
EXTRA_FILES = frozenset({"resources.py", "prompts.py"})

# The Tool fields tools/list and search_tools show; the rest (the function,
# auth, task settings) stay behind until the module is imported.
_LISTED_FIELDS = {
    "name",
    "version",
    "title",
    "description",
    "icons",
    "tags",
    "meta",
    "parameters",
    "output_schema",
    "annotations",
    "timeout",
}

# Tools a module defines only when a setting allows it. The catalogue is
# built with every switch on and lists these only while theirs is.
TOOL_SWITCHES: dict[str, Callable[[], bool]] = {
    "statcan_pumf_tabulate": config.get_pumf_tabulate_enabled,
}
_SWITCH_ENV = {"MAPLE_PUMF_TABULATE": "1"}


class CatalogueTool(Tool):
    """A tool as listed in the catalogue, with no function behind it.

    Listing and search use it; a call resolves the tool by name, which
    imports the module and runs the real one instead.
    """

    module: str = Field(exclude=True)

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise RuntimeError(f"{self.name} is a catalogue entry; resolve it with get_tool to run it")


def module_dirs() -> list[Path]:
    """Module folders the server registers; modules/_example/ is the template."""
    return [
        path
        for path in sorted(MODULES_ROOT.iterdir())
        if path.is_dir() and not path.name.startswith("_")
    ]


def component_files(root: Path) -> list[Path]:
    """A module's tools.py, resources.py and prompts.py files, sub-APIs included.

    Every other file stays unimported: FileSystemProvider's own scan also
    imported each module's __tests__/ (and so pytest) and client helpers,
    250 files and about 6 s of startup on 2026-09-24.
    """
    return sorted(
        path
        for path in root.rglob("*.py")
        if path.name in TOOL_FILES | EXTRA_FILES
        and "__pycache__" not in path.parts
        and "__tests__" not in path.parts
    )


def import_components(root: Path, files: Iterable[Path]) -> list[FastMCPComponent]:
    """Import the files as FileSystemProvider does and collect their components.

    An import failure is raised: FileSystemProvider only logs it, so a broken
    module silently disappeared.
    """
    components: list[FastMCPComponent] = []
    for file_path in files:
        module = import_module_from_file(file_path, provider_root=root)
        components.extend(extract_components(module))
    return components


def tool_module(tool: Tool) -> str:
    """The module a tool's function is defined in, as the server imports it.

    The provider imports a module folder as its own package, so the names
    are short: "boc.tools", "statcan.wds.tools".
    """
    if isinstance(tool, CatalogueTool):
        return tool.module
    return getattr(getattr(tool, "fn", None), "__module__", "") or ""


def _tool_entry(tool: Tool) -> dict[str, Any]:
    entry = {
        "module": tool_module(tool),
        **tool.model_dump(mode="json", include=_LISTED_FIELDS, exclude_defaults=True),
    }

    # A set dumps in hash order, which would change the file between runs.
    if tool.tags:
        entry["tags"] = sorted(tool.tags)
    return entry


def _check_component(component: FastMCPComponent, file_path: Path) -> None:
    """Refuse what the catalogue cannot carry or would load from the wrong file."""
    place = f"{component.name} in {file_path}"
    if isinstance(component, Tool) != (file_path.name in TOOL_FILES):
        raise ValueError(f"{place}: tools belong in tools.py, resources and prompts outside it")
    if component.task_config.supports_tasks():
        raise ValueError(f"{place}: background tasks are not supported by the lazy loader")
    if isinstance(component, Tool) and (component.auth is not None or component.execution):
        raise ValueError(f"{place}: per-tool auth and execution are not in the catalogue")
    if not isinstance(component, Tool | Resource | ResourceTemplate | Prompt):
        raise TypeError(f"{place}: unknown component type {type(component).__name__}")


def build_catalogue() -> str:
    """Import every module and render the catalogue file's text.

    One line per tool, so a change to a tool shows as a one-line diff.
    """
    saved = {name: os.environ.get(name) for name in _SWITCH_ENV}
    os.environ.update(_SWITCH_ENV)
    try:
        modules = []
        for root in module_dirs():
            files = component_files(root)
            tools = []
            for file_path in files:
                for component in import_components(root, [file_path]):
                    _check_component(component, file_path)
                    if isinstance(component, Tool):
                        tools.append(_tool_entry(component))
            relative = [path.relative_to(root).as_posix() for path in files]
            modules.append((root.name, relative, sorted(tools, key=lambda t: t["name"])))
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    lines = [f'{{"format": {CATALOGUE_FORMAT}, "modules": {{']
    for index, (name, files, tools) in enumerate(modules):
        head = json.dumps(name) + ': {"files": ' + json.dumps(files) + ', "tools": ['
        body = ",\n".join(json.dumps(tool, ensure_ascii=False) for tool in tools)
        tail = "]}" + ("," if index < len(modules) - 1 else "")
        lines.append(head + ("\n" + body + "\n" if body else "") + tail)
    lines.append("}}")
    return "\n".join(lines) + "\n"


def write_catalogue(path: Path = CATALOGUE_PATH) -> None:
    path.write_text(build_catalogue(), encoding="utf-8", newline="\n")


def read_catalogue(path: Path = CATALOGUE_PATH) -> dict[str, Any] | None:
    """The catalogue's modules by folder name, or None to load every module eagerly."""
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != CATALOGUE_FORMAT:
        return None
    return data["modules"]
