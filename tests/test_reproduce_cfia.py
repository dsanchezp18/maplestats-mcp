"""reproduce_code for the CFIA tools (reproduce/cfia.py), against saved pages.

The pages are the fixtures of modules/cfia/__tests__ (the <main> element of
each live page, saved 2026-09-26), served through pytest-httpx. The
generated Python parsers run here on those pages and must give the rows
the tool gives; R and Julia run the whole script offline where they and
their packages are installed (GitHub's runner has a bare julia, so those
tests probe the packages and skip). The scripts were also run live on
2026-09-27 in R 4.3, Julia 1.11 and Python, and the Stata script's
python: block line by line (see the CFIA section of
docs/findings/specialized-federal-sources.md).
"""

from __future__ import annotations

import ast
import collections
import io
import json
import re
import shutil
import subprocess
import sys
import tokenize
import types
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from bs4 import BeautifulSoup

from maplestats_mcp.modules.cfia import client as cfia
from maplestats_mcp.modules.cfia import constants
from maplestats_mcp.modules.reproduce import cfia as builder
from maplestats_mcp.modules.reproduce import client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput

_FIXTURES = Path(__file__).parent.parent / "src/maplestats_mcp/modules/cfia/__tests__"
_DETECTIONS = {
    "chronic_wasting_disease": ("cwd_en.html", "cwd_fr.html"),
    "scrapie": ("scrapie_en.html", "scrapie_fr.html"),
    "bovine_tuberculosis": ("btb_en.html", "btb_fr.html"),
    "cysticercosis": ("cysticercosis_en.html", None),
    "bovine_spongiform_encephalopathy": ("bse_en.html", None),
    "trichinellosis": ("trichinellosis_en.html", None),
    "avian_influenza": ("ai_en.html", "ai_fr.html"),
}
# URL -> fixture file; None answers 404, which the tool (and the scripts)
# treat as an unreadable French page and keep English labels.
_PAGES: dict[str, str | None] = {
    constants.REPORTABLE_PAGE["en"]: "reportable_en.html",
    constants.REPORTABLE_PAGE["fr"]: "reportable_fr.html",
    constants.HPAI_PREMISES_PAGE["en"]: "premises_en.html",
    constants.HPAI_PREMISES_PAGE["fr"]: "premises_fr.html",
    constants.HPAI_STATUS_PAGE["en"]: "status_en.html",
    constants.HPAI_STATUS_PAGE["fr"]: "status_fr.html",
}
for _key, (_en, _fr) in _DETECTIONS.items():
    _PAGES[constants.DETECTION_PAGES[_key]["en"]] = _en
    _PAGES[constants.DETECTION_PAGES[_key]["fr"]] = _fr

pytestmark = pytest.mark.httpx_mock(assert_all_responses_were_requested=False)


@pytest.fixture(autouse=True)
def pages(httpx_mock):
    cache_module._caches.clear()
    for url, name in _PAGES.items():
        if name is None:
            httpx_mock.add_response(url=url, status_code=404, is_reusable=True)
        else:
            httpx_mock.add_response(
                url=url,
                text=(_FIXTURES / name).read_text(encoding="utf-8"),
                headers={"content-type": "text/html; charset=UTF-8"},
                is_reusable=True,
            )
    yield


def _codes(result) -> dict[str, str]:
    return {s.language: s.code for s in result.scripts}


# Every tool and argument shape ------------------------------------------------------------

_SHAPES: list[tuple[str, dict[str, Any]]] = [
    ("cfia_reportable_diseases", {}),
    ("cfia_reportable_diseases", {"year_from": 2014, "year_to": 2016}),
    ("cfia_reportable_diseases", {"disease": "CWD", "totals_by": "year"}),
    ("cfia_reportable_diseases", {"disease": "tremblante", "lang": "fr"}),
    ("cfia_reportable_diseases", {"disease": "bovine", "totals_by": "disease"}),
    ("cfia_reportable_diseases", {"totals_by": "disease", "lang": "fr"}),
    ("cfia_disease_detections", {}),
    ("cfia_disease_detections", {"disease": "CWD", "province": "SK", "counts_by": "year"}),
    ("cfia_disease_detections", {"disease": "BSE", "year_from": 2010, "year_to": 2021}),
    (
        "cfia_disease_detections",
        {"disease": "cwd", "animal_type": "wapiti", "counts_by": "province"},
    ),
    ("cfia_disease_detections", {"disease": "scrapie", "counts_by": "month", "lang": "fr"}),
    ("cfia_disease_detections", {"disease": "tb", "counts_by": "animal_type"}),
    ("cfia_disease_detections", {"disease": "tuberculose bovine", "province": "SK", "lang": "fr"}),
    ("cfia_avian_influenza", {}),
    ("cfia_avian_influenza", {"status": "current", "province": "MB"}),
    ("cfia_avian_influenza", {"status": "released", "counts_by": "year", "limit": 5}),
    ("cfia_avian_influenza", {"date_from": "2024-11", "date_to": "2025-02", "counts_by": "month"}),
    (
        "cfia_avian_influenza",
        {
            "province": "AB",
            "premises_type": "commercial",
            "counts_by": "premises_type",
            "lang": "fr",
        },
    ),
]


