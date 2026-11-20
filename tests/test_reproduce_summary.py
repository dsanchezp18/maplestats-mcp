"""Summary scripts: a whole table downloaded and summarized outside the conversation.

reproduce_code for wds_get_full_table_download returns scripts that keep the members
and periods asked for (download the zip, rebuild through WDS at StatCan's captcha);
reproduce_code(summary=True) ends any R or Python script with a summary. No network: the WDS calls are replaced.
The Python script was also run live on 2026-11-03 against 18-10-0256 and
34-10-0130 (English and French editions).
"""

from __future__ import annotations

import contextlib
import io
from types import SimpleNamespace

import pytest

from maplestats_mcp.modules.reproduce import client
from maplestats_mcp.modules.reproduce.builders import full_table_spec
from maplestats_mcp.modules.reproduce.render import _PY_SUMMARY, RENDERERS
from maplestats_mcp.modules.reproduce.spec import Filter, Spec
from maplestats_mcp.modules.statcan.wds.schemas import CubeDimension, DimensionMember
from maplestats_mcp.shared.errors import InvalidInput

_MEASURE = "Measure of core inflation based on a trimmed mean approach, CPI-trim"


def _by_language(result) -> dict[str, str]:
    return {s.language: s.code for s in result.scripts}


async def _full_table(monkeypatch, arguments, **options):
    # The builder reads only the arguments, so the tool's run is replaced and no
    # request leaves the test.
    async def run_tool(name, args, lang="en"):
        return {}, []

    monkeypatch.setattr(client, "_run_tool", run_tool)
    return await client.reproduce("wds_get_full_table_download", arguments, **options)


async def test_a_full_table_script_tries_the_file_then_wds(monkeypatch):
    # StatCan's full-table zips answer most networks (cloud hosts and the hosted
    # server, 2026-11-20) but some get its captcha: R, Python and Stata download the
    # zip and rebuild the same rows through WDS only at the captcha. Until 2026-11-20
    # reproduce_code refused full tables. Run live on 2026-11-20 (18-10-0004, English
    # and French, both routes): the same final table either way.
    arguments = {
        "product_id": "18-10-0004-01",
        "members": {"Geography": ["Canada"]},
        "start_period": "2025",
    }
    result = await _full_table(monkeypatch, arguments)
    code = _by_language(result)
    assert set(code) == {"r", "python", "stata", "julia", "excel"}
    url = "https://www150.statcan.gc.ca/n1/tbl/csv/18100004-eng.zip"
    for language in ("r", "python", "stata"):
        assert url in code[language]
        assert "getDataFromCubePidCoordAndLatestNPeriods" in code[language]
    python = code["python"]
    compile(python, "python", "exec")
    fetch = python.split("def fetch_table", 1)[1]
    assert fetch.index(f"client.get({url!r})") < fetch.index("wds_rebuild(output)")
    assert "MEMBERS = {'Geography': ['Canada']}" in python
    assert "START_PERIOD = '2025'" in python
    assert 'list(dimension = "Geography", keep = c("Canada"))' in code["r"]
    assert "if (wds_captcha(response)) {" in code["r"]
    # Stata runs the same Python, one physical line at a time.
    block = code["stata"].split("python:\n", 1)[1].split("\nend\n", 1)[0]
    for line in filter(str.strip, block.splitlines()):
        compile(line, "stata", "exec")
    assert any("rebuild the same rows" in n for n in result.notes)


async def test_a_french_full_table_script_writes_the_french_edition(monkeypatch):
    arguments = {"product_id": 18100004, "members": {"Géographie": ["Québec"]}, "lang": "fr"}
    result = await _full_table(monkeypatch, arguments, language="r", lang="fr")
    (script,) = result.scripts
    assert "18100004-fra.zip" in script.code
    assert 'table_language <- "fr"' in script.code
    # R literals are ASCII: in a C locale a literal "É" reached R as "<c3><89>".
    settings = script.code.split("# --- Settings", 1)[1].split("# --- End of settings", 1)[0]
    assert 'list(dimension = "G\\u00e9ographie", keep = c("Qu\\u00e9bec"))' in settings
    assert "valeur_normalisee" in script.code
    assert any("vérification anti-robot" in n for n in result.notes)


