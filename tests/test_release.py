"""Release metadata stays consistent across PyPI, the MCP Registry and the code."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tomllib
import zipfile
from pathlib import Path

from maplestats_mcp import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_versions_match_everywhere():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    versions = {
        "pyproject": project["version"],
        "__version__": __version__,
        "server.json": server["version"],
        "server.json package": server["packages"][0]["version"],
    }
    assert len(set(versions.values())) == 1, versions


def test_registry_name_and_readme_ownership_line():
    # The MCP Registry verifies PyPI ownership through this README comment.
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"<!-- mcp-name: {server['name']} -->" in readme
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert server["packages"][0]["identifier"] == project["name"]
    # The registry caps descriptions at 100 characters.
    assert len(server["description"]) <= 100


def test_release_pins_a_real_publisher_checksum():
    # An all-zero placeholder passes review but fails `sha256sum -c` after
    # the PyPI upload, leaving the release half published.
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    match = re.search(r'MCP_PUBLISHER_SHA256: "([0-9a-f]{64})"', workflow)
    assert match, "release.yml must pin mcp-publisher's SHA-256"
    assert set(match.group(1)) != {"0"}


def test_smithery_bundle_launches_this_release(tmp_path, monkeypatch):
    # Smithery installs whatever version the bundle pins, and rejects a
    # release without tools or input schemas.
    monkeypatch.setattr(sys, "argv", ["build_smithery_bundle.py", str(tmp_path)])
    spec = importlib.util.spec_from_file_location(
        "build_smithery_bundle", ROOT / "scripts" / "build_smithery_bundle.py"
    )
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main() == 0

    with zipfile.ZipFile(tmp_path / f"maplestats-mcp-{__version__}.mcpb") as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
    assert manifest["version"] == __version__
    assert manifest["server"]["type"] == "python"
    assert manifest["server"]["mcp_config"]["args"] == [f"maplestats-mcp=={__version__}"]
    assert manifest["tools"] and all("inputSchema" in tool for tool in manifest["tools"])
