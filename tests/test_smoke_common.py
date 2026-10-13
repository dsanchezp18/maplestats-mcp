"""The smoke scripts skip an upstream outage but never a regression."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from _smoke_common import (  # pyright: ignore[reportMissingImports]
    is_upstream_outage,
    skip_outage,
)

from maplestats_mcp.shared.errors import UpstreamError, UpstreamUnavailable


def test_outages_are_timeouts_network_failures_and_5xx() -> None:
    assert is_upstream_outage(UpstreamUnavailable("timed out"))
    assert is_upstream_outage(UpstreamError("x returned HTTP 503: down"))
    assert not is_upstream_outage(UpstreamError("x returned HTTP 404: gone"))
    assert not is_upstream_outage(UpstreamError("the response shape changed"))
    assert not is_upstream_outage(ValueError("not an upstream error"))


def test_an_outage_is_reported_and_the_caller_goes_on_to_its_verdict(capsys) -> None:
    skip_outage("the source", UpstreamError("x returned HTTP 502: bad gateway"))
    assert "SKIP: the source unavailable" in capsys.readouterr().out


def test_anything_else_is_raised_again() -> None:
    with pytest.raises(UpstreamError, match="HTTP 404"):
        skip_outage("the source", UpstreamError("x returned HTTP 404: gone"))
