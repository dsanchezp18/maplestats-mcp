"""Summary scripts: a whole table downloaded and summarized outside the conversation.

wds_get_full_table_download returns Python and R scripts that keep the members
and periods asked for and print a summary; reproduce_code(summary=True) ends
any R or Python script the same way. No network: the WDS calls are replaced.
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
from maplestats_mcp.modules.statcan.wds import client as wds_client
from maplestats_mcp.modules.statcan.wds.schemas import CubeDimension, DimensionMember
from maplestats_mcp.shared.errors import InvalidInput

_MEASURE = "Measure of core inflation based on a trimmed mean approach, CPI-trim"


def _by_language(result) -> dict[str, str]:
    return {s.language: s.code for s in result.scripts}


async def test_summary_scripts_are_r_and_python_with_the_filters():
    result = await client.reproduce(
        "wds_get_full_table_download",
        {
            "product_id": "18-10-0256-01",
            "members": {"Geography": ["Canada"], "Alternative measures": [_MEASURE]},
            "start_period": "2025-01",
            "end_period": "2025-12",
        },
        summary=True,
    )
    code = _by_language(result)
    assert set(code) == {"r", "python"}
    assert any("summary printout is written in R and Python only" in n for n in result.notes)
    python, r = code["python"], code["r"]
    # Geography is the CSV's GEO column; members match ignoring case.
    assert "pl.col('GEO')" in python and "'canada'," in python
    assert f"{_MEASURE.lower()!r}," in python
    assert "pl.col('REF_DATE').cast(pl.Utf8) >= '2025-01'" in python
    assert "pl.col('REF_DATE').cast(pl.Utf8) <= '2025-12'" in python
    assert 'str_to_lower(str_trim(`GEO`)) %in% c(\n      "canada"\n    )' in r
    # The summary comes last, after the cleaning, and prints instead of the frame.
    for text, mark in ((python, "# %% 4. Summarize"), (r, "# 4. Summarize ----")):
        assert text.index("3. Prepare data") < text.index(mark)
        assert "a printed summary of it" in text
    assert "library(tibble)" in r and "as_tibble(" in r
    compile(python, "<script>", "exec")


async def test_without_summary_the_scripts_are_unchanged():
    result = await client.reproduce("wds_get_full_table_download", {"product_id": 18100256})
    code = _by_language(result)
    assert set(code) == {"r", "python", "stata", "julia", "excel"}
    assert not any("Summarize" in text for text in code.values())
    assert result.notes == []


async def test_french_table_filters_french_columns_and_notes():
    result = await client.reproduce(
        "wds_get_full_table_download",
        {"product_id": 34100130, "lang": "fr", "members": {"geo": "Montréal, Québec"}},
        language="python",
        lang="fr",
        summary=True,
    )
    code = result.scripts[0].code
    assert "pl.col('GÉO')" in code and "'montréal, québec'," in code
    assert result.notes == [
        "Le script télécharge le tableau complet, puis garde les membres et les périodes demandés."
    ]


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
    assert 'lowercase(strip(coalesce(string(row["GEO"]), ""))) in ("canada", "ontario",)' in julia
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


@pytest.fixture
def offline_wds(monkeypatch):
    """The inventory check, metadata and download link without WDS; a test may
    replace `.metadata` on the returned object."""
    state = SimpleNamespace(metadata=_metadata())

    async def known(pid):
        return None

    async def metadata(pid, **kwargs):
        return state.metadata

    async def get(method, path_suffix=""):
        pid, lang = path_suffix.strip("/").split("/")
        return f"https://www150.statcan.gc.ca/n1/tbl/csv/{pid}-{lang[:2]}.zip"

    monkeypatch.setattr(wds_client, "_require_known_table", known)
    monkeypatch.setattr(wds_client, "get_cube_metadata", metadata)
    monkeypatch.setattr(wds_client, "_get", get)
    return state


async def test_download_returns_summary_scripts_with_the_csv_spelling(offline_wds):
    link = await wds_client.get_full_table_download_csv(
        34100130, "fr", members={"GEO": ["montreal, quebec"]}, start_period="2020"
    )
    assert [s.language for s in link.scripts] == ["python", "r"]
    python = link.scripts[0].code
    # Matched without accents, written as the French file spells it.
    assert "'montréal, québec'," in python and "pl.col('GÉO')" in python
    assert "# %% 4. Summarize" in python


async def test_download_without_members_still_has_scripts(offline_wds):
    link = await wds_client.get_full_table_download_csv(34100130)
    assert link.download_url.endswith("34100130-en.zip")
    assert "4. Summarize" in link.scripts[1].code
    assert "Keep the rows" not in link.scripts[1].code


async def test_unknown_dimension_or_member_is_refused(offline_wds):
    with pytest.raises(InvalidInput, match="Its dimensions: Geography"):
        await wds_client.get_full_table_download_csv(34100130, members={"Sex": ["Males"]})
    with pytest.raises(InvalidInput, match="'Toronto, Ontario' is not a member"):
        await wds_client.get_full_table_download_csv(
            34100130, members={"Geography": ["Toronto, Ontario"]}
        )


async def test_member_not_checked_when_the_metadata_is_capped(offline_wds):
    # Only part of the dimension came back, so an unlisted name may still exist.
    offline_wds.metadata = _metadata(member_count=5000)
    link = await wds_client.get_full_table_download_csv(
        34100130, members={"Geography": ["Toronto, Ontario"]}
    )
    assert "'toronto, ontario'," in link.scripts[0].code