def _stata_block(do: str) -> str:
    return do.split("\npython:\n", 1)[1].split("\nend\n", 1)[0]


def _string_literals(code: str) -> collections.Counter[str]:
    values: collections.Counter[str] = collections.Counter()

    def collect(text: str) -> None:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.STRING:
                value = ast.literal_eval(token.string)
                if isinstance(value, str):
                    values[value] += 1
                    if token.line.lstrip().startswith("exec("):
                        collect(value)

    collect(code)
    return values


@pytest.mark.parametrize(("tool", "args"), _SHAPES)
async def test_every_shape_gets_four_scripts(tool, args):
    result = await client.reproduce(tool, args)
    code = _codes(result)
    assert set(code) == {"r", "python", "stata", "julia"}, result.notes
    assert result.method.startswith("exact")
    ast.parse(code["python"])
    for line in _stata_block(code["stata"]).splitlines():
        compile(line, "<stata-python>", "exec")  # Stata compiles one line at a time
    for text in code.values():
        # Provenance: every page, the query and the attribution the terms ask for.
        assert f"{tool}(" in text and "Canadian Food Inspection Agency" in text
        assert "Date modified" in text and "credits the title" in text
    assert "library(rvest)" in code["r"] and "using Gumbo" in code["julia"]
    assert "from bs4 import BeautifulSoup" in code["python"]
    assert "beautifulsoup4" in next(s for s in result.scripts if s.language == "python").packages
    # Stata's rewriting to one-line statements keeps every string literal.
    spec = await builder.__dict__[_BUILDERS[tool]](args, {})
    python = spec.native["python"].body + spec.prepare["python"].body
    assert not _string_literals(python) - _string_literals(_stata_block(code["stata"]))


_BUILDERS = {
    "cfia_reportable_diseases": "reportable",
    "cfia_disease_detections": "detections",
    "cfia_avian_influenza": "avian_influenza",
}


async def test_header_names_each_page_its_role_and_date():
    result = await client.reproduce(
        "cfia_avian_influenza", {"province": "AB", "lang": "fr", "limit": 3}, "python"
    )
    code = result.scripts[0].code
    header = code.split("# %% 0. Setup")[0]
    assert constants.HPAI_PREMISES_PAGE["en"] in header
    assert constants.HPAI_PREMISES_PAGE["fr"] in header
    assert constants.HPAI_STATUS_PAGE["fr"] in header
    assert "dates and statuses; Date modified" in header and "labels (municipality" in header
    assert "Investigations and orders of avian influenza" in header
    assert '"province": "AB", "limit": 3, "lang": "fr"' in header
    # The language rule is stated where the pages are read.
    flat = " ".join(line.lstrip("# ") for line in code.splitlines())
    assert "only labels from the French page" in flat and "joined by premises id" in flat


async def test_reportable_reads_every_year_table_not_one():
    result = await client.reproduce("cfia_reportable_diseases", {"year_from": 2011}, "python")
    code = result.scripts[0].code
    assert 'main.find_all("table")' in code and 'find_previous("h2")' in code
    assert "tables[" not in code  # the generic HTML path picked one table


async def test_bad_arguments_raise_like_the_tool():
    with pytest.raises(InvalidInput, match="unknown disease"):
        await client.reproduce("cfia_reportable_diseases", {"disease": "foot and mouth"})
    with pytest.raises(InvalidInput, match="unknown province"):
        await client.reproduce("cfia_avian_influenza", {"province": 'SK"); system("x'})
    with pytest.raises(InvalidInput, match="YYYY"):
        await client.reproduce("cfia_avian_influenza", {"date_from": "2024-01-01$(x)"})
    with pytest.raises(InvalidInput, match="whole number"):
        await client.reproduce("cfia_disease_detections", {"year_from": "2020; rm -rf"})
    with pytest.raises(InvalidInput, match="cfia_reportable_diseases"):
        await client.reproduce("cfia_disease_detections", {"disease": "EIA"})


