# ============================================================
# Verify reproduce_code scripts against their tools, live
# Author: Daniel Sanchez
# Purpose: Run each tool once, generate its Python (and R, when Rscript is
#          found) script with reproduce_code, run the script for real, and
#          compare the script's row count with the tool's. Some cases also
#          check a column the script must keep (vector ids, coordinates
#          kept as text).
# Inputs:  The live sources behind each case below
# Outputs: One line per case and language on the console; exit status 1
#          when any count or check differs
# ============================================================
#
# Run from the repository root:
#     uv run python scripts/verify_reproduce_counts.py
#
# The Python scripts run in a throwaway uv environment with the packages
# they list; R scripts run with Rscript from PATH or MAPLE_RSCRIPT, with
# the packages they load already installed.

# %% 0. Setup

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from maplestats_mcp.modules.reproduce import client

TIMEOUT = 900


def _series_points(payload: dict[str, Any]) -> int:
    """Rows in a result that holds a list of series, each with its own list."""
    return sum(
        len(value)
        for series in payload.get("series") or []
        for value in series.values()
        if isinstance(value, list) and (not value or isinstance(value[0], dict))
    )


@dataclass
class Case:
    tool: str
    arguments: dict[str, Any]
    # Rows the script must return, from the tool's result.
    expected: Callable[[dict[str, Any]], int] | None
    # Python lines appended to the script, printing "CHECK <value>", and the
    # value they must print.
    python_check: str = ""
    check_value: str = ""
    languages: tuple[str, ...] = ("python", "r")
    skip_tool: bool = False
    notes: list[str] = field(default_factory=list)


CASES = [
    # H1, H2: latest periods only, and each row keeps its vector id.
    Case(
        "wds_get_data_from_vectors",
        {"vector_ids": [41690973, 41690914], "latest_n": 6},
        _series_points,
        'print("CHECK", data["vector_id"].null_count() == 0 and data["vector_id"].n_unique())',
        "2",
    ),
    # H5: the key's series and the tool's latest-100 default, not the table.
    Case(
        "sdmx_get_data",
        {"product_id": 18100004, "key": "2.2"},
        lambda payload: int(payload["row_count"]),
    ),
    Case(
        "sdmx_get_data",
        {"product_id": 18100004, "key": "2.2+3", "last_n_observations": 4},
        lambda payload: int(payload["row_count"]),
    ),
    Case(
        "sdmx_get_vector_data",
        {"vector_id": 41690973, "start_period": "2024-01", "end_period": "2024-12"},
        lambda payload: int(payload["row_count"]),
    ),
    # H4: the tool's default limits (10 and 20), not the servers' (1,000, 100).
    Case(
        "socrata_query_dataset_rows",
        {"portal": "calgary", "dataset_id": "848s-4m4z"},
        lambda payload: len(payload["rows"]),
    ),
    Case(
        "ckan_datastore_search",
        {"portal": "on", "resource_id": "ea9dc29c-b4f1-4426-b1f2-974ce995aca1"},
        lambda payload: len(payload["records"]),
    ),
    # Valet: one row per date and series.
    Case(
        "boc_get_observations",
        {"series_names": ["FXUSDCAD", "FXEURCAD"], "recent": 5},
        lambda payload: len(payload["observations"]) * len(payload["series"]),
    ),
    # H6: quoted cells with line breaks stay one row (Stata's case; Python
    # and R read the same CSV).
    Case(
        "arcgis_hub_query_feature_layer",
        {"portal": "ottawa", "item_id": "c4816ebf0d58479d9f8e6c8485607e35"},
        lambda payload: len(payload["rows"]),
    ),
    # H7: CMHC's CSV export, two title lines above its header and notes below.
    Case(
        "cmhc_get_table_data",
        {
            "category_level_1": "Primary Rental Market",
            "category_level_2": "Vacancy Rate (%)",
            "column_field": "2",
            "row_field": "TIMESERIES",
        },
        lambda payload: len(payload["rows"]),
    ),
    Case(
        "eccc_query_items",
        {
            "collection_id": "climate-daily",
            "filters": {"CLIMATE_IDENTIFIER": "3031093"},
            "limit": 5,
        },
        lambda payload: len(payload.get("features") or payload.get("items") or []),
    ),
    # The script keeps every matching round; the tool shows the first 20.
    Case(
        "ircc_list_express_entry_rounds",
        {"program": "Canadian Experience Class"},
        lambda payload: int(payload["total_matching"]),
    ),
    # H3: StatCan coordinates stay text ("2.1" is not "2.10"). The full
    # table's distinct coordinates, counted from its CSV, must survive.
    Case(
        "wds_get_cube_metadata",
        {"product_id": 18100004},
        None,
        (
            "import csv, zipfile\n"
            "with zipfile.ZipFile(raw_path) as archive:\n"
            '    with archive.open("18100004.csv") as handle:\n'
            '        rows = csv.DictReader(line.decode("utf-8-sig") for line in handle)\n'
            '        raw_count = len({row["COORDINATE"] for row in rows})\n'
            'print("CHECK", data["coordinate"].n_unique() == raw_count, data["coordinate"].dtype)\n'
        ),
        "True String",
        languages=("python",),
        skip_tool=True,
    ),
]

