"""Live smoke test for the statcan.surveys module's client.py: calls the
real survey directory and IMDB (not mocks), per AGENTS.md's "lesson from
auditing the StatCan module".

Usage:
    uv run python scripts/smoke_test_statcan_surveys.py
"""

from __future__ import annotations

import asyncio
import sys

from maple_data_mcp.modules.statcan.surveys import client
from maple_data_mcp.shared.errors import InvalidInput, NotFound


async def main() -> int:
    ok = True

    all_surveys = await client.search_surveys()
    print(f"OK: search_surveys() -> {all_surveys.total_matched} surveys")
    ok &= all_surveys.total_matched > 800  # confirmed live: ~899

    result = await client.search_surveys("aboriginal children")
    print(f"OK: search_surveys('aboriginal children') -> {result.total_matched}")
    ok &= result.total_matched > 0
    survey = next(s for s in result.surveys if s.survey_id == 5108)
    print("  found:", survey.model_dump())

    metadata = await client.get_survey_metadata(survey.survey_id)
    print(f"OK: get_survey_metadata({survey.survey_id}) -> {metadata.name}")
    ok &= bool(metadata.name)
    ok &= metadata.status is not None
    ok &= metadata.frequency is not None
    ok &= bool(metadata.description)
    ok &= len(metadata.subjects) > 0
    print("  sample:", metadata.model_dump())

    fr = await client.get_survey_metadata(survey.survey_id, lang="fr")
    print(f"OK: get_survey_metadata({survey.survey_id}, lang=fr) -> {fr.name}")
    ok &= bool(fr.name)

    try:
        await client.get_survey_metadata(999999999)
        print("FAIL: expected NotFound for a bogus survey id")
        ok = False
    except NotFound:
        print("OK: bogus survey id raises NotFound as expected")

    try:
        await client.search_surveys(lang="de")
        print("FAIL: expected InvalidInput for a bogus lang")
        ok = False
    except InvalidInput:
        print("OK: bogus lang raises InvalidInput as expected")

    print("\nSTATCAN SURVEYS SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
