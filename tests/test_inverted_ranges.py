"""An inverted date or year range is an InvalidInput, raised before any request.

These used to come back as an empty success, which reads as "no data".
No response is mocked, so a request would fail the test instead.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import pytest

from maplestats_mcp.modules.bc_lobbyists import client as bc_lobbyists
from maplestats_mcp.modules.competition_bureau import client as competition_bureau
from maplestats_mcp.modules.cwfis import client as cwfis
from maplestats_mcp.modules.ircc.monthly import client as ircc_monthly
from maplestats_mcp.modules.ised.ip_horizons import client as ip_horizons
from maplestats_mcp.modules.openparliament import client as openparliament
from maplestats_mcp.modules.pbo import client as pbo
from maplestats_mcp.shared.errors import InvalidInput

CASES: list[tuple[str, Callable[[], Awaitable[Any]]]] = [
    (
        "competition_bureau",
        lambda: competition_bureau.search_mergers(
            concluded_from="2025-06", concluded_to="2024-01"
        ),
    ),
    ("pbo", lambda: pbo.search_information_requests(since="2025", until="2024-12")),
    (
        "ised_ip_horizons",
        lambda: ip_horizons.search_patents(filed_from=date(2025, 1, 1), filed_to=date(2024, 1, 1)),
    ),
    ("ircc_monthly", lambda: ircc_monthly.query_table("x", year_from=2025, year_to=2020)),
    ("cwfis_large_fires", lambda: cwfis.search_large_fires(year_from=2025, year_to=2020)),
    (
        "cwfis_hotspots",
        lambda: cwfis.get_hotspots(start_date="2025-07-02", end_date="2025-07-01"),
    ),
    (
        "bc_lobbyists",
        lambda: bc_lobbyists.search_registrations(date_from="2025-02-01", date_to="2025-01-01"),
    ),
    (
        "openparliament_votes",
        lambda: openparliament.search_votes(date_from="2025-02-01", date_to="2025-01-01"),
    ),
]


@pytest.mark.parametrize(("name", "call"), CASES, ids=[name for name, _ in CASES])
async def test_inverted_range_is_invalid_input(name: str, call: Callable[[], Awaitable[Any]]):
    with pytest.raises(InvalidInput, match="is after"):
        await call()
