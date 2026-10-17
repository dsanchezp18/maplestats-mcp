"""Release metadata stays consistent across PyPI, the MCP Registry and the code."""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
import tomllib
import zipfile
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


def test_smithery_cli_is_installed_from_a_lockfile():
    # The publish step holds SMITHERY_API_KEY, so the CLI must come from a lockfile
    # whose hashes npm checks, not from `npx -y` resolving a version at run time.
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert "npx" not in release
    assert "npm ci --ignore-scripts --prefix .github/smithery" in release
    assert ".github/smithery/node_modules/.bin/smithery" in release
    folder = ROOT / ".github" / "smithery"
    package = json.loads((folder / "package.json").read_text(encoding="utf-8"))
    version = package["dependencies"]["@smithery/cli"]
    assert re.fullmatch(r"[0-9]+[.][0-9]+[.][0-9]+", version), "pin an exact version"
    lock = json.loads((folder / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["packages"]["node_modules/@smithery/cli"]["version"] == version
    for name, entry in lock["packages"].items():
        if name:
            assert entry["integrity"].startswith("sha512-"), name


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
