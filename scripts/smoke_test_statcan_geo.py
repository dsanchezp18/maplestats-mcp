"""Live smoke test for the statcan.geo module's client.py: calls the
real geo.statcan.gc.ca ArcGIS REST service (not mocks), per AGENTS.md's
"lesson from auditing the StatCan module". This host is confirmed live
to intermittently 500 on an otherwise-valid request (a load-balanced
backend with some unhealthy nodes) -- shared/http.py's own 3-attempt
retry already covers this, so no extra retry logic is added here.

Usage:
    uv run python scripts/smoke_test_statcan_geo.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.statcan.geo import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def main() -> int:
    ok = True

    services = await client.list_services("2021")
    print(f"OK: list_services('2021') -> {len(services.services)} services")
    ok &= len(services.services) >= 8  # confirmed live: 10
    names = [s.name for s in services.services]
    ok &= any("Cartographic_boundary_files" in n for n in names)

    layer = await client.get_layer_detail("2021", "Cartographic_boundary_files", 9)
    print(f"OK: get_layer_detail(...) -> {layer.name}, {len(layer.fields)} fields")
    ok &= layer.geometry_type == "esriGeometryPolygon"
    ok &= layer.max_record_count is not None and layer.max_record_count > 0
    ok &= layer.spatial_reference_wkid == 3347
    field_names = [f.name for f in layer.fields]
    ok &= "CSDNAME" in field_names and "DGUID" in field_names

    toronto = await client.query_layer_features(
        "2021", "Cartographic_boundary_files", 9, where="CSDNAME='Toronto'"
    )
    print(f"OK: query_layer(CSDNAME='Toronto') -> {toronto.returned_count} feature(s)")
    ok &= toronto.returned_count == 1
    ok &= toronto.features[0].attributes.get("DGUID") == "2021A00053520005"
    ok &= toronto.features[0].geometry is None

    with_geom = await client.query_layer_features(
        "2021", "Cartographic_boundary_files", 9, where="CSDNAME='Toronto'", return_geometry=True
    )
    print(
        f"OK: query_layer(..., return_geometry=True) -> geometry present={with_geom.features[0].geometry is not None}"
    )
    geometry = with_geom.features[0].geometry
    ok &= geometry is not None
    ok &= geometry is not None and geometry["type"] in ("Polygon", "MultiPolygon")

    broad = await client.query_layer_features(
        "2021",
        "Cartographic_boundary_files",
        12,
        where="PRUID='35'",
        out_fields="DAUID",
        result_record_count=50,
    )
    print(f"OK: query_layer(DA, PRUID='35', record_count=50) -> {broad.returned_count} feature(s)")
    ok &= broad.returned_count == 50
    ok &= broad.exceeded_transfer_limit is True

    try:
        await client.get_layer_detail("2021", "Not_A_Real_Service", 9)
        print("FAIL: expected NotFound for a bogus service name")
        ok = False
    except NotFound:
        print("OK: bogus service name raises NotFound as expected")

    try:
        await client.query_layer_features(
            "2021", "Cartographic_boundary_files", 9, where="NOTAFIELD='x'"
        )
        print("FAIL: expected InvalidInput for a malformed where clause")
        ok = False
    except InvalidInput:
        print("OK: malformed where clause raises InvalidInput as expected")

    print("\nSTATCAN GEO SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
