"""Live smoke test for NRCan's National Burned Area Composite (NBAC) WFS client."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable
from typing import Any

from maple_data_mcp.modules.nrcan_nbac import client
from maple_data_mcp.shared.errors import InvalidInput


async def _check(label: str, awaitable: Awaitable[Any]) -> Any:
    try:
        result = await awaitable
        print(f"OK: {label} -> {type(result).__name__}")
        return result
    except Exception as exc:
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        raise


async def main() -> int:
    result = await _check(
        "query_fires(BC 2017-2024)",
        client.query_fires(
            cql_filter="admin_area = 'BC' AND year >= 2017 AND year <= 2024", limit=5
        ),
    )
    if not result.fires:
        print("FAIL: no BC fires returned for 2017-2024")
        return 1
    if result.total_matched < 100:
        print(f"FAIL: suspiciously low total_matched ({result.total_matched}) for BC 2017-2024")
        return 1

    fire = result.fires[0]
    if fire.admin_area != "BC":
        print(f"FAIL: filtered query returned admin_area={fire.admin_area!r}, expected BC")
        return 1
    if fire.geometry is not None:
        print("FAIL: geometry present despite include_geometry=False")
        return 1

    with_geom = await _check(
        "query_fires(include_geometry=True)",
        client.query_fires(
            cql_filter="admin_area = 'BC' AND year = 2021", include_geometry=True, limit=1
        ),
    )
    if not with_geom.fires or with_geom.fires[0].geometry is None:
        print("FAIL: include_geometry=True returned no geometry")
        return 1

    try:
        await client.query_fires(cql_filter="garbage===")
    except InvalidInput:
        print("OK: malformed CQL_FILTER raises InvalidInput")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: malformed CQL_FILTER raised {type(exc).__name__}: {exc}")
        return 1

    try:
        await client.query_fires(limit=0)
    except InvalidInput:
        print("OK: limit=0 raises InvalidInput")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: limit=0 raised {type(exc).__name__}: {exc}")
        return 1

    print(f"BC fires 2017-2024: {result.total_matched} total matched")
    print("NRCAN-NBAC SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
