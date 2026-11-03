"""Live smoke test for IRCC's processing-times files (ircc_processing_).

uv run python scripts/smoke_test_ircc_processing.py
"""

from __future__ import annotations

import asyncio
import sys

from _smoke_common import skip_outage

from maplestats_mcp.modules.ircc.processing import client
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)


async def main() -> int:
    ok = True
    try:
        # Checked 2026-11-03: 57 types across the four files, none unlabelled.
        listing = await client.list_application_types()
        unknown = [t.type_id for t in listing.types if t.category == "other"]
        print(f"OK: {listing.returned_count} application types; unlabelled: {unknown}")
        ok &= listing.returned_count >= 50 and not unknown
        ok &= all(t.last_updated_date is not None for t in listing.types)

        inside = await client.get_processing_time("work_extension")
        print(
            f"OK: work permit from inside Canada -> {inside.time and inside.time.text} "
            f"(IRCC last updated {inside.application_type.last_updated})"
        )
        ok &= inside.time is not None and inside.time.status == "available"

        estimate = await client.get_processing_time("WP-EXT")
        print(
            f"OK: WP-EXT estimate -> {estimate.time and estimate.time.text}, "
            f"{estimate.people_waiting} waiting"
        )
        ok &= estimate.application_type.basis == "forward_looking"
        ok &= (estimate.people_waiting or 0) > 0

        cec = await client.get_processing_time("cec", lang="fr")
        print(f"OK: CEC FR -> {cec.time and cec.time.text} ({cec.application_type.last_updated})")
        ok &= cec.time is not None and cec.time.unit == "months"
        ok &= "&" not in (cec.application_type.last_updated or "")

        india = await client.get_processing_time("visitor-outside-canada", country="India")
        print(f"OK: visitor visa from India -> {india.countries[0].time.text}")
        ok &= india.countries[0].country_code == "IN"

        study = await client.get_processing_time("study")
        published = sum(c.time.status == "available" for c in study.countries)
        print(f"OK: study permit -> {study.returned_count} countries, {published} with a time")
        ok &= study.returned_count >= 200 and published >= 50

        refugees = await client.get_processing_time("refugees_private", country="IN")
        ok &= {c.component for c in refugees.countries} == {"sponsor", "refugee"}

        for label, call, exc_type in (
            ("ambiguous type", client.get_processing_time("work permit"), InvalidInput),
            ("unknown type", client.get_processing_time("zzz"), NotFound),
        ):
            try:
                await call
                print(f"FAIL: {label} did not raise")
                ok = False
            except exc_type as exc:
                print(f"OK: {label} -> {type(exc).__name__}")
    except (UpstreamError, UpstreamUnavailable) as exc:
        skip_outage("canada.ca", exc)

    print("\nIRCC PROCESSING SMOKE TEST PASSED" if ok else "\nIRCC PROCESSING SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