# The generated Python, run on the pages --------------------------------------------------


def _python_namespace(tmp_path: Path) -> dict[str, Any]:
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    return {
        "re": re,
        "time": types.SimpleNamespace(sleep=lambda seconds: None),
        "unicodedata": __import__("unicodedata"),
        "date": date,
        "httpx": httpx,
        "BeautifulSoup": BeautifulSoup,
        "RAW_DIR": raw,
        "pl": None,
    }


async def _parsers(tool: str, args: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    """The script's helpers and parsers, without the polars steps."""
    spec = await builder.__dict__[_BUILDERS[tool]](args, {})
    body = spec.native["python"].body.split("\nSCHEMA = {")[0]
    namespace = _python_namespace(tmp_path)
    exec(compile(body, "<cfia-script>", "exec"), namespace)  # noqa: S102 - generated here
    return namespace


def _plain(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return ",".join(value)
    return value


async def test_python_reportable_parser_matches_the_client(tmp_path):
    for lang in ("en", "fr"):
        ns = await _parsers("cfia_reportable_diseases", {"lang": lang}, tmp_path)
        url = constants.REPORTABLE_PAGE[lang]
        rows, as_of = ns["parse_reportable"](ns["fetch_page"](url, "page.html"), url)
        tool = await cfia.get_reportable_diseases(lang=lang)
        assert as_of == str(tool.current_as_of)
        rows.sort(key=lambda r: (-r["year"], cfia._fold(r["disease"])))
        fields = ("year", "disease_key", "disease", "count", "note", "detections_tool")
        assert [tuple(r[f] for f in fields) for r in rows] == [
            tuple(getattr(r, f) for f in fields) for r in tool.rows
        ]
        assert len({r["year"] for r in rows}) == 16  # every year table, 2011-2026


_DETECTION_FIELDS = (
    "disease_key",
    "disease",
    "year",
    "date_confirmed",
    "date_text",
    "location",
    "province_codes",
    "animal_type",
    "herds",
    "age",
    "note",
)


@pytest.mark.parametrize("lang", ["en", "fr"])
async def test_python_detection_parser_matches_the_client(lang, tmp_path):
    ns = await _parsers("cfia_disease_detections", {"lang": lang}, tmp_path)
    rows = [row for page in ns["PAGES"] for row in ns["detections_for"](*page)]
    rows.sort(
        key=lambda r: (r["date_confirmed"] or date(r["year"], 1, 1), r["disease_key"]),
        reverse=True,
    )
    tool = await cfia.get_disease_detections(lang=lang)
    assert len(rows) == tool.row_count == 181
    assert sum(r["herds"] for r in rows) == tool.herd_count
    assert [tuple(_plain(r[f]) for f in _DETECTION_FIELDS) for r in rows] == [
        tuple(_plain(getattr(r, f)) for f in _DETECTION_FIELDS) for r in tool.rows
    ]
    if lang == "fr":
        # Dates from the English page, labels from the French one ("21 huin").
        scrapie = [r for r in rows if r["disease_key"] == "scrapie" and r["year"] == 2019]
        assert {r["date_text"] for r in scrapie} == {"21 juin", "21 huin"}
        assert {r["date_confirmed"] for r in scrapie} == {date(2019, 6, 21)}


async def test_python_french_rows_that_do_not_line_up_keep_english_labels(tmp_path, httpx_mock):
    ns = await _parsers(
        "cfia_disease_detections", {"disease": "tuberculose bovine", "lang": "fr"}, tmp_path
    )
    shifted = (_FIXTURES / "btb_fr.html").read_text().replace("<td>2018</td>", "<td>2019</td>", 1)
    fr_url = constants.DETECTION_PAGES["bovine_tuberculosis"]["fr"]
    ns["fetch_page"] = lambda url, name: BeautifulSoup(
        shifted if url == fr_url else (_FIXTURES / "btb_en.html").read_text(), "html.parser"
    )
    rows = ns["detections_for"](*ns["PAGES"][0])
    assert rows[0]["animal_type"] == "Dairy Cattle"


@pytest.mark.parametrize("lang", ["en", "fr"])
async def test_python_premises_parser_matches_the_client(lang, tmp_path):
    ns = await _parsers("cfia_avian_influenza", {"lang": lang}, tmp_path)
    english = ns["parse_premises"](ns["fetch_page"](ns["URL_EN"], "en.html"), ns["URL_EN"])
    french = ns["french_premises"]() if lang == "fr" else {}
    rows = ns["with_labels"](english, french)
    rows.sort(key=lambda r: (r["date_detected"] or date.min, r["number"]), reverse=True)
    tool = await cfia.get_avian_influenza(limit=1000, lang=lang)
    fields = [f for f in type(tool.premises[0]).model_fields]
    assert len(rows) == tool.total_matched == 30
    assert [tuple(_plain(r[f]) for f in fields) for r in rows] == [
        tuple(_plain(getattr(p, f)) for f in fields) for p in tool.premises
    ]
    summary = ns["status_rows"]()
    assert tool.province_summary is not None
    assert [(r["province_code"], r["birds_impacted"]) for r in summary[:-1]] == [
        (r.province_code, r.birds_impacted) for r in tool.province_summary.rows
    ]
    assert summary[-1]["current_premises"] == tool.province_summary.total_current


async def test_python_helpers_match_the_client(tmp_path):
    ns = await _parsers("cfia_avian_influenza", {}, tmp_path)
    ns |= await _parsers("cfia_disease_detections", {}, tmp_path)
    reportable = await _parsers("cfia_reportable_diseases", {}, tmp_path)
    texts = ["Débilitante’s  Œuvre", "Île-Prince-Édouard", "PEI", "Alberta et Saskatchewan"]
    texts += ["Alberta and Saskatchewan", "Terre-Neuve", "qc", "Yukon Territory", "Atlantis"]
    for text in texts:
        assert ns["fold"](text) == cfia._fold(text)
        assert ns["province_code"](text) == cfia.province_code(text)
        assert ns["province_codes_in"](text) == cfia.province_codes_in(text)
    for text, year in [("July 6", 2020), ("1er juin", 2019), ("21 huin", 2019), ("Feb 30", 1)]:
        assert ns["parse_day_month"](text, year) == cfia.parse_day_month(text, year)
    for text in ["September 26, 2026", "16 mai 2026", "no date"]:
        assert ns["parse_long_date"](text) == cfia.parse_long_date(text)
    for text in ["2,552,000", "2 552 000", "2\u202f552\u00a0000", "`0", "Under 100", "12,34"]:
        assert ns["parse_int"](text) == cfia.parse_int(text)
    for text in ["commercial", "Non- commerciale", "captive wild", "s.o.", "backyard flock"]:
        assert ns["premises_type"](text) == cfia.normalize_premises_type(text)
    for text in ["poultry", "N/A\u00a0- LPAI", "non-volailles", "o.s."]:
        assert ns["woah_class"](text) == cfia.normalize_woah(text)
    for text in ["Revoked; PCZ-239 Revoked", "Zone libérée", "Actif", "N/A"]:
        assert ns["order_status"](text) == cfia.normalize_order(text)
    for name in ["Tremblante du mouton", "Notifiable avian influenza", "Anthrax", "New thing!"]:
        assert reportable["disease_key"](name) == cfia.disease_key(name)
    for key in [*constants.DISEASES, "new_thing"]:
        for year in (2016, 2021, 2026):
            assert reportable["detections_tool"](key, year) == cfia._detections_tool(key, year)


async def test_python_layout_changes_stop_the_script(tmp_path):
    ns = await _parsers("cfia_reportable_diseases", {}, tmp_path)
    url = constants.REPORTABLE_PAGE["en"]
    page = (_FIXTURES / "reportable_en.html").read_text()
    renamed = page.replace(">Disease<", ">Illness<")
    with pytest.raises(SystemExit, match="unexpected columns"):
        ns["parse_reportable"](BeautifulSoup(renamed, "html.parser"), url)
    with pytest.raises(SystemExit, match="no <main>"):
        ns["parse_reportable"](BeautifulSoup("<html><body></body></html>", "html.parser"), url)
    ns = await _parsers("cfia_avian_influenza", {}, tmp_path)
    no_table = BeautifulSoup("<main><p>Moved</p></main>", "html.parser")
    with pytest.raises(SystemExit, match="no infected premises table"):
        ns["parse_premises"](no_table, "u")
    ns = await _parsers("cfia_disease_detections", {"disease": "cwd"}, tmp_path)
    with pytest.raises(SystemExit, match="Year / Date confirmed"):
        ns["parse_detections"](no_table, "u")


async def test_python_and_stata_scripts_end_to_end(tmp_path, monkeypatch):
    """Whole Python scripts, and Stata's block line by line (needs polars)."""
    pytest.importorskip("polars")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    for tool, args in _E2E:
        code = _codes(await client.reproduce(tool, args))
        expected = await _expected(tool, args)
        script: dict[str, Any] = {"__name__": "__script__"}
        aggregate = await _expected_aggregate(tool, args)
        exec(compile(code["python"], "<script>", "exec"), script)  # noqa: S102
        stata: dict[str, Any] = {"__name__": "__stata__"}
        for line in _stata_block(code["stata"]).splitlines():
            exec(compile(line, "<stata-python>", "exec"), stata)  # noqa: S102
        for namespace in (script, stata):
            assert _frame_rows(namespace["data"], _FIELDS[tool]) == expected, tool
            if aggregate is not None:
                name, columns = _AGGREGATES[tool]
                assert _frame_rows(namespace[name], columns) == aggregate, (tool, args)


def _text(value: Any) -> str:
    value = _plain(value)
    return "" if value is None else str(value)


def _frame_rows(frame: Any, fields: list[str]) -> list[list[str]]:
    return [[_text(row[f]) for f in fields] for row in frame.iter_rows(named=True)]


# Hostile text ---------------------------------------------------------------------------

_PAYLOAD = 'zq"); system("touch pwned") $(run(`id`)) `x\' /* a */ b // c\nshell touch pwned'
_STATA_ACTIVE = re.compile(r"\$|`|/\*|\*/|(?<!:)//")


async def test_hostile_animal_type_stays_inside_its_literals():
    """animal_type is the one free-text argument the tool accepts as given."""
    result = await client.reproduce(
        "cfia_disease_detections", {"disease": "cwd", "animal_type": _PAYLOAD}
    )
    code = _codes(result)
    folded = cfia._fold(_PAYLOAD)
    for language, text in code.items():
        for line in text.splitlines():
            assert not line.startswith(("shell", 'system("touch')), (language, line)
    tree = ast.parse(code["python"])
    literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)]
    assert folded in literals
    # Julia: no "$(" outside an escaped "\$(" (comments are inert).
    julia = [line for line in code["julia"].splitlines() if not line.lstrip().startswith("#")]
    assert any("\\$(run" in line for line in julia)
    assert not any("$(run" in line.replace("\\$(run", "") for line in julia)
    # Stata: nothing its parser acts on, in the header or the Python block.
    do = code["stata"]
    for line in do.splitlines():
        if "zq" in line:
            assert not _STATA_ACTIVE.search(line.removesuffix("; the prepared table as `data`")), (
                line
            )
    assert folded in _string_literals(_stata_block(do))
    assert not any(line.lstrip().startswith("shell") for line in do.splitlines())


