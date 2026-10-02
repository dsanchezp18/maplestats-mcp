"""Live smoke test for every tool of statcan/wds: calls the real Web Data
Service (not mocks), per AGENTS.md's "lesson from auditing the StatCan module".

Each of the 13 wds_ tools has at least one step, and the regressions found by
the 2026-10-02 live review are asserted against the real service: a changed
series asked for by table + coordinate never comes from another table, an
unknown table is NotFound (not a dead download link), one bad vector does not
fail a batch, and large tables come back capped.

Usage:
    uv run python scripts/smoke_test_statcan_wds.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp.modules.statcan.wds import client
from maplestats_mcp.server import mcp
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.http import new_client

CPI_PID = 18100004
CPI_VECTOR = 41690973  # Canada, all-items, in table 18-10-0004
CPI_COORDINATE = "2.2"


def check(ok: bool, label: str, detail: object = "") -> bool:
    print(f"{'OK  ' if ok else 'FAIL'}: {label}" + (f" -> {detail}" if detail != "" else ""))
    return ok


async def raises(error: type[Exception], label: str, coro) -> bool:
    try:
        await coro
    except error as exc:
        return check(True, label, str(exc)[:110])
    except Exception as exc:  # noqa: BLE001 - report any other type as a failure
        return check(False, label, f"{type(exc).__name__}: {exc}"[:160])
    return check(False, label, "no error raised")


async def main() -> int:
    ok = True

    # wds_search_cubes: topic words, every way of writing a table number,
    # real-time flag, paging with a total.
    cpi = await client.search_cubes("consumer price index", limit=5)
    ok &= check(
        cpi.returned_count == 5 and cpi.total_count > 5, "search by words, capped", cpi.total_count
    )
    for form in ("18-10-0004", "18100004", "1810000401", "326-0020"):
        found = await client.search_cubes(form)
        ok &= check(
            [c.product_id for c in found.cubes] == [CPI_PID], f"search by table number {form}"
        )
    real_time = await client.search_cubes("real-time", limit=50)
    flagged = [c for c in real_time.cubes if c.real_time]
    ok &= check(len(flagged) >= 10, "real-time tables are flagged", len(flagged))
    page = await client.search_cubes(limit=10, offset=10)
    ok &= check(
        page.total_count > 8000 and page.returned_count == 10, "inventory pages", page.total_count
    )
    ok &= check(page.provenance.limits is not None, "truncation is stated", page.provenance.limits)

    # wds_get_cube_metadata: every form of the table number, caps, unknown table.
    meta = await client.get_cube_metadata("18-10-0004-01")
    ok &= check(
        meta.product_id == CPI_PID and len(meta.dimensions) >= 2, "metadata for 18-10-0004-01"
    )
    big = await client.get_cube_metadata(98100002)
    biggest = max(len(d.members) for d in big.dimensions)
    ok &= check(
        biggest <= 100 and big.dimensions[0].member_count > 100, "large table is capped", biggest
    )
    ok &= check(big.provenance.limits is not None, "metadata truncation is stated")
    ok &= await raises(NotFound, "unknown table is NotFound", client.get_cube_metadata(99999999))

    # wds_get_series_info: both directions, the extra fields, an unknown vector.
    by_vector = await client.get_series_info_from_vector(CPI_VECTOR)
    by_coord = await client.get_series_info_from_cube_pid_coord(CPI_PID, CPI_COORDINATE)
    ok &= check(
        by_vector.vector_id == by_coord.vector_id == CPI_VECTOR, "vector <-> coordinate agree"
    )
    ok &= check(
        by_vector.series_title_en is not None and by_vector.frequency_code == 6,
        "series info keeps title and frequency",
        by_vector.series_title_en,
    )
    ok &= await raises(
        NotFound, "unknown vector is NotFound", client.get_series_info_from_vector(999999999)
    )

    # wds_get_data_from_vectors: a bad id is listed, not fatal.
    two = await client.get_data_from_vectors_and_latest_n_periods([CPI_VECTOR, 999999999], 2)
    ok &= check(
        len(two.series) == 1 and [f.vector_id for f in two.failed] == [999999999],
        "one bad vector does not fail the batch",
        two.failed,
    )

    # wds_get_data_from_cube_coord
    coord = await client.get_data_from_cube_pid_coord_and_latest_n_periods(
        CPI_PID, CPI_COORDINATE, 3
    )
    ok &= check(
        coord.vector_id == CPI_VECTOR and len(coord.observations) == 3, "latest 3 by coordinate"
    )

    # wds_get_bulk_vector_data_by_range: a bare date is accepted, a bad one is not.
    bulk = await client.get_bulk_vector_data_by_range([CPI_VECTOR], "2024-01-01", "2024-02-01")
    ok &= check(bool(bulk.series and bulk.series[0].observations), "bulk by release date range")
    ok &= await raises(
        InvalidInput,
        "bulk rejects a malformed date",
        client.get_bulk_vector_data_by_range([CPI_VECTOR], "01/01/2024", "2024-02-01"),
    )

    # wds_get_data_by_reference_period_range
    window = await client.get_data_from_vector_by_reference_period_range(
        [CPI_VECTOR], "2024-01", "2024-03"
    )
    ok &= check(
        len(window.series[0].observations) == 3,
        "reference-period range (months widened)",
        len(window.series[0].observations),
    )

    # wds_get_changed_series_list / wds_get_changed_series_data
    changed = await client.get_changed_series_list()
    ok &= check(True, "changed series today", len(changed.series))
    if changed.series:
        first = changed.series[0]
        by_vec = await client.get_changed_series_data_from_vector(first.vector_id)
        by_pid = await client.get_changed_series_data_from_cube_pid_coord(
            first.product_id, first.coordinate
        )
        ok &= check(
            by_vec.vector_id == by_pid.vector_id == first.vector_id
            and by_pid.product_id == first.product_id,
            "changed data by coordinate is the same series",
        )
    # The review's reproduction: this used to return vector 74740 of another table.
    try:
        data = await client.get_changed_series_data_from_cube_pid_coord(CPI_PID, CPI_COORDINATE)
        ok &= check(
            data.product_id == CPI_PID, "changed data is from the asked table", data.product_id
        )
    except NotFound as exc:
        ok &= check(True, "unchanged series is NotFound, not another table's series", str(exc)[:90])
    ok &= (
        await raises(
            NotFound,
            "unchanged vector is NotFound",
            client.get_changed_series_data_from_vector(CPI_VECTOR),
        )
        if not any(s.vector_id == CPI_VECTOR for s in changed.series)
        else True
    )

    # wds_get_changed_cube_list
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    cubes = await client.get_changed_cube_list(yesterday)
    ok &= check(isinstance(cubes.cubes, list), f"changed cubes {yesterday}", len(cubes.cubes))
    ok &= await raises(
        InvalidInput, "changed cubes rejects DD/MM/YYYY", client.get_changed_cube_list("16/09/2026")
    )

    # wds_get_full_table_download: a real link that answers, no link for an unknown table.
    csv = await client.get_full_table_download_csv("18-10-0004-01", "en")
    sdmx = await client.get_full_table_download_sdmx(CPI_PID)
    async with new_client(timeout=30.0, follow_redirects=True) as http:
        head = await http.head(csv.download_url)
    ok &= check(head.status_code == 200, "CSV link answers 200", csv.download_url)
    ok &= check(sdmx.download_url.startswith("https://"), "SDMX link", sdmx.download_url)
    ok &= await raises(
        NotFound, "unknown table has no download", client.get_full_table_download_csv(99999999)
    )

    # wds_get_code_sets: capped, one category, filter.
    sets = await client.get_code_sets()
    ok &= check(
        len(sets.subject) <= 100
        and sets.counts["subject"] > 100
        and sets.provenance.limits is not None,
        "code sets capped",
        sets.counts["subject"],
    )
    scalar = await client.get_code_sets(category="scalar")
    ok &= check(any(e.description_en == "thousands" for e in scalar.scalar), "scalar factor codes")

    # The same tools through the server, as a client calls them: the union
    # product_id type and the BaseModel list results must survive the schema.
    async with Client(mcp) as server:
        for name, args in (
            ("wds_search_cubes", {"query": "18-10-0004"}),
            ("wds_get_cube_metadata", {"product_id": "18-10-0004-01", "member_limit": 3}),
            ("wds_get_data_from_vectors", {"vector_ids": [CPI_VECTOR], "latest_n": 1}),
        ):
            result = await server.call_tool(
                "call_tool", {"name": name, "arguments": args}, raise_on_error=False
            )
            text = next((b.text for b in result.content if isinstance(b, TextContent)), "")
            ok &= check(not result.is_error and bool(json.loads(text)), f"server call {name}")

    print("\nSTATCAN WDS SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
