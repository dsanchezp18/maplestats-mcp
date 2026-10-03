"""Check reproduce_code's Excel (Power Query M) queries against the live sources.

No Excel runs here. For each query this script takes the URL and request
the M code sends (Web.Contents), makes the same request, and repeats in
Python the M steps that are easy to get wrong without Excel: the ZIP
central-directory reader (offsets and raw deflate), WDS's
object/vectorDataPoint nesting, SDMX GenericData's element and attribute
names, and Valet's nested {v} cells.

    uv run python scripts/verify_excel_queries.py
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
import zlib

import httpx

from maplestats_mcp.modules.reproduce import client

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MapleStats verify script)"}


def unzip_like_m(data: bytes) -> dict[str, bytes]:
    """The M UnzipFiles function, step for step."""

    def read16(offset: int) -> int:
        return struct.unpack_from("<H", data, offset)[0]

    def read32(offset: int) -> int:
        return struct.unpack_from("<I", data, offset)[0]

    directory_end = len(data) - 22
    assert read32(directory_end) == 0x06054B50, (
        "archive has a comment: EOCD is not the last 22 bytes"
    )
    count, offset = read16(directory_end + 10), read32(directory_end + 16)
    files = {}
    for _ in range(count):
        name_length = read16(offset + 28)
        name = data[offset + 46 : offset + 46 + name_length].decode("utf-8")
        method, size, local = read16(offset + 10), read32(offset + 20), read32(offset + 42)
        start = local + 30 + read16(local + 26) + read16(local + 28)
        packed = data[start : start + size]
        files[name] = zlib.decompress(packed, -15) if method == 8 else packed
        offset += 46 + name_length + read16(offset + 30) + read16(offset + 32)
    return files


def m_url(code: str) -> str:
    match = re.search(r'Web\.Contents\("((?:[^"]|"")*)"', code)
    assert match, "no Web.Contents in the query"
    return match.group(1).replace('""', '"')


async def query(tool: str, arguments: dict) -> str:
    result = await client.reproduce(tool, arguments, "excel")
    assert result.scripts, f"{tool}: no excel query ({result.notes})"
    return result.scripts[0].code


def check_table(http: httpx.Client) -> str:
    code = asyncio.run(query("wds_get_cube_metadata", {"product_id": 18100004}))
    body = http.get(m_url(code)).raise_for_status().content
    files = unzip_like_m(body)
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        assert set(files) == set(archive.namelist())
        assert all(files[n] == archive.read(n) for n in files)
    data = next(n for n in files if n.lower().endswith(".csv") and "metadata" not in n.lower())
    header = next(csv.reader(io.StringIO(files[data][:4000].decode("utf-8-sig"))))
    assert "VALUE" in header and "SCALAR_ID" in header, header
    bom = files[data].startswith(b"\xef\xbb\xbf")
    return (
        f"table ZIP {len(body):,} bytes, files {sorted(files)}, BOM={bom}, header {header[:4]}..."
    )


def check_vectors(http: httpx.Client) -> str:
    code = asyncio.run(
        query("wds_get_data_from_vectors", {"vector_ids": [41690973, 41690914], "latest_n": 3})
    )
    body = [{"vectorId": 41690973, "latestN": 3}, {"vectorId": 41690914, "latestN": 3}]
    assert 'Json.FromValue({[#"vectorId" = 41690973, #"latestN" = 3]' in code
    payload = http.post(m_url(code), json=body).raise_for_status().json()
    parent = payload[0]["object"]
    scalars = [k for k, v in parent.items() if not isinstance(v, list | dict)]
    point = parent["vectorDataPoint"][0]
    assert {"vectorId", "productId", "coordinate"} <= set(scalars)
    assert {"refPer", "value", "scalarFactorCode"} <= set(point)
    return f"WDS vectors: parent fields {scalars}, point fields {sorted(point)[:6]}..."


def check_sdmx(http: httpx.Client) -> str:
    code = asyncio.run(
        query("sdmx_get_data", {"product_id": 18100004, "key": "2.2", "last_n_observations": 3})
    )
    root = ET.fromstring(http.get(m_url(code)).raise_for_status().content)

    def local(element: ET.Element) -> str:
        return element.tag.rsplit("}", 1)[-1]

    data_set = next(child for child in root if local(child) == "DataSet")
    rows = []
    for series in (child for child in data_set if local(child) == "Series"):
        fields = {}
        for part in (child for child in series if local(child) in ("SeriesKey", "Attributes")):
            fields |= {value.get("id"): value.get("value") for value in part}
        for obs in (child for child in series if local(child) == "Obs"):
            parts = {local(child): child for child in obs}
            rows.append(
                fields
                | {
                    "TIME_PERIOD": parts["ObsDimension"].get("value"),
                    "OBS_VALUE": parts["ObsValue"].get("value"),
                }
            )
    assert rows and "SCALAR_FACTOR" in rows[0], rows[:1]
    return f"SDMX: {len(rows)} observations, first {rows[0]}"


def check_valet(http: httpx.Client) -> str:
    code = asyncio.run(query("boc_get_observations", {"series_names": ["FXUSDCAD"], "recent": 3}))
    observations = http.get(m_url(code)).raise_for_status().json()["observations"]
    first = observations[0]
    assert "d" in first and isinstance(first["FXUSDCAD"], dict) and "v" in first["FXUSDCAD"]
    return f"Valet: {first}"


def check_socrata(http: httpx.Client) -> str:
    code = asyncio.run(
        query(
            "socrata_query_dataset_rows",
            {"portal": "calgary", "dataset_id": "848s-4m4z", "limit": 3},
        )
    )
    text = http.get(m_url(code)).raise_for_status().text
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows) == 4, rows
    return f"Socrata CSV: header {rows[0][:4]}"


def main() -> int:
    checks = [check_table, check_vectors, check_sdmx, check_valet, check_socrata]
    failures = 0
    with httpx.Client(http2=True, timeout=180, follow_redirects=True, headers=_HEADERS) as http:
        for check in checks:
            try:
                print(f"ok   {check.__name__}: {check(http)}")
            except Exception as exc:  # noqa: BLE001 - report every check, then fail
                failures += 1
                print(f"FAIL {check.__name__}: {exc!r}")
    print(json.dumps({"checks": len(checks), "failures": failures}))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