async def test_hostile_animal_type_is_one_r_string(tmp_path):
    rscript = shutil.which("Rscript")
    if rscript is None:
        pytest.skip("R is not installed")
    result = await client.reproduce(
        "cfia_disease_detections", {"disease": "cwd", "animal_type": _PAYLOAD}, "r"
    )
    path = tmp_path / "script.R"
    path.write_text(result.scripts[0].code)
    # parse() reads the whole script without running it: any code the payload
    # escaped into would show up as calls to system().
    probe = (
        f"exprs <- parse({json.dumps(str(path))}, keep.source = FALSE)\n"
        "calls <- all.names(as.call(c(as.name('{'), exprs)))\n"
        "cat(sum(calls == 'system'), sum(calls == 'run'), '\\n')\n"
    )
    out = _run([rscript, "-e", probe])
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["0", "0"]


# R and Julia, whole scripts offline -------------------------------------------------------

_E2E = [
    (
        "cfia_reportable_diseases",
        {"year_from": 2022, "disease": "CWD", "totals_by": "year", "lang": "fr"},
    ),
    ("cfia_disease_detections", {"disease": "scrapie", "counts_by": "province", "lang": "fr"}),
    (
        "cfia_avian_influenza",
        {"date_from": "2024", "counts_by": "month", "limit": 12, "lang": "fr"},
    ),
    # No row matches: the scripts return an empty table, as the tool does.
    ("cfia_disease_detections", {"disease": "cwd", "province": "NS", "counts_by": "province"}),
    ("cfia_avian_influenza", {"status": "current", "province": "NS", "counts_by": "premises_type"}),
    ("cfia_reportable_diseases", {"year_from": 2026, "disease": "scrapie", "totals_by": "disease"}),
    ("cfia_avian_influenza", {"limit": 7}),
    (
        "cfia_disease_detections",
        {"disease": "cwd", "animal_type": "wapiti", "counts_by": "animal_type", "lang": "fr"},
    ),
    ("cfia_reportable_diseases", {"disease": "bovine", "totals_by": "disease"}),
]


