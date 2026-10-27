"""Every WDS observation call also reads getCodeSets (cached) to decode the
status, symbol and security-level codes. Tests that mock HTTP get a small
live-shaped answer for it, registered as optional so tests that never read
observations are unaffected."""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.wds import constants

# A subset of the live getCodeSets answer (2026-10-27), field names and the
# string-typed symbolCode/statusCode as sent.
CODE_SETS = {
    "status": "SUCCESS",
    "object": {
        "scalar": [
            {"scalarFactorCode": 0, "scalarFactorDescEn": "units", "scalarFactorDescFr": "unités"},
            {
                "scalarFactorCode": 6,
                "scalarFactorDescEn": "millions",
                "scalarFactorDescFr": "millions",
            },
        ],
        "frequency": [
            {"frequencyCode": 6, "frequencyDescEn": "Monthly", "frequencyDescFr": "Mensuelle"}
        ],
        "symbol": [
            {"symbolCode": "0", "symbolDescEn": "none", "symbolDescFr": "aucun"},
            {"symbolCode": "1", "symbolDescEn": "preliminary", "symbolDescFr": "provisoire"},
        ],
        "status": [
            {"statusCode": "0", "statusDescEn": "normal", "statusDescFr": "normal"},
            {
                "statusCode": "1",
                "statusDescEn": "not available for a specific reference period",
                "statusDescFr": "indisponible pour une période de référence précise",
            },
            {
                "statusCode": "7",
                "statusDescEn": "use with caution",
                "statusDescFr": "à utiliser avec prudence",
            },
            {
                "statusCode": "8",
                "statusDescEn": "too unreliable to be published",
                "statusDescFr": "trop peu fiable pour être publié",
            },
        ],
        "uom": [
            {"memberUomCode": 17, "memberUomEn": "2002=100", "memberUomFr": "2002=100"},
            {"memberUomCode": 81, "memberUomEn": "Dollars", "memberUomFr": "Dollars"},
            {"memberUomCode": 239, "memberUomEn": "Percent", "memberUomFr": "Pourcent"},
        ],
        "securityLevel": [
            {
                "securityLevelCode": 0,
                "securityLevelDescEn": "public",
                "securityLevelDescFr": "public",
            },
            {
                "securityLevelCode": 1,
                "securityLevelDescEn": (
                    "suppressed to meet the confidentiality requirements of the Statistics Act"
                ),
                "securityLevelDescFr": (
                    "confidentiel en vertu des dispositions de la Loi sur la statistique"
                ),
            },
        ],
    },
}


@pytest.fixture(autouse=True)
def _code_sets(request: pytest.FixtureRequest) -> None:
    # Tests of getCodeSets itself register their own answer.
    if "httpx_mock" not in request.fixturenames or "code_sets" in request.node.name:
        return
    httpx_mock = request.getfixturevalue("httpx_mock")
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}getCodeSets",
        json=CODE_SETS,
        is_optional=True,
        is_reusable=True,
    )
