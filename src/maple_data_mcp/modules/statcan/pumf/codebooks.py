"""Parse the codebook formats StatCan ships inside PUMF zips.

Each parser returns {variable name (upper case): PumfVariable}; the
client merges them so a Stata .dct (positions, labels) and a .do file
(value labels) describe the same variables together.
"""

from __future__ import annotations

import csv
import io
import re

from maple_data_mcp.modules.statcan.pumf.schemas import PumfVariable, ValueLabel

Variables = dict[str, PumfVariable]

_QUOTED = r'"([^"]*)"?'


def _var(found: Variables, name: str) -> PumfVariable:
    key = name.strip().upper()
    if key not in found:
        found[key] = PumfVariable(name=key, values=[])
    return found[key]


def parse_codebook_csv(text: str, lang: str) -> Variables:
    """LFS-style CSV: a row per variable, then rows of codes with blank Field."""
    found: Variables = {}
    rows = list(csv.reader(io.StringIO(text)))
    label_col = 4 if lang == "en" else 5
    current: PumfVariable | None = None
    for row in rows[1:]:
        if len(row) <= label_col:
            continue
        if row[0].strip():
            current = _var(found, row[3])
            current.label = row[label_col].strip() or None
            current.position = int(row[1]) if row[1].strip().isdigit() else None
            current.width = int(row[2]) if row[2].strip().isdigit() else None
        elif current is not None and row[3].strip():
            label = row[label_col].strip()
            # A range such as "1-9999999" with no label is a domain, not a code.
            if label:
                current.values.append(ValueLabel(code=row[3].strip(), label=label))
    return found


def parse_stata_dct(text: str) -> Variables:
    found: Variables = {}
    # Census: _column(12) byte attsch %1f "label"
    for start, name, width, label in re.findall(
        r"_column\((\d+)\)\s+\w+\s+(\w+)\s+%(\d+)\w*\s+" + _QUOTED, text
    ):
        variable = _var(found, name)
        variable.position, variable.width = int(start), int(width)
        variable.label = variable.label or label.strip() or None
    # CCHS: [str] NAME 31 - 32
    for name, start, end in re.findall(
        r"^\s*(?:str\w*\s+)?(\w+)\s+(\d+)\s*-\s*(\d+)\s*$", text, re.MULTILINE
    ):
        variable = _var(found, name)
        variable.position, variable.width = int(start), int(end) - int(start) + 1
    return found


def parse_stata_do(text: str) -> Variables:
    found: Variables = {}
    for name, label in re.findall(r"label\s+var(?:iable)?\s+(\w+)\s+" + _QUOTED, text):
        _var(found, name).label = label.strip() or None
    # Value-label sets, inline or one code per line under `#delimit ;`.
    sets: dict[str, list[ValueLabel]] = {}
    for block in re.finditer(
        r"label\s+define\s+(\w+)(.*?)(?=label\s+(?:define|values|var)|\Z)", text, re.DOTALL
    ):
        pairs = re.findall(r'(-?\d+(?:\.\d+)?)\s+"([^"]*)"', block.group(2))
        sets[block.group(1).upper()] = [ValueLabel(code=c, label=v.strip()) for c, v in pairs]
    attached = {
        var.upper(): lbl.upper() for var, lbl in re.findall(r"label\s+values\s+(\w+)\s+(\w+)", text)
    }
    for set_name, values in sets.items():
        target = next((v for v, lbl in attached.items() if lbl == set_name), set_name)
        _var(found, target).values = values
    return found


def parse_spss(text: str) -> Variables:
    found: Variables = {}
    var_block = re.search(
        r"VARIABLE\s+LABELS(.*?)(?:\.\s*$|\Z)", text, re.DOTALL | re.IGNORECASE | re.MULTILINE
    )
    if var_block:
        for name, label in re.findall(
            r"^\s*/?(\w+)\s+" + _QUOTED, var_block.group(1), re.MULTILINE
        ):
            _var(found, name).label = label.strip() or None
    value_block = re.search(r"VALUE\s+LABELS(.*)", text, re.DOTALL | re.IGNORECASE)
    if value_block:
        for chunk in re.split(r"^\s*/", value_block.group(1), flags=re.MULTILINE)[1:]:
            lines = chunk.strip().splitlines()
            if not lines:
                continue
            variable = _var(found, lines[0].split()[0])
            for code, label in re.findall(
                r'^\s*"?(-?[\w.]+)"?\s+"([^"]*)"', "\n".join(lines[1:]), re.MULTILINE
            ):
                variable.values.append(ValueLabel(code=code, label=label.strip()))
    return found


def merge(target: Variables, extra: Variables) -> None:
    for key, variable in extra.items():
        base = target.setdefault(key, variable)
        if base is variable:
            continue
        base.label = base.label or variable.label
        base.position = base.position or variable.position
        base.width = base.width or variable.width
        base.values = base.values or variable.values