def _run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, capture_output=True, text=True, timeout=1200, check=False, **kwargs
    )


def _probe(binary: str, code: str) -> bool:
    return _run([binary, "-e", code]).returncode == 0


# Every field of each returned row, and the totals or counts the tool returns
# beside them (the script's frame name and columns).
_FIELDS = {
    "cfia_reportable_diseases": [
        "year",
        "disease_key",
        "disease",
        "count",
        "note",
        "detections_tool",
    ],
    "cfia_disease_detections": list(_DETECTION_FIELDS),
    "cfia_avian_influenza": [
        "premises_id",
        "province_code",
        "province",
        "location",
        "date_detected",
        "status",
        "premises_type",
        "premises_type_label",
        "woah_classification",
        "woah_classification_label",
        "low_pathogenic",
        "control_zone",
        "control_zone_order",
        "control_zone_order_text",
    ],
}
_AGGREGATES = {
    "cfia_reportable_diseases": ("totals", ["key", "label", "total", "rows"]),
    "cfia_disease_detections": ("counts", ["key", "label", "detections", "herds"]),
    "cfia_avian_influenza": ("counts", ["key", "label", "current", "released", "total"]),
}


def _fields(tool: str) -> list[str]:
    return _FIELDS[tool]


def _offline_r(
    code: str, out: Path, fields: list[str], aggregate: tuple[str, list[str], Path] | None = None
) -> str:
    pages = ", ".join(
        f"{json.dumps(url)} = {json.dumps(str(_FIXTURES / name))}"
        for url, name in _PAGES.items()
        if name
    )
    override = (
        f"fixture_pages <- list({pages})\n"
        "fetch_page <- function(url, file) {\n"
        '  if (is.null(fixture_pages[[url]])) stop("HTTP 404")\n'
        '  read_html(fixture_pages[[url]], encoding = "UTF-8")\n'
        "}\n"
    )
    code = code.replace(
        "fetch_page <- function(url, file) {", "fetch_online <- function(url, file) {"
    )
    code = code.replace("# 1. Read inputs ----\n", "# 1. Read inputs ----\n" + override, 1)
    frames = [("data", fields, out), *([aggregate] if aggregate else [])]
    for name, columns, path in frames:
        names = ", ".join(json.dumps(f) for f in columns)
        code += (
            f"\nwrite.table(as.data.frame({name})[, c({names}), drop = FALSE], "
            f"{json.dumps(str(path))}, sep = '\\t', na = '', quote = FALSE, "
            "row.names = FALSE, col.names = FALSE, fileEncoding = 'UTF-8')\n"
        )
    return code