async def test_a_full_table_summary_comes_in_r_and_python(monkeypatch):
    result = await _full_table(monkeypatch, {"product_id": "18-10-0256-01"}, summary=True)
    assert {s.language for s in result.scripts} == {"r", "python"}
    assert all("Summarize" in s.code for s in result.scripts)


@pytest.mark.parametrize(
    "members, period",
    [
        (["Canada"], None),  # not a mapping
        ({"Geography": []}, None),
        ({"Geography": [""]}, None),
        ({"Geo`graphy": ["Canada"]}, None),  # would leave R's backticks
        (None, "January 2025"),
    ],
)
def test_bad_members_or_periods_are_refused(members, period):
    with pytest.raises(InvalidInput):
        full_table_spec(18100256, "en", members, period)


def test_in_filter_in_julia_and_excel():
    spec = Spec(
        kind="csv",
        url="https://x.ca/f.csv",
        file_name="f.csv",
        method="exact",
        filters=[Filter("in", ["GEO"], ["Canada", " Ontario "])],
    )
    julia, _ = RENDERERS["julia"](spec, "t")  # type: ignore[misc]
    assert 'lowercase(strip(string(coalesce(row["GEO"], "")))) in ("canada", "ontario",)' in julia
    from maplestats_mcp.modules.reproduce.excel import render_excel

    rendered = render_excel(spec, "t")
    assert rendered is not None
    assert 'List.Contains({"canada", "ontario"}' in rendered[0]


def test_python_summary_prints_a_summary_not_the_rows():
    pl = pytest.importorskip("polars")
    data = pl.DataFrame(
        {
            "ref_date": [f"2025-{m:02d}" for m in range(1, 13)] * 2,
            "geo": ["Canada"] * 24,
            "measure": ["a"] * 12 + ["b"] * 12,
            "value": [float(v) for v in range(24)],
            "status": [None] * 24,
        }
    )
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(_PY_SUMMARY, {"pl": pl, "data": data, "raw_path": "data/raw/x.zip"})  # noqa: S102
    text = out.getvalue()
    assert text.startswith("24 rows x 5 columns; download saved as data/raw/x.zip")
    assert "- geo (1 distinct): Canada" in text
    assert "- value (24 distinct): 0.0 to 23.0" in text
    assert "- status (0 distinct): all missing" in text
    # The row printout leaves out the columns with one value.
    table = text.split("shape:")[1]
    assert "measure" in table and "geo" not in table


# wds_get_full_table_download ----------------------------------------------------


def _metadata(member_count: int | None = None):
    geography = CubeDimension(
        dimension_position_id=1,
        dimension_name_en="Geography",
        dimension_name_fr="Géographie",
        has_uom=False,
        member_count=member_count or 2,
        members=[
            DimensionMember(
                member_id=1,
                parent_member_id=None,
                member_name_en="Montreal, Quebec",
                member_name_fr="Montréal, Québec",
            ),
            DimensionMember(
                member_id=2,
                parent_member_id=None,
                member_name_en="Barrie, Ontario",
                member_name_fr="Barrie, Ontario",
            ),
        ],
    )
    return SimpleNamespace(dimensions=[geography])


@pytest.mark.parametrize(
    ("end", "bound"),
    [("2025", "2025-12-31"), ("2025-03", "2025-03-31"), ("2025-03-15", "2025-03-15")],
)
def test_end_period_keeps_the_whole_last_period(end, bound):
    # REF_DATE compares as text, and "2025-03" > "2025": an end of 2025 must keep 2025's months.
    spec = full_table_spec("18-10-0256-01", "en", None, None, end)
    (last,) = [f for f in spec.filters if f.op == "le"]
    assert last.value == bound
    for kept in (end, end[:4] + "-12" if len(end) == 4 else end):
        assert kept <= last.value
