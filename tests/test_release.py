"""Release metadata stays consistent across PyPI, the MCP Registry and the code."""

from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path

import yaml

from maplestats_mcp import __version__

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


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


def _workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _steps(workflow: dict) -> list[dict]:
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


def test_every_action_is_pinned_by_commit_sha():
    # A tag can be moved to different code; a full commit SHA cannot.
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for step in _steps(_workflow(path)):
            uses = step.get("uses")
            if uses and not uses.startswith("./"):
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", uses), (path.name, uses)


def test_every_workflow_sets_token_permissions():
    # Without a top-level block a workflow gets the repository's default token scopes.
    for path in sorted(WORKFLOWS.glob("*.yml")):
        assert "permissions" in _workflow(path), path.name


def test_setup_uv_matches_the_dockerfile_pin():
    pins = {
        name: re.search(r"uv==([0-9.]+)", (ROOT / name).read_text(encoding="utf-8"))
        for name in ("Dockerfile", "chat/Dockerfile")
    }
    assert all(pins.values()), pins
    versions = {match.group(1) for match in pins.values() if match}
    assert len(versions) == 1, "the two Dockerfiles must pin the same uv"
    seen = 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for step in _steps(_workflow(path)):
            if str(step.get("uses", "")).startswith("astral-sh/setup-uv@"):
                seen += 1
                assert str(step["with"].get("version")) in versions, path.name
    assert seen > 0


def test_ci_runs_the_r_and_julia_reproduce_tests():
    # tests/test_reproduce*.py skip when R, Julia or one of their packages is
    # missing, so without these steps a regression in the generated scripts
    # merges green.
    steps = _steps(_workflow(WORKFLOWS / "ci.yml"))
    gated = [step for step in steps if step.get("if") == "matrix.python-version == '3.12'"]
    assert any(str(step.get("uses", "")).startswith("r-lib/actions/setup-r@") for step in gated)
    commands = " ".join(str(step.get("run", "")) for step in gated)
    assert "julia -e" in commands and "Rscript -e" in commands
    source = ast.parse((ROOT / "tests" / "test_reproduce_cfia.py").read_text(encoding="utf-8"))
    probed = next(
        ast.literal_eval(node.value)
        for node in source.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_R_SCRIPT_PACKAGES"
            for target in node.targets
        )
    )
    # purrr is loaded by the generated scripts and jsonlite by test_reproduce.py,
    # though neither is in the tests' own skip probes.
    for package in (*probed, "purrr", "jsonlite"):
        assert f'"{package}"' in commands, f"R package {package} is not installed in CI"
    for package in ("Cascadia", "DataFrames", "Gumbo", "JSON3", "TidierData"):
        assert f'"{package}"' in commands, f"Julia package {package} is not installed in CI"


def test_server_json_lists_the_hosted_endpoint():
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    assert server["remotes"] == [
        {"type": "streamable-http", "url": "https://maplestats-mcp.onrender.com/mcp"}
    ]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert server["remotes"][0]["url"] in readme