def _offline_julia(
    code: str,
    out: Path,
    fields: list[str],
    name: str,
    aggregate: tuple[str, list[str], Path] | None = None,
) -> str:
    pages = ", ".join(
        f"{json.dumps(url)} => {json.dumps(str(_FIXTURES / page))}"
        for url, page in _PAGES.items()
        if page
    )
    override = (
        f"const FIXTURE_PAGES = Dict({pages})\n"
        "fetch_page(url, file) = haskey(FIXTURE_PAGES, url) ? "
        'parsehtml(read(FIXTURE_PAGES[url], String)).root : error("HTTP 404")\n'
    )
    code = code.replace("function fetch_page(url, file)", "function fetch_online(url, file)")
    code = code.replace("# 1. Read inputs\n", "# 1. Read inputs\n" + override, 1)
    writer = ""
    for frame, columns, path in [("data", fields, out), *([aggregate] if aggregate else [])]:
        names = ", ".join(json.dumps(f) for f in columns)
        writer += (
            f'\nopen({json.dumps(str(path))}, "w") do io\n'
            f"    for row in eachrow({frame}[:, [{names}]])\n"
            '        println(io, join([ismissing(x) ? "" : string(x) for x in row], "\\t"))\n'
            "    end\n"
            "end\n"
        )
    # One Julia process runs every script, each in its own module.
    return f"module {name}\n{code}{writer}end\n"


async def _tool_result(tool: str, args: dict[str, Any]) -> Any:
    function = {
        "cfia_reportable_diseases": cfia.get_reportable_diseases,
        "cfia_disease_detections": cfia.get_disease_detections,
        "cfia_avian_influenza": cfia.get_avian_influenza,
    }[tool]
    return await function(**args)


async def _expected(tool: str, args: dict[str, Any]) -> list[list[str]]:
    result = await _tool_result(tool, args)
    rows = result.premises if tool == "cfia_avian_influenza" else result.rows
    return [[_text(getattr(row, f)) for f in _FIELDS[tool]] for row in rows]


