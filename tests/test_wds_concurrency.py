"""A cold wds_get_data_from_vectors asks StatCan's independent requests together.

On 2026-11-06 the hosted /stats showed a 6.4 s median for this tool: the data,
code sets, series info and each table's metadata were requested one after
another. Here each mocked request waits, and the call must take about as long
as the longest chain (series info, then metadata), not the sum.
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx

from maplestats_mcp.modules.statcan.wds import tools

DELAY = 0.2
BASE = "https://www150.statcan.gc.ca/t1/wds/rest/"


def _ok(obj) -> list[dict]:
    return [{"status": "SUCCESS", "object": obj}]


def _data(vector_id: int, product_id: int) -> dict:
    return {
        "responseStatusCode": 0,
        "productId": product_id,
        "coordinate": "1.1.0.0.0.0.0.0.0.0",
        "vectorId": vector_id,
        "vectorDataPoint": [
            {
                "refPer": "2026-09-01",
                "value": 1.5,
                "decimals": 1,
                "scalarFactorCode": 0,
                "symbolCode": 0,
                "statusCode": 0,
                "securityLevelCode": 0,
                "releaseTime": "2026-10-09T08:30",
                "frequencyCode": 6,
            }
        ],
    }


def _info(vector_id: int, product_id: int) -> dict:
    return {
        "responseStatusCode": 0,
        "productId": product_id,
        "coordinate": "1.1.0.0.0.0.0.0.0.0",
        "vectorId": vector_id,
        "frequencyCode": 6,
        "scalarFactorCode": 0,
        "decimals": 1,
        "terminated": 0,
        "SeriesTitleEn": "A series",
        "SeriesTitleFr": "Une série",
        "memberUomCode": 239,
    }


async def test_independent_requests_run_together(httpx_mock) -> None:
    vectors = {101: 1410028701, 102: 1810000401, 103: 3610043401}

    async def respond(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(DELAY)
        method = str(request.url).removeprefix(BASE)
        if method == "getCodeSets":
            return httpx.Response(200, json={"status": "SUCCESS", "object": {}})
        body = json.loads(request.content)
        if method == "getDataFromVectorsAndLatestNPeriods":
            return httpx.Response(
                200, json=[_ok(_data(b["vectorId"], vectors[b["vectorId"]]))[0] for b in body]
            )
        if method == "getSeriesInfoFromVector":
            return httpx.Response(
                200, json=[_ok(_info(b["vectorId"], vectors[b["vectorId"]]))[0] for b in body]
            )
        if method == "getCubeMetadata":
            pid = body[0]["productId"]
            return httpx.Response(
                200,
                json=_ok({"responseStatusCode": 0, "productId": pid, "cubeTitleEn": "T"}),
            )
        return httpx.Response(404)

    httpx_mock.add_callback(respond, is_reusable=True)
    started = time.perf_counter()
    result = await tools.wds_get_data_from_vectors(vector_ids=list(vectors), latest_n=1)
    elapsed = time.perf_counter() - started
    assert len(result.series) == 3
    # Done one after another this is 6 requests (data, code sets, series info and
    # three tables), about 6 * DELAY; together it is about 2 * DELAY.
    assert elapsed < 4 * DELAY, f"took {elapsed:.2f}s"
