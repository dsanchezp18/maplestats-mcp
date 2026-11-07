"""The ChatGPT app directory package in distribution/chatgpt/ meets OpenAI's limits.

Limits from developers.openai.com/plugins/deploy/submission (read 2026-11-07).
The live check of the test cases is distribution/chatgpt/check_test_cases.py.
"""

from __future__ import annotations

import importlib.util
import json
import struct
import zipfile
from pathlib import Path

from maplestats_mcp import __version__

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "distribution" / "chatgpt"
PLUGIN = json.loads((PACKAGE / "plugin.json").read_text(encoding="utf-8"))
OPENAI = PLUGIN["extensions"]["com.openai"]
INTERFACE = OPENAI["interface"]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PACKAGE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_listing_fields_fit_the_limits():
    assert len(INTERFACE["displayName"]) <= 30
    assert len(INTERFACE["shortDescription"]) <= 30
    assert len(INTERFACE["longDescription"]) <= 4000
    assert len(INTERFACE["developerName"]) <= 80
    assert len(PLUGIN["description"]) <= 4000
    assert INTERFACE["category"]
    prompts = INTERFACE["defaultPrompt"]
    assert len(prompts) <= 3 and len(set(prompts)) == len(prompts)
    assert all(len(p) <= 128 and "@" not in p for p in prompts)


def test_listing_urls_are_https_and_on_the_site():
    for key in ("websiteURL", "supportURL", "privacyPolicyURL", "termsOfServiceURL"):
        assert INTERFACE[key].startswith("https://"), key
    for key in ("privacyPolicyURL", "termsOfServiceURL"):
        page = INTERFACE[key].rsplit("/", 1)[-1]
        assert (ROOT / "site" / page).exists(), f"{key}: site/{page} is missing"


def test_exactly_five_positive_and_three_negative_cases():
    cases = OPENAI["review"]["test_cases"]
    assert len(cases["positive"]) == 5
    assert len(cases["negative"]) == 3
    for case in cases["positive"]:
        assert case["description"] and case["prompt"]
        assert case["tools_triggered"] and case["expected_behavior"]
        tools = {t.strip() for t in case["tools_triggered"].split(",")}
        # The hosted server lists only these three; data tools run through call_tool.
        assert tools <= {"search_tools", "call_tool", "plan_query"}, tools
    for case in cases["negative"]:
        assert case["description"] and case["prompt"]


def test_checker_covers_every_case_in_order():
    checker = _load("check_test_cases")
    cases = OPENAI["review"]["test_cases"]
    assert len(checker.POSITIVE) == len(cases["positive"])
    assert len(checker.NEGATIVE) == len(cases["negative"])


def test_mcp_json_points_at_the_hosted_server_without_auth():
    servers = json.loads((PACKAGE / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert len(servers) == 1
    (server,) = servers.values()
    assert server["type"] == "streamable-http"
    assert server["url"] == "https://mcp.maplestats.danielstats.io/mcp"
    assert server["extensions"]["com.openai"]["auth"]["type"] == "none"
    assert "headers" not in server


def test_zip_layout(tmp_path):
    target = _load("build_zip").build("https://example.com/demo", out_dir=tmp_path)
    with zipfile.ZipFile(target) as archive:
        assert sorted(archive.namelist()) == ["assets/logo.png", "mcp.json", "plugin.json"]
        manifest = json.loads(archive.read("plugin.json"))
        logo = archive.read("assets/logo.png")
    assert manifest["version"] == __version__
    assert manifest["extensions"]["com.openai"]["review"]["demo_recording_url"] == (
        "https://example.com/demo"
    )
    assert manifest["extensions"]["com.openai"]["interface"]["logo"] == "./assets/logo.png"
    width, height = struct.unpack(">II", logo[16:24])
    assert width == height >= 48 and len(logo) <= 5 * 1024 * 1024
