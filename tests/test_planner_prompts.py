"""The cross-source workflow prompts name only tools that exist, in both languages."""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest

import maplestats_mcp
from maplestats_mcp.modules.planner import prompts

CATALOGUE = Path(maplestats_mcp.__file__).parent / "tool_catalogue.json"
# Tools the server adds itself rather than a module (the search transform's two).
META_TOOLS = {"search_tools", "call_tool"}

PROMPTS = {
    "labour_market_snapshot": {"province": "Alberta"},
    "refresh_with_latest_release": {"subject": "the CPI"},
    "housing_affordability_scan": {"place": "Calgary"},
    "inflation_check": {"as_of": "2025-03-01"},
    "compare_province_with_peers": {"province": "Manitoba", "indicator": "unemployment"},
    "find_and_cite_dataset": {"topic": "food insecurity"},
}

# A call written as name(...): every tool a prompt tells the assistant to run.
_CALL = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\(")
_WORD = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def _tools() -> set[str]:
    catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    names = {tool["name"] for entry in catalogue["modules"].values() for tool in entry["tools"]}
    return names | META_TOOLS


def _render(name: str, lang: str) -> str:
    return getattr(prompts, name)(**PROMPTS[name], lang=lang)


def test_every_prompt_is_covered():
    defined = {
        name
        for name, fn in inspect.getmembers(prompts, inspect.isfunction)
        if fn.__module__ == prompts.__name__ and not name.startswith("_")
    }
    assert defined == set(PROMPTS)


@pytest.mark.parametrize("name", PROMPTS)
@pytest.mark.parametrize("lang", ["en", "fr"])
def test_prompt_names_only_real_tools(name, lang):
    tools = _tools()
    text = _render(name, lang)
    called = set(_CALL.findall(text))
    assert called, "a workflow prompt should name the tools to call"
    assert called <= tools, sorted(called - tools)
    # A tool named without parentheses must exist too. Its family prefix (wds,
    # statcan, boc...) tells it apart from an argument name such as product_id.
    prefixes = {tool.split("_")[0] for tool in tools}
    mentioned = {word for word in _WORD.findall(text) if word.split("_")[0] in prefixes}
    assert mentioned <= tools | {"build_sdmx_or_key"}, sorted(mentioned - tools)


@pytest.mark.parametrize("name", PROMPTS)
def test_prompt_follows_lang_and_asks_for_provenance_and_caveats(name):
    english, french = _render(name, "en"), _render(name, "fr")
    assert english != french
    for text in (english, french):
        assert "provenance.caveats" in text
        assert "provenance.source" in text and "provenance.licence" in text
    assert "Enfin, pour chaque chiffre" in french and "Finally" not in french


def test_tool_check_catches_a_missing_tool():
    assert "wds_get_everything" not in _tools()
    assert _CALL.findall("call wds_get_everything(product_id=1)") == ["wds_get_everything"]


def test_labour_prompt_warns_about_lfs_and_seph():
    text = _render("labour_market_snapshot", "en")
    assert "14-10-0287" in text and "14-10-0223" in text
    assert "Never add or compare their employment levels" in text
