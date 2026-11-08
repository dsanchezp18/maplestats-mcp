"""SAS (.sas7bdat), SPSS (.sav, .zsav) and Stata (.dta) PUMF data files.

Some PUMFs ship their microdata only in a statistical package's format:
Canada's Core Public Infrastructure Survey (34-25-0001, 2020 and 2022) has
one .sas7bdat and no text file (checked 2026-11-08). DuckDB 2.0 has no
reader for these formats (the read_stat community extension is not built
for it: HTTP 404 on 2026-11-08), so pyreadstat reads them: Apache-2.0,
over the MIT-licensed ReadStat C library, with numpy and narwhals as its
only dependencies (no pandas with output_format="dict").

The file is converted once, in chunks, to a CSV of text values beside it
in the PUMF cache, and tabulated from there like any CSV member: memory
stays at one chunk (about 400,000 cells) whatever the file's size.
Measured 2026-11-08 on the CCPI 2022 file (670,292 rows x 12 columns, 86 MB,
psutil sampling every 50 ms, MAPLE_DUCKDB_MEMORY_LIMIT=384MB): conversion
7 s; the first table 31 s including the download, peak process memory
194 MB from 62 MB at start; later tables 4 s.
"""

from __future__ import annotations

import csv
import math
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from maplestats_mcp.modules.statcan.lang import say
from maplestats_mcp.modules.statcan.pumf.schemas import PumfVariable, ValueLabel
from maplestats_mcp.shared.errors import UpstreamError

EXTENSIONS = (".sas7bdat", ".sav", ".zsav", ".dta")
# Cells per chunk: a cell is a Python object of about 50-80 bytes once read.
_CHUNK_CELLS = 400_000


def is_stat_file(name: str) -> bool:
    return name.lower().endswith(EXTENSIONS)


def column_name(raw: str) -> str:
    """The name a variable gets in the converted CSV and in the codebook.

    Upper case, as the other codebooks give them, and an identifier the tool
    accepts: CCPI's SAS file has a column named "Municipal class".
    """
    name = re.sub(r"[^A-Za-z0-9_]", "_", raw.strip()).upper() or "_"
    return "_" + name if name[0].isdigit() else name


def _names(raw: list[str]) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for column in raw:
        name = column_name(column)
        while name in seen:
            name += "_"
        seen.add(name)
        names.append(name)
    return names


def _reader(path: Path) -> Callable[..., Any]:
    import pyreadstat  # imported on first use: only this conversion needs it

    suffix = path.suffix.lower()
    if suffix == ".sas7bdat":
        return pyreadstat.read_sas7bdat
    if suffix in (".sav", ".zsav"):
        return pyreadstat.read_sav
    return pyreadstat.read_dta


def _fail(path: Path, exc: Exception) -> UpstreamError:
    return UpstreamError(
        say(
            f"statcan_pumf: {path.name} could not be read: {exc}",
            f"statcan_pumf : {path.name} n'a pas pu être lu : {exc}",
        )
    )


def _metadata(path: Path) -> Any:
    read = _reader(path)
    try:
        _, meta = read(str(path), metadataonly=True, output_format="dict")
    except Exception as exc:
        raise _fail(path, exc) from exc
    return meta


def read_variables(path: Path) -> list[PumfVariable]:
    """The file's own variable names, labels and value labels, as a codebook.

    SAS files keep value labels in a separate format catalogue, so theirs
    come back without values; SPSS and Stata files carry them.
    """
    meta = _metadata(path)
    raw_names: list[str] = list(meta.column_names)
    labels: dict[str, str | None] = dict(meta.column_names_to_labels or {})
    value_labels: dict[str, dict[Any, str]] = dict(meta.variable_value_labels or {})
    variables: list[PumfVariable] = []
    for raw, name in zip(raw_names, _names(raw_names), strict=True):
        values = [
            ValueLabel(code=_text(code), label=str(label))
            for code, label in (value_labels.get(raw) or {}).items()
        ]
        variables.append(PumfVariable(name=name, label=labels.get(raw) or None, values=values))
    return variables


def _text(value: Any) -> str:
    """A cell as the CSV path reads it: whole numbers without '.0', missing as ''."""
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    return str(value).strip()


def to_csv(path: Path) -> Path:
    """Convert the file once to a CSV beside it; later calls reuse that CSV."""
    import pyreadstat

    target = path.with_name(path.name + ".csv")
    if target.exists():
        target.touch()
        return target
    meta = _metadata(path)
    raw_names: list[str] = list(meta.column_names)
    chunk_rows = max(500, _CHUNK_CELLS // max(1, len(raw_names)))
    part = target.with_name(f"{target.name}.{uuid.uuid4().hex[:8]}.part")
    try:
        with part.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(_names(raw_names))
            chunks = pyreadstat.read_file_in_chunks(
                _reader(path),
                str(path),
                chunksize=chunk_rows,
                output_format="dict",
                # Dates stay the numbers stored in the file, as in the text PUMFs.
                disable_datetime_conversion=True,
            )
            for chunk, _ in chunks:
                columns = [[_text(v) for v in chunk[name]] for name in raw_names]
                writer.writerows(zip(*columns, strict=True))
        part.replace(target)
    except UpstreamError:
        raise
    except Exception as exc:
        raise _fail(path, exc) from exc
    finally:
        part.unlink(missing_ok=True)
    return target
