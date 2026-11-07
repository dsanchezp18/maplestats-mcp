"""One call against the hosted server. Runs only with MAPLESTATS_LIVE=1."""

from __future__ import annotations

import os

import pytest

from maplestats import Client

pytestmark = pytest.mark.skipif(
    os.environ.get("MAPLESTATS_LIVE") != "1", reason="set MAPLESTATS_LIVE=1"
)


def test_live_search_and_get_data() -> None:
    with Client() as client:
        found = client.search_tools("bank of canada exchange rate")
        assert found["name"].str.starts_with("boc_").any()
        result = client.get_data(
            "boc_get_observations", series_names=["FXUSDCAD"], recent=2
        )
    assert result.data.height == 2
    assert "values_fxusdcad" in result.data.columns
    assert result.provenance["source"] == "boc"
