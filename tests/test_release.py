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
    # The r_julia tests skip when R, Julia or one of their packages is
    # missing, so without the r-julia job (and MAPLE_REQUIRE_R_JULIA, which
    # fails such a skip) a regression in the generated scripts merges green.
    jobs = _workflow(WORKFLOWS / "ci.yml")["jobs"]
    steps = jobs["r-julia"]["steps"]
    assert any(str(step.get("uses", "")).startswith("r-lib/actions/setup-r@") for step in steps)
    commands = " ".join(str(step.get("run", "")) for step in steps)
    assert "julia -e" in commands and "Rscript -e" in commands
    pytest_step = next(step for step in steps if "pytest" in str(step.get("run", "")))
    assert "-m r_julia" in pytest_step["run"]
    assert pytest_step["env"]["MAPLE_REQUIRE_R_JULIA"] == "1"
    check = " ".join(str(step.get("run", "")) for step in jobs["check"]["steps"])
    assert '-m "not r_julia"' in check
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
    r_packages = (ROOT / ".github" / "ci" / "r-packages.txt").read_text(encoding="utf-8").split()
    julia_packages = (ROOT / ".github" / "ci" / "julia-packages.txt").read_text(encoding="utf-8")
    # purrr is loaded by the generated scripts and jsonlite by test_reproduce.py,
    # though neither is in the tests' own skip probes.
    for package in (*probed, "purrr", "jsonlite"):
        assert package in r_packages, f"R package {package} is not installed in CI"
    for package in ("Cascadia", "DataFrames", "Gumbo", "JSON3", "TidierData"):
        assert package in julia_packages.split(), f"Julia package {package} is not installed in CI"


def test_tests_that_run_r_or_julia_are_marked():
    # An unmarked test that starts R or Julia would run in the check jobs,
    # which have neither, and skip there without failing.
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not node.name.startswith("test_"):
                continue
            body = ast.get_source_segment(text, node) or ""
            if not re.search(r'shutil\.which\([^)]*"(Rscript|julia)"', body):
                continue
            marks = {ast.unparse(decorator) for decorator in node.decorator_list}
            assert "pytest.mark.r_julia" in marks, (
                f"{path.name}::{node.name} needs @pytest.mark.r_julia"
            )


def test_server_json_lists_the_hosted_endpoint():
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    assert server["remotes"] == [
        {"type": "streamable-http", "url": "https://maplestats-mcp.onrender.com/mcp"}
    ]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert server["remotes"][0]["url"] in readme