PYTHON_PACKAGES = ["polars", "httpx[http2]", "fastexcel", "pandas", "lxml", "pyarrow"]
R_COUNT = '\ncat("ROWS", nrow(data), "\\n")\n'
PY_COUNT = '\nprint("ROWS", data.height)\n'


def _rscript() -> str | None:
    found = os.environ.get("MAPLE_RSCRIPT") or shutil.which("Rscript")
    if found:
        return found
    installs = sorted(Path("C:/Program Files/R").glob("R-*/bin/Rscript.exe"))
    return str(installs[-1]) if installs else None


def _run(command: list[str], folder: Path) -> tuple[int | None, str, str]:
    """The ROWS and CHECK lines a script printed, or the error it ended with."""
    try:
        done = subprocess.run(
            command, cwd=folder, capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
    except subprocess.TimeoutExpired:
        return None, "", "timed out"
    rows, check = None, ""
    for line in done.stdout.splitlines():
        if line.startswith("ROWS "):
            rows = int(line.split()[1])
        if line.startswith("CHECK "):
            check = line.removeprefix("CHECK ").strip()
    error = "" if done.returncode == 0 else (done.stderr or done.stdout).strip()[-600:]
    return rows, check, error


# %% 1. Run every case


async def verify(case: Case, rscript: str | None) -> bool:
    expected = None
    if not case.skip_tool:
        payload, _ = await client._run_tool(case.tool, case.arguments)
        expected = case.expected(payload) if case.expected else None
    result = await client.reproduce(case.tool, case.arguments)
    scripts = {script.language: script.code for script in result.scripts}
    ok = True
    for language in case.languages:
        if language == "r" and rscript is None:
            print(f"SKIP {case.tool} r: no Rscript found")
            continue
        code = scripts.get(language)
        if code is None:
            print(f"FAIL {case.tool} {language}: no script ({'; '.join(result.notes)})")
            ok = False
            continue
        with tempfile.TemporaryDirectory() as folder:
            if language == "python":
                path = Path(folder, "script.py")
                path.write_text(code + PY_COUNT + case.python_check, encoding="utf-8")
                extras = [arg for package in PYTHON_PACKAGES for arg in ("--with", package)]
                command = ["uv", "run", "--no-project", *extras, "python", str(path)]
            else:
                path = Path(folder, "script.R")
                path.write_text(code + R_COUNT, encoding="utf-8")
                command = [str(rscript), str(path)]
            rows, check, error = _run(command, Path(folder))
        label = f"{case.tool} {language} {case.arguments}"
        if error:
            print(f"FAIL {label}: the script failed: {error}")
            ok = False
            continue
        if expected is not None and rows != expected:
            print(f"FAIL {label}: script {rows} rows, tool {expected}")
            ok = False
            continue
        if language == "python" and case.check_value and check != case.check_value:
            print(f"FAIL {label}: check printed {check!r}, expected {case.check_value!r}")
            ok = False
            continue
        print(f"OK   {label}: {rows} rows" + (f", check {check}" if check else ""))
    return ok


async def main() -> int:
    rscript = _rscript()
    # Optional arguments keep only the cases whose tool name contains one.
    chosen = [c for c in CASES if not sys.argv[1:] or any(a in c.tool for a in sys.argv[1:])]
    results = [await verify(case, rscript) for case in chosen]
    print(f"{sum(results)} of {len(results)} cases match their tool")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