async def _expected_aggregate(tool: str, args: dict[str, Any]) -> list[list[str]] | None:
    """The tool's totals (reportable) or counts, None when it returns none."""
    result = await _tool_result(tool, args)
    groups = result.totals if tool == "cfia_reportable_diseases" else result.counts
    if groups is None:
        return None
    return [[_text(getattr(group, c)) for c in _AGGREGATES[tool][1]] for group in groups]


def _read_rows(path: Path) -> list[list[str]]:
    # R writes TRUE/FALSE and Julia true/false where Python writes True/False.
    booleans = {"TRUE": "True", "true": "True", "FALSE": "False", "false": "False"}
    return [
        [booleans.get(cell, cell) for cell in line.split("\t")]
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _aggregate_file(tool: str, path: Path) -> tuple[str, list[str], Path]:
    name, columns = _AGGREGATES[tool]
    return name, columns, path


_R_SCRIPT_PACKAGES = (
    "rvest",
    "xml2",
    "dplyr",
    "stringr",
    "stringi",
    "httr2",
    "janitor",
    "readr",
    "tibble",
    "tidyr",
)


async def test_r_scripts_reproduce_the_tool_offline(tmp_path):
    rscript = shutil.which("Rscript")
    if rscript is None:
        pytest.skip("R is not installed")
    load = "; ".join(f"library({p})" for p in _R_SCRIPT_PACKAGES)
    if not _probe(rscript, f"suppressMessages({{{load}}})"):
        pytest.skip("R packages for the CFIA scripts are not installed")
    for index, (tool, args) in enumerate(_E2E):
        result = await client.reproduce(tool, args, "r")
        out, groups = tmp_path / f"out_{index}.tsv", tmp_path / f"groups_{index}.tsv"
        aggregate = await _expected_aggregate(tool, args)
        script = tmp_path / f"script_{index}.R"
        script.write_text(
            _offline_r(
                result.scripts[0].code,
                out,
                _fields(tool),
                _aggregate_file(tool, groups) if aggregate is not None else None,
            )
        )
        run = _run([rscript, str(script)], cwd=tmp_path)
        assert run.returncode == 0, run.stderr[-3000:]
        assert _read_rows(out) == await _expected(tool, args), tool
        if aggregate is not None:
            assert _read_rows(groups) == aggregate, (tool, args)


async def test_r_french_premises_listed_twice_take_the_last_row(tmp_path, monkeypatch):
    """The tool joins French labels through a dict, so a repeated id keeps its last row."""
    rscript = shutil.which("Rscript")
    if rscript is None:
        pytest.skip("R is not installed")
    load = "; ".join(f"library({p})" for p in _R_SCRIPT_PACKAGES)
    if not _probe(rscript, f"suppressMessages({{{load}}})"):
        pytest.skip("R packages for the CFIA scripts are not installed")
    pages = tmp_path / "pages"
    shutil.copytree(_FIXTURES, pages, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    french = (pages / "premises_fr.html").read_text(encoding="utf-8")
    start = french.index("<tbody>") + len("<tbody>")
    end = french.index("</tr>", start) + len("</tr>")
    repeated = french[start:end].replace("</td>\n<td>", " (bis)</td>\n<td>", 1)
    (pages / "premises_fr.html").write_text(french[:end] + repeated + french[end:], "utf-8")
    monkeypatch.setattr(sys.modules[__name__], "_FIXTURES", pages)
    served = {
        url: (pages / name).read_text(encoding="utf-8") for url, name in _PAGES.items() if name
    }

    async def fetch(url: str) -> str:
        return served[url]

    monkeypatch.setattr(cfia, "_fetch", fetch)
    cache_module._caches.clear()
    args = {"province": "AB", "lang": "fr"}
    expected = await _expected("cfia_avian_influenza", args)
    location = _FIELDS["cfia_avian_influenza"].index("location")
    assert any(row[location].endswith("(bis)") for row in expected)
    result = await client.reproduce("cfia_avian_influenza", args, "r")
    out = tmp_path / "out.tsv"
    script = tmp_path / "script.R"
    script.write_text(_offline_r(result.scripts[0].code, out, _fields("cfia_avian_influenza")))
    run = _run([rscript, str(script)], cwd=tmp_path)
    assert run.returncode == 0, run.stderr[-3000:]
    assert _read_rows(out) == expected


async def test_julia_scripts_reproduce_the_tool_offline(tmp_path):
    julia = shutil.which("julia")
    if julia is None:
        pytest.skip("Julia is not installed")
    # GitHub's ubuntu runner ships a bare julia: probe the packages the scripts load.
    if not _probe(julia, "using Cascadia, DataFrames, Gumbo, TidierData"):
        pytest.skip("Julia packages for the CFIA scripts are not installed")
    modules, outputs = [], []
    for index, (tool, args) in enumerate(_E2E):
        result = await client.reproduce(tool, args, "julia")
        out, groups = tmp_path / f"out_{index}.tsv", tmp_path / f"groups_{index}.tsv"
        aggregate = await _expected_aggregate(tool, args)
        outputs.append((out, groups, aggregate, tool, args))
        modules.append(
            _offline_julia(
                result.scripts[0].code,
                out,
                _fields(tool),
                f"Run{index}",
                _aggregate_file(tool, groups) if aggregate is not None else None,
            )
        )
    script = tmp_path / "scripts.jl"
    script.write_text("\n".join(modules))
    run = _run([julia, str(script)], cwd=tmp_path)
    assert run.returncode == 0, run.stderr[-3000:]
    for out, groups, aggregate, tool, args in outputs:
        assert _read_rows(out) == await _expected(tool, args), tool
        if aggregate is not None:
            assert _read_rows(groups) == aggregate, (tool, args)


@pytest.mark.parametrize("language", ["r", "julia"])
async def test_r_and_julia_helpers_match_the_client(language, tmp_path):
    binary = shutil.which("Rscript" if language == "r" else "julia")
    if binary is None:
        pytest.skip(f"{language} is not installed")
    probe = (
        "suppressMessages({library(dplyr); library(stringr); library(stringi); library(xml2); "
        "library(rvest); library(httr2)})"
        if language == "r"
        else "using Cascadia, Gumbo"
    )
    if not _probe(binary, probe):
        pytest.skip(f"{language} packages for this test are not installed")
    helpers = builder._helpers(language, "en", dates=True, ints=True)
    texts = ["Débilitante’s  Œuvre", "Île-Prince-Édouard", "Alberta et Saskatchewan", "PEI"]
    days = [("December 17", 2021), ("1er juin", 2019), ("21 huin", 2019), ("30 février", 2020)]
    numbers = ["2,552,000", "2 552 000", "2\u202f552\u00a0000", "`0", "Under 100"]
    if language == "r":
        quote = builder._r_str
        script = (
            "suppressMessages({library(dplyr); library(stringr); library(stringi); "
            "library(xml2); library(rvest); library(httr2)})\n"
            + helpers
            + "".join(
                f"cat(fold({quote(t)}), province_code({quote(t)}), "
                f"str_c(province_codes_in({quote(t)}), collapse = ','), sep = '|'); cat('\\n')\n"
                for t in texts
            )
            + "".join(f"cat(format(parse_day_month({quote(t)}, {y})), '\\n')\n" for t, y in days)
            + "".join(f"cat(parse_int({quote(n)}), '\\n')\n" for n in numbers)
        )
    else:
        quote = builder._jl_str
        script = (
            "using Cascadia, Dates, Downloads, Gumbo, Unicode\n"
            + helpers
            + "".join(
                f'println(join([fold({quote(t)}), coalesce(province_code({quote(t)}), "NA"), '
                f'join(province_codes_in({quote(t)}), ",")], "|"))\n'
                for t in texts
            )
            + "".join(
                f'println((d = parse_day_month({quote(t)}, {y}); ismissing(d) ? "NA" : d))\n'
                for t, y in days
            )
            + "".join(f'println(coalesce(parse_int({quote(n)}), "NA"))\n' for n in numbers)
        )
    path = tmp_path / ("helpers.R" if language == "r" else "helpers.jl")
    path.write_text(script, encoding="utf-8")
    # LANG=C: the R helpers must match non-ASCII text outside a UTF-8 locale.
    out = _run(
        [binary, str(path)], env={"LANG": "C", "PATH": "/usr/bin:/bin", "HOME": str(Path.home())}
    )
    assert out.returncode == 0, out.stderr
    lines = [line.strip() for line in out.stdout.splitlines()]
    expected = [
        "|".join(
            [cfia._fold(t), cfia.province_code(t) or "NA", ",".join(cfia.province_codes_in(t))]
        )
        for t in texts
    ]
    expected += [str(cfia.parse_day_month(t, y) or "NA") for t, y in days]
    expected += [str(cfia.parse_int(n) if cfia.parse_int(n) is not None else "NA") for n in numbers]
    assert lines == expected
