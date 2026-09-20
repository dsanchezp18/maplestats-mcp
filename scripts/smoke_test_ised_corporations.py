"""Live smoke test for Corporations Canada's federal corporation lookup API."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable
from typing import Any

from maple_data_mcp.modules.ised.corporations import client
from maple_data_mcp.shared.errors import InvalidInput, NotFound

# A long-standing, real federal corporation (Abbotsford Chamber of Commerce),
# used only because its id is stable enough to check against repeatedly.
_KNOWN_CORPORATION_ID = "1007"


async def _check(label: str, awaitable: Awaitable[Any]) -> Any:
    try:
        result = await awaitable
        print(f"OK: {label} -> {type(result).__name__}")
        return result
    except Exception as exc:
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        raise


async def main() -> int:
    detail = await _check("get_corporation(by id)", client.get_corporation(_KNOWN_CORPORATION_ID))
    if not detail.names:
        print("FAIL: corporation has no names")
        return 1
    if not detail.business_number:
        print("FAIL: corporation has no business number")
        return 1

    by_bn = await _check(
        "get_corporation(by business number)", client.get_corporation(detail.business_number)
    )
    if by_bn.corporation_id != detail.corporation_id:
        print("FAIL: business-number lookup returned a different corporation")
        return 1

    fr_detail = await _check(
        "get_corporation(lang=fr)", client.get_corporation(_KNOWN_CORPORATION_ID, lang="fr")
    )
    if not fr_detail.names:
        print("FAIL: French-language lookup has no names")
        return 1

    try:
        await client.get_corporation("999999999999")
    except NotFound:
        print("OK: unmatched id raises NotFound")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: unmatched id raised {type(exc).__name__}: {exc}")
        return 1

    try:
        await client.get_corporation("not-a-number")
    except InvalidInput:
        print("OK: non-numeric input raises InvalidInput")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: non-numeric input raised {type(exc).__name__}: {exc}")
        return 1

    print(f"Corporation {detail.corporation_id}: status={detail.status!r}, act={detail.act!r}")
    print("ISED-CORPORATIONS SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
