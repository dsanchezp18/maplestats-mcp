"""Release metadata stays consistent across PyPI, the MCP Registry and the code."""

from __future__ import annotations

import json
import re
import tomllib
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
