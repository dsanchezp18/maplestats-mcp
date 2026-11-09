"""Live smoke test for the statcan.surveys module's client.py: calls the
real survey directory and IMDB (not mocks), per AGENTS.md's "lesson from
auditing the StatCan module".

The survey directory (/n1/{lang}/type/surveys) has answered 404 or looped on
redirects since 2026-10-29; the client raises UpstreamUnavailable for it. That
part is then reported as SKIPPED, and the IMDB, RDC and RTRA checks, which read
other pages, still run against survey 5108 (Aboriginal Children's Survey).

Usage:
    uv run python scripts/smoke_test_statcan_surveys.py
"""

from __future__ import annotations

import asyncio
import sys

from _smoke_common import skip_outage, verdict

from maplestats_mcp.modules.statcan.surveys import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable


async def main() -> int:
    ok = True

    survey_id = 5108  # Aboriginal Children's Survey, confirmed live
    try:
        all_surveys = await client.search_surveys()
        print(f"OK: search_surveys() -> {all_surveys.total_matched} surveys")
        ok &= all_surveys.total_matched > 800  # confirmed live: ~899

        result = await client.search_surveys("aboriginal children")
        print(f"OK: search_surveys('aboriginal children') -> {result.total_matched}")
        ok &= result.total_matched > 0
        survey = next(s for s in result.surveys if s.survey_id == survey_id)
        print("  found:", survey.model_dump())
    except UpstreamUnavailable as exc:
        skip_outage("StatCan's survey directory", exc, rest_runs=True)

    metadata = await client.get_survey_metadata(survey_id)
    print(f"OK: get_survey_metadata({survey_id}) -> {metadata.name}")
    ok &= bool(metadata.name)
    ok &= metadata.status is not None
    ok &= metadata.frequency is not None
    ok &= bool(metadata.description)
    ok &= len(metadata.subjects) > 0
    # A record with no methodology section parsed means IMDB's layout changed.
    sections = metadata.methodology.model_dump()
    missing = [name for name, text in sections.items() if not text]
    print(f"  methodology sections: {len(sections) - len(missing)} of {len(sections)}")
    ok &= len(missing) < len(sections)
    print("  sample:", metadata.model_dump())

    sampling = await client.get_survey_metadata(survey_id, section="sampling")
    print(f"OK: get_survey_metadata({survey_id}, section=sampling) -> {sampling.survey_design}")
    ok &= bool(sampling.methodology.sampling) and not sampling.trimmed_sections

    fr = await client.get_survey_metadata(survey_id, lang="fr")
    print(f"OK: get_survey_metadata({survey_id}, lang=fr) -> {fr.name}")
    ok &= bool(fr.name)
    ok &= fr.status is not None

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

    rdc = await client.search_rdc_holdings()
    print(f"OK: search_rdc_holdings() -> {rdc.total_matched} holdings")
    ok &= rdc.total_matched > 300  # confirmed live 2026-10-02: 352
    cchs = await client.search_rdc_holdings("community health survey", limit=3)
    ok &= cchs.total_matched > 0
    print("  sample:", cchs.holdings[0].model_dump())
    rdc_fr = await client.search_rdc_holdings("enquête", lang="fr", limit=2)
    print(f"OK: search_rdc_holdings('enquête', fr) -> {rdc_fr.total_matched}")
    ok &= rdc_fr.total_matched > 0

    rtra = await client.search_rtra_datasets()
    print(f"OK: search_rtra_datasets() -> {rtra.total_matched} datasets")
    ok &= rtra.total_matched > 300  # confirmed live 2026-10-02: 357
    ok &= all(d.tag_name for d in rtra.datasets)
    cchs_rtra = await client.search_rtra_datasets("canadian community health", limit=2)
    ok &= cchs_rtra.total_matched > 20
    ok &= any(
        link.sdds_id or link.instance_id for d in cchs_rtra.datasets for link in d.survey_links
    )
    print("  sample:", cchs_rtra.datasets[0].model_dump(exclude={"survey_links"}))
    rtra_fr = await client.search_rtra_datasets("décès", lang="fr", limit=2)
    print(f"OK: search_rtra_datasets('décès', fr) -> {rtra_fr.total_matched}")
    ok &= rtra_fr.total_matched > 0

    return verdict("STATCAN SURVEYS", ok)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
