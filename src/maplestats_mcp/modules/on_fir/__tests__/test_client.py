"""Mocked tests for the Ontario FIR module, shaped on the Ministry's real files.

fixtures/myc_index.html is the first four rows of MYCIndex.html as captured
on 2026-09-09. fixtures/fir_data_2023_sample.csv is 34 rows of
fir_data_2023.zip (posted 2025-04) copied byte for byte: AMOUNT padded to
80 characters, Ottawa's MUNID with a leading space, an alphanumeric column
(slc.53X.L1070.C01.0A) and Thunder Bay's schedule 83 note with a bare
double quote inside a quoted field. The treasurer name rows were left out.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from maplestats_mcp.modules.on_fir import client, constants, store
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_FIXTURES = Path(__file__).parent / "fixtures"
_INDEX = (_FIXTURES / "myc_index.html").read_text(encoding="utf-8")
_CSV_2023 = (_FIXTURES / "fir_data_2023_sample.csv").read_text(encoding="utf-8")


def _zip(text: str, name: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, text)
    return buffer.getvalue()


def _year(text: str, year: int) -> str:
    """The 2023 sample relabelled as another year (header line untouched)."""
    header, _, body = text.partition("\n")
    return header + "\n" + body.replace("\n2023,", f"\n{year},").replace("2023,", f"{year},", 1)


@pytest.fixture(autouse=True)
def _cache(tmp_path, monkeypatch):
    monkeypatch.setenv("MAPLE_ON_FIR_CACHE_DIR", str(tmp_path / "on_fir"))
    store._downloads.clear()


def _mock_index(httpx_mock):
    httpx_mock.add_response(url=constants.INDEX_URL, text=_INDEX)


def _mock_year(httpx_mock, year: int, text: str | None = None):
    body = _year(_CSV_2023, year) if text is None else text
    httpx_mock.add_response(
        url=constants.ZIP_URL.format(year=year),
        content=_zip(body, f"fir_data_{year}.csv"),
        headers={"content-type": "application/x-zip-compressed"},
    )


def test_parse_index_reads_years_dates_and_links():
    years = client.parse_index(_INDEX)
    assert [y.year for y in years] == [2025, 2024, 2023, 2022]
    assert years[0].last_updated == "2026-09-08"
    assert years[1].last_updated == "2026-09-02"
    assert years[1].posted == "2026-09-08"
    assert years[2].url.endswith("/MultiYearReport/fir_data_2023.zip")


async def test_list_schedules_counts_filers_and_flags_an_incomplete_year(httpx_mock):
    _mock_index(httpx_mock)
    _mock_year(httpx_mock, 2023)
    result = await client.list_schedules(2023)
    assert result.year == 2023
    assert result.municipalities_filed == 5
    codes = [s.code for s in result.schedules]
    assert codes == ["02X", "40X", "53X", "83X"]
    assert next(s for s in result.schedules if s.code == "40X").lines == 2
    assert [y.year for y in result.years][:2] == [2025, 2024]
    assert result.provenance.coverage is not None
    assert "5 of Ontario's 444" in result.provenance.coverage
    assert "incomplete" in result.provenance.coverage
    assert result.provenance.as_of is not None
    assert result.provenance.licence is not None
    assert "Open Government Licence - Ontario" in result.provenance.licence


async def test_default_year_is_the_one_before_the_newest(httpx_mock):
    _mock_index(httpx_mock)
    _mock_year(httpx_mock, 2024)
    result = await client.list_schedules()
    assert result.year == 2024


async def test_a_year_is_downloaded_once(httpx_mock):
    _mock_index(httpx_mock)
    _mock_year(httpx_mock, 2023)
    await client.list_schedules(2023)
    # A second zip request would find no mocked response and fail.
    again = await client.search_municipalities("toronto", 2023)
    assert again.total == 1


async def test_search_municipalities_trims_ids_and_reads_population(httpx_mock):
    _mock_index(httpx_mock)
    _mock_year(httpx_mock, 2023)
    result = await client.search_municipalities("ottawa", 2023)
    assert result.total == 1
    ottawa = result.municipalities[0]
    assert ottawa.munid == "6005"
    assert ottawa.name == "Ottawa C"
    assert ottawa.tier == "ST"
    assert ottawa.municipal_type == "city"
    assert ottawa.service_office == "Eastern"
    assert ottawa.population == 1_083_550
    assert ottawa.last_updated == "2025-03-21"

    by_id = await client.search_municipalities("06005", 2023)
    assert [m.name for m in by_id.municipalities] == ["Ottawa C"]

    upper = await client.search_municipalities("", 2023, tier="ut", lang="fr")
    assert [m.name for m in upper.municipalities] == ["Peel R"]
    assert upper.municipalities[0].tier_name.startswith("palier supérieur")


async def test_search_municipalities_rejects_an_unknown_tier(httpx_mock):
    _mock_index(httpx_mock)
    _mock_year(httpx_mock, 2023)
    with pytest.raises(InvalidInput, match="tier"):
        await client.search_municipalities("", 2023, tier="XX")


async def test_search_lines_matches_every_word_without_accents(httpx_mock):
    _mock_index(httpx_mock)
    _mock_year(httpx_mock, 2023)
    result = await client.search_lines("police total after", 2023, schedule="40")
    assert [line.slc for line in result.lines] == ["slc.40X.L0420.C01.11"]
    line = result.lines[0]
    assert (line.schedule, line.line, line.column) == ("40X", "0420", "01.11")
    assert line.line_desc == "Police"
    assert line.column_desc == "Total Expenses After Adjustments"
    assert line.datatype == "currency"
    # Toronto, Ottawa and Peel report police; Mississauga's is Peel's.
    assert line.municipalities == 3


async def test_search_lines_needs_a_query_or_a_schedule():
    with pytest.raises(InvalidInput):
        await client.search_lines("  ")


async def test_get_schedule_returns_labelled_dollar_amounts(httpx_mock):
    _mock_index(httpx_mock)
    _mock_year(httpx_mock, 2023)
    result = await client.get_schedule("Toronto", "40", 2023)
    assert result.municipality.munid == "20002"
    # A bare number covers every part of the schedule.
    assert result.schedule == "40"
    assert result.schedule_name == "CONSOLIDATED STATEMENT OF OPERATIONS: EXPENSES"
    values = {v.slc: v for v in result.values}
    assert values["slc.40X.L0410.C01.11"].amount == 662_165_927
    assert values["slc.40X.L0410.C01.11"].line_desc == "Fire"

    one_line = await client.get_schedule("20002", "40X", 2023, line="L0420")
    assert {v.line for v in one_line.values} == {"0420"}


async def test_get_schedule_reads_a_note_with_a_bare_quote_whole(httpx_mock):
    _mock_index(httpx_mock)
    _mock_year(httpx_mock, 2023)
    result = await client.get_schedule("Thunder Bay", "83", 2023)
    note = result.values[0].text
    assert note is not None
    assert note.startswith("For FIR purposes")
    assert note.endswith("$152,467 was included.")


async def test_get_schedule_keeps_alphanumeric_columns(httpx_mock):
    _mock_index(httpx_mock)
    _mock_year(httpx_mock, 2023)
    result = await client.get_schedule("Peel", "53", 2023)
    assert [v.column for v in result.values] == ["01.0A"]


async def test_get_schedule_names_the_schedules_filed_when_one_is_empty(httpx_mock):
    _mock_index(httpx_mock)
    _mock_year(httpx_mock, 2023)
    with pytest.raises(NotFound, match="02X, 40X, 53X"):
        await client.get_schedule("Toronto", "70", 2023)


async def test_an_ambiguous_name_lists_the_candidates(httpx_mock):
    _mock_index(httpx_mock)
    _mock_year(httpx_mock, 2023)
    with pytest.raises(InvalidInput, match="Ottawa C \\(6005\\)"):
        await client.get_schedule("o", "40", 2023)


async def test_year_not_on_the_index_is_not_found(httpx_mock):
    _mock_index(httpx_mock)
    with pytest.raises(NotFound, match="2022"):
        await client.list_schedules(1995)


async def test_compare_ranks_per_capita_within_a_tier(httpx_mock):
    _mock_index(httpx_mock)
    _mock_year(httpx_mock, 2023)
    result = await client.compare("slc.40x.l0420.c01.11", [2023], tier="ST", per_capita=True)
    assert result.slc == "slc.40X.L0420.C01.11"
    assert result.line_desc == "Police"
    assert [row.municipality for row in result.rows] == ["Toronto C", "Ottawa C"]
    toronto = result.rows[0]
    assert toronto.population == 3_110_984
    assert toronto.amount is not None
    assert toronto.per_capita == pytest.approx(toronto.amount / 3_110_984)
    assert result.label_changes == []


async def test_compare_across_years_reports_label_changes(httpx_mock):
    _mock_index(httpx_mock)
    _mock_year(httpx_mock, 2023)
    relabelled = _year(_CSV_2023, 2022).replace('"Police","Total', '"Police services","Total')
    _mock_year(httpx_mock, 2022, relabelled)
    result = await client.compare(
        "slc.40X.L0420.C01.11", [2022, 2023], municipalities=["Peel R", "21000"]
    )
    assert result.years == [2023, 2022]
    assert [(row.year, row.munid) for row in result.rows] == [(2023, "21000"), (2022, "21000")]
    assert result.label_changes == ["2022: Police services / Total Expenses After Adjustments"]
    assert result.rows[0].per_capita is None


async def test_compare_refuses_a_malformed_code_and_too_many_years():
    with pytest.raises(InvalidInput, match="slc"):
        await client.compare("40X.0420")
    with pytest.raises(InvalidInput, match="10 years"):
        await client.compare("slc.40X.L0420.C01.11", list(range(2000, 2012)))


async def test_compare_with_no_reporting_municipality_is_not_found(httpx_mock):
    _mock_index(httpx_mock)
    _mock_year(httpx_mock, 2023)
    with pytest.raises(NotFound, match="line numbers change"):
        await client.compare("slc.40X.L9999.C01.11", [2023])


async def test_french_errors_and_notes(httpx_mock):
    _mock_index(httpx_mock)
    with pytest.raises(NotFound, match="aucun fichier du RIF pour 1995"):
        await client.list_schedules(1995, lang="fr")


async def test_an_html_answer_for_a_zip_is_not_found(httpx_mock):
    _mock_index(httpx_mock)
    httpx_mock.add_response(
        url=constants.ZIP_URL.format(year=2023),
        text="<html>Page not found</html>",
        headers={"content-type": "text/html; charset=UTF-8"},
    )
    with pytest.raises(NotFound, match="not published"):
        await client.list_schedules(2023)


async def test_a_404_zip_is_not_found(httpx_mock):
    _mock_index(httpx_mock)
    httpx_mock.add_response(url=constants.ZIP_URL.format(year=2023), status_code=404)
    with pytest.raises(NotFound):
        await client.list_schedules(2023)


async def test_a_reposted_year_replaces_the_old_copy(tmp_path, monkeypatch):
    folder = tmp_path / "on_fir"
    folder.mkdir()
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(_CSV_2023, encoding="utf-8")
    old = folder / "fir_2023_20250405.parquet"
    store.convert_csv(csv_path, old)
    zip_body = _zip(_CSV_2023, "fir_data_2023.csv")

    async def fake_fetch(url: str, zip_path: Path) -> None:
        zip_path.write_bytes(zip_body)

    monkeypatch.setattr(store, "_fetch_zip", fake_fetch)
    new = await store.local_year(2023, constants.ZIP_URL.format(year=2023), "2026-09-02")
    assert new.name == "fir_2023_20260902.parquet"
    assert new.exists()
    assert not old.exists()
    assert not list(folder.glob("*.part"))


async def test_index_with_no_years_is_an_upstream_error(httpx_mock):
    httpx_mock.add_response(url=constants.INDEX_URL, text="<html><body>Maintenance</body></html>")
    with pytest.raises(UpstreamError, match="lists no yearly FIR files"):
        await client.list_years()
