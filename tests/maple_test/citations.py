"""Check the identifiers an answer cites against the publishers, not against the answer key.

The answer key names one table and vector per figure, but the same number is often
published in more than one place: average weekly earnings sit in 14-10-0222 and
14-10-0223, CPI-trim in StatCan table 18-10-0256 and in the Bank of Canada's CPI_TRIM.
Grading citations only against the key counted those as misses (MapleStats' 57% vector
coverage in the first Maple Test run was mostly that). This module asks the sources:

- does each cited StatCan vector, table and Bank of Canada series exist? (invented IDs)
- does a cited vector belong to a table the answer cites? (mismatched IDs)
- does a cited series hold a value equal to a number the answer states? (supporting IDs)

Lookups are cached in `citation_checks.json` beside each version's key, so grading is
repeatable offline; `grade --verify` fetches what the cache lacks.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

WDS = "https://www150.statcan.gc.ca/t1/wds/rest/"
VALET = "https://www.bankofcanada.ca/valet/"

DASHED_TABLE = re.compile(r"\b(\d{2})-(\d{2})-(\d{4})(?:-\d{2})?\b")
VECTOR = re.compile(r"\bv(\d{1,11})\b", re.IGNORECASE)
# FXUSDCAD, V39079, CPI_TRIM, BD.CDN.10YR.DQ.YLD. Candidates only: an acronym such as
# "CPI" or "SEPH" does not match, and a candidate Valet does not know is ignored, not
# counted as invented, because it may be ordinary text.
VALET_NAME = re.compile(r"\b(FX[A-Z]{6}|V\d{4,9}|[A-Z][A-Z0-9]*(?:[._][A-Z0-9]+)+)\b")
RELEASE = re.compile(r"\b(releas\w*|diffus\w*|published (?:on|in))\b", re.IGNORECASE)


def table_ids(text: str) -> set[int]:
    """Product ids of the tables an answer cites in StatCan's dashed form."""
    return {int(a + b + c) for a, b, c in DASHED_TABLE.findall(text)}


def vector_ids(text: str) -> set[int]:
    return {int(v) for v in VECTOR.findall(text)}


def valet_names(text: str) -> set[str]:
    return set(VALET_NAME.findall(text))


def _close(stated: float, published: float) -> bool:
    return abs(stated - published) <= max(0.051, abs(published) * 0.0005)


@dataclass
class CitationCheck:
    vectors: list[int] = field(default_factory=list)
    vectors_invented: list[int] = field(default_factory=list)
    vectors_supporting: list[int] = field(default_factory=list)
    vectors_off_table: list[int] = field(default_factory=list)
    tables: list[int] = field(default_factory=list)
    tables_invented: list[int] = field(default_factory=list)
    valet: list[str] = field(default_factory=list)
    valet_supporting: list[str] = field(default_factory=list)
    traceable: bool = False
    release_mentioned: bool = False

    @property
    def cited(self) -> int:
        return len(self.vectors) + len(self.valet)

    @property
    def supporting(self) -> int:
        return len(self.vectors_supporting) + len(self.valet_supporting)

    @property
    def invented(self) -> int:
        return len(self.vectors_invented) + len(self.tables_invented)


class Cache:
    """Publisher lookups, keyed 'vector:N', 'table:N', 'valet:NAME'."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )

    def save(self) -> None:
        self.path.write_text(
            json.dumps(self.data, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )

    def missing(self, texts: list[str]) -> tuple[set[int], set[int], set[str]]:
        vecs, tabs, names = set(), set(), set()
        for text in texts:
            vecs |= {v for v in vector_ids(text) if f"vector:{v}" not in self.data}
            tabs |= {t for t in table_ids(text) if f"table:{t}" not in self.data}
            names |= {n for n in valet_names(text) if f"valet:{n}" not in self.data}
        return vecs, tabs, names

    def fetch(self, texts: list[str]) -> None:
        """Look up every identifier the texts cite that the cache does not hold yet."""
        vecs, tabs, names = self.missing(texts)
        with httpx.Client(http2=True, timeout=120) as client:
            if tabs:
                cubes = client.get(WDS + "getAllCubesListLite").json()
                known = {int(c["productId"]) for c in cubes}
                for t in tabs:
                    self.data[f"table:{t}"] = {"exists": t in known}
            ordered = sorted(vecs)
            for start in range(0, len(ordered), 50):
                chunk = ordered[start : start + 50]
                info = client.post(
                    WDS + "getSeriesInfoFromVector", json=[{"vectorId": v} for v in chunk]
                ).json()
                pids = {}
                for item in info:
                    obj = item.get("object")
                    if isinstance(obj, dict) and obj.get("responseStatusCode") == 0:
                        pids[int(obj["vectorId"])] = int(obj["productId"])
                data = client.post(
                    WDS + "getDataFromVectorsAndLatestNPeriods",
                    json=[{"vectorId": v, "latestN": 400} for v in pids],
                ).json()
                values: dict[int, list[float]] = {}
                for item in data:
                    obj = item.get("object")
                    if isinstance(obj, dict) and obj.get("responseStatusCode") == 0:
                        values[int(obj["vectorId"])] = [
                            float(p["value"])
                            for p in obj.get("vectorDataPoint") or []
                            if p.get("value") is not None
                        ]
                for v in chunk:
                    self.data[f"vector:{v}"] = (
                        {"exists": True, "product_id": pids[v], "values": values.get(v, [])}
                        if v in pids
                        else {"exists": False}
                    )
            for name in sorted(names):
                response = client.get(f"{VALET}observations/{name}/json", params={"recent": 500})
                if response.status_code != 200:
                    self.data[f"valet:{name}"] = {"exists": False}
                    continue
                rows = response.json().get("observations", [])
                self.data[f"valet:{name}"] = {
                    "exists": True,
                    "values": [
                        float(row[name]["v"])
                        for row in rows
                        if isinstance(row.get(name), dict) and _is_number(row[name].get("v"))
                    ],
                }

    def check(self, text: str, figures: list[float]) -> CitationCheck:
        out = CitationCheck(release_mentioned=bool(RELEASE.search(text)))
        cited_tables = table_ids(text)
        for t in sorted(cited_tables):
            out.tables.append(t)
            if not self.data.get(f"table:{t}", {}).get("exists", True):
                out.tables_invented.append(t)
        for v in sorted(vector_ids(text)):
            entry = self.data.get(f"vector:{v}")
            if entry is None:
                continue
            out.vectors.append(v)
            if not entry["exists"]:
                out.vectors_invented.append(v)
                continue
            if cited_tables and entry["product_id"] not in cited_tables:
                out.vectors_off_table.append(v)
            if any(_close(f, p) for f in figures for p in entry["values"]):
                out.vectors_supporting.append(v)
        for name in sorted(valet_names(text)):
            entry = self.data.get(f"valet:{name}")
            if not entry or not entry["exists"]:
                continue  # an unknown name may be ordinary text, so it is not "invented"
            out.valet.append(name)
            if any(_close(f, p) for f in figures for p in entry["values"]):
                out.valet_supporting.append(name)
        out.traceable = out.supporting > 0
        return out


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
