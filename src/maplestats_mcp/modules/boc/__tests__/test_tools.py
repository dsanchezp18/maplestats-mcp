"""Tests for the boc module's tools.py: docstring discoverability
contract (Use for:/Keywords:/Mots-clés : lines, >=8 keywords each) that
BM25SearchTransform relies on, plus a thin pass-through check for each
tool against a mocked client function."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from maplestats_mcp.modules.boc import tools
from maplestats_mcp.modules.boc.schemas import SeriesDetail
from maplestats_mcp.shared.models import Provenance

ALL_TOOLS = [
    tools.boc_search_series,
    tools.boc_list_series,
    tools.boc_search_groups,
    tools.boc_list_groups,
    tools.boc_get_series,
    tools.boc_get_group,
    tools.boc_get_observations,
    tools.boc_get_group_observations,
]


@pytest.mark.parametrize("tool_fn", ALL_TOOLS, ids=lambda f: f.__name__)
def test_docstring_has_use_for_and_keywords(tool_fn):
    doc = tool_fn.__doc__ or ""
    assert "Use for:" in doc, f"{tool_fn.__name__} is missing a 'Use for:' line"
    assert "Keywords:" in doc, f"{tool_fn.__name__} is missing a 'Keywords:' line"
    assert "Mots-clés :" in doc, f"{tool_fn.__name__} is missing a 'Mots-clés :' line"
    keywords_line = doc.split("Keywords:")[1].split("Mots-clés :")[0]
    keywords = [k.strip() for k in keywords_line.replace(".", "").split(",") if k.strip()]
    assert len(keywords) >= 8, f"{tool_fn.__name__} has only {len(keywords)} keywords"
    mots_cles_line = doc.split("Mots-clés :")[1]
    mots_cles = [k.strip() for k in mots_cles_line.replace(".", "").split(",") if k.strip()]
    assert len(mots_cles) >= 8, f"{tool_fn.__name__} has only {len(mots_cles)} mots-clés"


@pytest.mark.parametrize("tool_fn", ALL_TOOLS, ids=lambda f: f.__name__)
def test_tool_name_has_boc_prefix(tool_fn):
    assert tool_fn.__name__.startswith("boc_")


async def test_boc_get_series_delegates_to_client(monkeypatch):
    fake_result = SeriesDetail(
        name="FXUSDCAD",
        label="USD/CAD",
        description="Daily average exchange rate",
        provenance=Provenance(
            source="boc",
            url="https://example.invalid",
            queried_at=datetime.now(UTC),
            cached=False,
            schema_name="boc.SeriesDetail",
        ),
    )
    mock_get_series = AsyncMock(return_value=fake_result)
    monkeypatch.setattr(tools.client, "get_series", mock_get_series)

    result = await tools.boc_get_series("FXUSDCAD")

    mock_get_series.assert_awaited_once_with("FXUSDCAD")
    assert result is fake_result
