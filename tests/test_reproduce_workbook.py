"""reproduce_workbook: rows to a formatted .xlsx, reopened here with openpyxl.

No network: the tool call is replaced by recorded payload shapes (checked
live 2026-10-02 against wds_get_data_from_vectors, sdmx_get_data,
boc_get_observations and socrata_query_dataset_rows).
"""

from __future__ import annotations

import base64
import io
from datetime import date, datetime
from typing import Any

import pytest
from openpyxl import load_workbook
from openpyxl.chart import BarChart, LineChart

from maplestats_mcp.modules.reproduce import workbook
from maplestats_mcp.shared.errors import InvalidInput, NotFound

OGL = "Open Government Licence - Canada (https://open.canada.ca/en/open-government-licence-canada)"

SDMX_PAYLOAD = {
    "dataflow_id": "DF_18100004",
    "key": "2.2",
    "series": [
        {
            "series_key": {"Geography": "2", "Products_and_product_groups": "2"},
            "vector_id": 41690973,
            "scalar_factor": 0,
            "observations": [
                {"period": "2026-05", "value": 168.5},
                {"period": "2026-06", "value": 169.0},
                {"period": "2026-07", "value": 169.9},
            ],
        }
    ],
    "row_count": 3,
    "provenance": {
        "source": "statcan-sdmx",
        "url": "https://www150.statcan.gc.ca/t1/wds/sdmx/statcan/rest/data/DF_18100004/2.2",
        "queried_at": "2026-10-02T22:04:38Z",
        "licence": OGL,
    },
}

# wds_get_data_from_vectors returns a list, one result (with provenance) per vector.
WDS_PAYLOAD = {
    "result": [
        {
            "vector_id": vector,
            "product_id": 18100006,
            "data_points": [
                {"ref_period": f"2026-0{month}-01", "value": 100.0 + month + vector % 7}
                for month in (5, 6, 7)
            ],
            "provenance": {"source": "statcan-wds", "url": "https://www150.statcan.gc.ca/t1/wds/"},
        }
        for vector in (41690973, 41690914)
    ]
}


def _open(result):
    return load_workbook(io.BytesIO(base64.b64decode(result.workbook_base64 or "")))


def _source(book) -> dict[str, str]:
    """The Source sheet as {field: value}."""
    rows = book["Source"].iter_rows(min_row=2, values_only=True)
    return {str(row[0]): "" if row[1] is None else str(row[1]) for row in rows}


def _charts(sheet: Any) -> list[Any]:
    return sheet._charts


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv("MAPLE_TRANSPORT", "http")


@pytest.fixture
def fake_call(monkeypatch):
    calls = []

    def install(payload):
        async def call(tool, arguments, lang="en"):
            calls.append((tool, arguments))
            return payload

        monkeypatch.setattr(workbook, "_call", call)
        return calls

    return install


async def test_tool_rows_become_a_formatted_table_with_source_and_chart(hosted, fake_call):
    calls = fake_call(SDMX_PAYLOAD)
    arguments = {"product_id": 18100004, "key": "2.2", "last_n_observations": 3}
    result = await workbook.export(
        "sdmx_get_data", arguments, None, "CPI, Canada", "en", 2000, "auto"
    )
    assert calls == [("sdmx_get_data", arguments)]
    assert result.saved_path is None
    assert result.size_bytes == len(base64.b64decode(result.workbook_base64 or ""))
    assert result.file_name.startswith("CPI_Canada_") and result.file_name.endswith(".xlsx")
    book = _open(result)
    assert book.sheetnames == ["CPI, Canada", "Chart data", "Chart", "Source"] == result.sheets
    data = book["CPI, Canada"]
    header = [c.value for c in data[1]]
    assert header == [
        "series_key_geography",
        "series_key_products_and_product_groups",
        "vector_id",
        "scalar_factor",
        "period",
        "value",
    ]
    table = data.tables["maplestats_data"]
    assert table.ref == "A1:F4" and table.tableStyleInfo.name == "TableStyleMedium2"
    assert data.freeze_panes == "A2"
    formats = {header[i]: data.cell(row=2, column=i + 1).number_format for i in range(len(header))}
    assert formats["vector_id"] == "0" and formats["value"] == "#,##0.0"
    assert formats["series_key_geography"] == "0" and formats["period"] == "@"
    assert data.cell(row=2, column=1).value == 2  # "2" stored as text became a number
    assert data.column_dimensions["B"].width >= len("series_key_products_and_product_groups")
    chart_data = book["Chart data"]
    assert [c.value for c in chart_data[1]] == ["period", "value"]
    assert "chart_data" in chart_data.tables
    charts = _charts(book["Chart"])
    assert len(charts) == 1 and isinstance(charts[0], LineChart)
    source = _source(book)
    assert source["Tool"] == "sdmx_get_data"
    assert '"key": "2.2"' in source["Arguments (JSON)"]
    assert source["Source URL"] == SDMX_PAYLOAD["provenance"]["url"]
    assert source["Licence"] == OGL
    assert "Open Government Licence - Canada" in source["Attribution"]
    assert source["Rows"] == "3 of 3 rows"
    assert "source_notes" in book["Source"].tables
    # The result's fields outside the rows are named in the notes, valued on the Source sheet.
    assert '"row_count": 3' in source["Fields of the result"]
    assert any("dataflow_id, key, row_count" in note for note in result.notes)
    assert any(note.startswith("Cleaned as the R scripts") for note in result.notes)
    assert any("series_key_geography" in note for note in result.notes)  # converted


async def test_list_results_keep_each_vector_and_pivot_the_chart(hosted, fake_call):
    fake_call(WDS_PAYLOAD)
    result = await workbook.export(
        "wds_get_data_from_vectors",
        {"vector_ids": [41690973, 41690914]},
        None,
        None,
        "en",
        2000,
        "auto",
    )
    book = _open(result)
    data = book.worksheets[0]
    header = [c.value for c in data[1]]
    assert header == ["vector_id", "product_id", "ref_period", "value"]
    assert data.max_row == 7
    assert isinstance(data.cell(row=2, column=3).value, datetime)  # ISO text became a date
    assert data.cell(row=2, column=3).number_format == "yyyy-mm-dd"
    chart_data = book["Chart data"]
    assert [c.value for c in chart_data[1]] == ["ref_period", "41690914", "41690973"]
    assert result.chart and "ref_period" in result.chart
    source = _source(book)
    assert source["Source"] == "statcan-wds"
    assert "Not stated" in source["Licence"]


async def test_rows_passed_directly_french_labels_and_safe_text(hosted):
    rows = [
        {"Région": "Québec", "Montant ($)": "1234.5", "Formule": '=HYPERLINK("http://x")'},
        {"Région": "Ontario", "Montant ($)": "99", "Formule": " texte "},
    ]
    result = await workbook.export(None, None, rows, "Montants", "fr", 2000, "base64")
    book = _open(result)
    assert book.sheetnames == ["Montants", "Données du graphique", "Graphique", "Source"]
    data = book["Montants"]
    assert [c.value for c in data[1]] == ["region", "montant", "formule"]
    cell = data["C2"]
    assert cell.value == '=HYPERLINK("http://x")' and cell.data_type == "s"
    assert data["C3"].value == "texte"
    assert data["B2"].value == 1234.5 and data["B2"].number_format == "#,##0.0"
    assert isinstance(_charts(book["Graphique"])[0], BarChart)
    source = _source(book)
    assert "appelant" in source["Outil"] and source["Lignes"] == "2 lignes sur 2"


async def test_max_rows_caps_and_says_so(hosted):
    rows = [{"name": f"row {n}", "amount": n} for n in range(50)]
    result = await workbook.export(None, None, rows, "Rows", "en", 10, "auto")
    assert result.truncated and result.rows_written == 10 and result.rows_available == 50
    assert any("first 10 of 50" in note for note in result.notes)
    book = _open(result)
    assert book["Rows"].max_row == 11
    source = _source(book)
    assert source["Rows"] == "10 of 50 rows (capped by max_rows)"
    assert isinstance(_charts(book["Chart"])[0], BarChart)  # 10 labelled amounts


async def test_codes_with_leading_zeros_and_mixed_columns_stay_text(hosted):
    rows = [
        {"code": "01", "mixed": "12", "when": "2026-01-02"},
        {"code": "35", "mixed": "n/a", "when": "2026-01-03"},
    ]
    result = await workbook.export(None, None, rows, None, "en", 2000, "auto")
    data = _open(result).worksheets[0]
    assert data["A2"].value == "01" and data["B2"].value == "12" and data["B3"].value == "n/a"
    assert str(data["C2"].value).startswith("2026-01-02")
    assert workbook.clean_rows([{"d": "2026-01-02"}])[1] == [[date(2026, 1, 2)]]


async def test_local_server_saves_the_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MAPLE_TRANSPORT", "stdio")
    monkeypatch.setenv("MAPLE_EXPORT_DIR", str(tmp_path))
    result = await workbook.export(None, None, [{"a": 1}, {"a": 2}], "Local", "en", 2000, "auto")
    assert result.workbook_base64 is None and result.saved_path
    saved = tmp_path / result.file_name
    assert saved.exists() and load_workbook(saved).sheetnames[0] == "Local"


async def test_bad_requests(hosted, monkeypatch):
    with pytest.raises(InvalidInput, match="hosted server"):
        await workbook.export(None, None, [{"a": 1}], None, "en", 10, "file")
    with pytest.raises(InvalidInput, match="tool_name"):
        await workbook.export(None, None, None, None, "en", 10, "auto")
    with pytest.raises(InvalidInput, match="max_rows"):
        await workbook.export(None, None, [{"a": 1}], None, "en", workbook.MAX_ROWS + 1, "auto")
    with pytest.raises(InvalidInput, match="does not return data"):
        await workbook.export("plan_query", {}, None, None, "en", 10, "auto")
    with pytest.raises(NotFound):
        await workbook.export(None, None, [], None, "en", 10, "auto")
    monkeypatch.setattr(workbook, "MAX_BYTES", 1000)
    with pytest.raises(InvalidInput, match="language='excel'"):
        await workbook.export(None, None, [{"a": "x" * 50}] * 50, None, "en", 50, "auto")


def test_names_clean_as_janitor_does():
    assert workbook.clean_names(["PÉRIODE", "referenceNumber", "Indicator", "indicator", "%"]) == [
        "periode",
        "reference_number",
        "indicator",
        "indicator_2",
        "x",
    ]


async def test_tool_is_registered_and_findable():
    from fastmcp import Client

    from maplestats_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool("search_tools", {"query": "export to an Excel workbook"})
    assert "reproduce_workbook" in str(result.content)


async def test_french_errors_notes_and_chart(hosted, monkeypatch):
    with pytest.raises(InvalidInput, match="serveur est hébergé"):
        await workbook.export(None, None, [{"a": 1}], None, "fr", 10, "file")
    with pytest.raises(InvalidInput, match="ne renvoie pas de lignes"):
        await workbook.export("plan_query", {}, None, None, "fr", 10, "auto")
    with pytest.raises(NotFound, match="aucune ligne"):
        await workbook.export(None, None, [], None, "fr", 10, "auto")
    rows = [{"nom": f"ligne {n}", "montant": n} for n in range(1500)]
    result = await workbook.export(None, None, rows, "Lignes", "fr", 10, "base64")
    assert result.notes[0] == "Les 10 premières lignes sur 1 500 ont été écrites (max_rows)."
    assert result.notes[1].startswith("Nettoyé comme dans les scripts R")
    assert result.notes[-1].startswith("Décodez workbook_base64")
    assert result.chart is not None and result.chart.startswith("graphique à barres de montant")
    assert (result.provenance.limits or "").startswith("au maximum 20 000 lignes")
    assert result.provenance.reproduce.startswith("Pour obtenir")
    english = await workbook.export(None, None, rows, "Rows", "en", 10, "base64")
    assert english.notes[0] == "Wrote the first 10 of 1,500 rows (max_rows)."
    assert english.chart is not None and english.chart.startswith("bar chart of montant")


async def test_large_identifiers_stay_exact_in_saved_workbook(hosted):
    rows = [{"code": "9007199254740993"}, {"code": 9007199254740995}]
    result = await workbook.export(None, None, rows, "Identifiers", "en", 2000, "base64")
    data = _open(result).worksheets[0]
    assert data["A2"].value == "9007199254740993"
    assert data["A3"].value == "9007199254740995"
    assert data["A2"].data_type == data["A3"].data_type == "s"


async def test_headers_remain_unique_when_suffixes_already_exist(hosted):
    rows = [{"a": 1, "A": 2, "a_2": 3}]
    result = await workbook.export(None, None, rows, "Columns", "en", 2000, "base64")
    data = _open(result).worksheets[0]
    assert [c.value for c in data[1]] == ["a", "a_2", "a_2_2"]
    assert [c.value for c in data[2]] == [1, 2, 3]


async def test_workbook_size_limits_apply_before_writing(hosted, monkeypatch):
    with pytest.raises(InvalidInput, match="columns"):
        await workbook.export(
            None,
            None,
            [{f"c{n}": n for n in range(workbook.MAX_COLUMNS + 1)}],
            None,
            "en",
            2000,
            "base64",
        )
    monkeypatch.setattr(workbook, "MAX_CELLS", 4)
    with pytest.raises(InvalidInput, match="cellules"):
        await workbook.export(None, None, [{"a": 1, "b": 2}] * 3, None, "fr", 2000, "base64")
    monkeypatch.setattr(workbook, "MAX_TEXT_CHARS", 3)
    with pytest.raises(InvalidInput, match="characters"):
        await workbook.export(None, None, [{"a": "long text"}], None, "en", 2000, "base64")


async def test_export_yields_to_the_tool_deadline(hosted, monkeypatch):
    import threading

    from fastmcp.exceptions import ToolError
    from fastmcp.server.middleware import MiddlewareContext
    from mcp.types import CallToolRequestParams

    from maplestats_mcp.shared.timeouts import ToolTimeoutMiddleware

    started = threading.Event()
    release = threading.Event()
    stopped = threading.Event()

    def slow_workbook(*args, **kwargs):
        started.set()
        try:
            release.wait(2)
            return b"xlsx", ["Data"], None, []
        finally:
            stopped.set()

    monkeypatch.setattr(workbook, "build_workbook", slow_workbook)

    async def export(context):
        return await workbook.export(None, None, [{"a": 1}], None, "en", 2000, "base64")

    context = MiddlewareContext(
        message=CallToolRequestParams(name="reproduce_workbook", arguments={})
    )
    try:
        with pytest.raises(ToolError, match="did not finish"):
            await ToolTimeoutMiddleware(0.1).on_call_tool(context, export)
        assert started.is_set() and not stopped.is_set()
    finally:
        release.set()
        assert stopped.wait(2)


def test_signed_leading_zero_codes_stay_text():
    from maplestats_mcp.modules.reproduce.workbook import _convert

    assert _convert("-0123") == "-0123"
    assert _convert("+007") == "+007"
    assert _convert("-0.5") == -0.5


def test_long_code_makes_whole_column_text():
    from maplestats_mcp.modules.reproduce.workbook import clean_rows

    _, table = clean_rows([{"id": 12345678901234567890}, {"id": 3}])
    assert [r[0] for r in table] == ["12345678901234567890", "3"]


@pytest.mark.parametrize(
    ("licence", "lang", "region"),
    [
        ("Open Government Licence - Canada 2.0 (https://open.canada.ca/)", "en", "Canada"),
        (
            "Open Government Licence - British Columbia 2.0 (https://www2.gov.bc.ca/)",
            "fr",
            "Colombie-Britannique",
        ),
        ("Open Government Licence - Yukon (https://open.yukon.ca/)", "en", "Yukon"),
        (
            "Open Government Licence - Newfoundland and Labrador 1.0 (https://www.gov.nl.ca/)",
            "en",
            "Newfoundland and Labrador",
        ),
        (
            "Licence du gouvernement ouvert – Terre-Neuve-et-Labrador 1.0",
            "en",
            "Newfoundland and Labrador",
        ),
        (
            "Open Government Licence - Northwest Territories, as the territory's open data",
            "fr",
            "Territoires du Nord-Ouest",
        ),
        ("Open Government Licence - Ontario as the terms of the portal", "en", "Ontario"),
        ("Open Government Licence - City of Calgary", "en", None),
        ("Statistics Canada Open Licence", "en", None),
    ],
)
def test_licence_region_follows_the_licence_text(licence, lang, region):
    assert workbook._licence_region(licence, lang) == region


def test_territorial_licence_gets_its_own_attribution():
    attribution = workbook.LABELS["en"]["ogl_attribution"].format(
        region=workbook._licence_region("Open Government Licence - Yukon", "en")
    )
    assert attribution == (
        "Contains information licensed under the Open Government Licence - Yukon."
    )


async def test_series_named_like_a_formula_keeps_text_chart_headers(hosted, recwarn):
    # The chart sheet's header is made of the data's series values, so a value that
    # starts with "=" became a formula cell, openpyxl warned that column headings must
    # be strings, and the Table's column names no longer matched its header cells.
    formula = '=HYPERLINK("http://x","go")'
    rows = [
        {"period": f"2026-0{month}-01", "geography": name, "value": 100.0 + month + shift}
        for month in (1, 2, 3)
        for shift, name in enumerate(("Canada", formula))
    ]
    result = await workbook.export(None, None, rows, "Series", "en", 2000, "base64")
    book = _open(result)
    chart_header = {cell.value: cell for cell in book["Chart data"][1]}
    assert set(chart_header) == {"period", "Canada", formula}
    assert all(cell.data_type == "s" for cell in chart_header.values())
    assert len(_charts(book["Chart"])) == 1
    assert not [w for w in recwarn if "column headings" in str(w.message)]


def test_code_columns_stay_text():
    # StatCan coordinates "2.1" and "2.10" are different members; NAICS is not a quantity.
    from maplestats_mcp.modules.reproduce.workbook import clean_rows_report

    names, table, converted, codes = clean_rows_report(
        [
            {"coordinate": "2.1", "NAICS": "111", "series.vectorId": "41690973", "value": "1.5"},
            {"coordinate": "2.10", "NAICS": "112", "series.vectorId": "41690974", "value": "2"},
        ]
    )
    assert names == ["coordinate", "naics", "series_vector_id", "value"]
    assert table == [["2.1", "111", "41690973", 1.5], ["2.10", "112", "41690974", 2]]
    assert converted == ["value"] and codes == ["coordinate", "naics", "series_vector_id"]


def _statcan_payload(points: list[dict[str, Any]], licence: str) -> dict[str, Any]:
    return {
        "vector_id": 41690973,
        "data_points": points,
        "provenance": {
            "source": "statcan-wds",
            "url": "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods",
            "queried_at": "2026-10-27T15:00:00Z",
            "as_of": "2026-09-16T08:30:00",
            "licence": licence,
        },
    }


async def test_statcan_data_cleaned_are_adapted_from_and_say_what_changed(hosted, fake_call):
    # The Open Licence's notice for data in a value-added product.
    from maplestats_mcp.shared.envelope import STATCAN_LICENCE

    points = [{"refPer": "2026-07-01", "value": " 169.9 "}, {"refPer": "2026-08-01", "value": ""}]
    fake_call(_statcan_payload(points, STATCAN_LICENCE))
    result = await workbook.export(
        "wds_get_data_from_vectors", {"product_id": 18100004}, None, "CPI", "en", 2000, "auto"
    )
    source = _source(_open(result))
    assert source["Licence"] == STATCAN_LICENCE  # as the tool published it
    assert source["Attribution"] == (
        "Adapted from Statistics Canada, Table 18-10-0004-01 CPI, 2026-09-16. This does not "
        "constitute an endorsement by Statistics Canada of this product."
    )
    changes = source["Changes made"]
    assert "column names put in snake_case (1 of 2: refPer → ref_per)" in changes
    assert "cells trimmed of spaces: 1" in changes
    assert "cells left blank (empty text or a non-finite number): 1" in changes
    assert "text converted to numbers or dates in ref_per, value" in changes


async def test_statcan_data_unchanged_keep_the_source_notice_in_french(hosted, fake_call):
    from maplestats_mcp.shared.envelope import make_provenance

    licence = make_provenance(
        source="statcan-wds",
        url="https://www150.statcan.gc.ca",
        cached=False,
        schema_name="s",
        lang="fr",
    ).licence
    points = [{"ref_period": date(2026, 7, 1), "value": 169.9}]
    fake_call(_statcan_payload(points, licence or ""))
    result = await workbook.export("wds_get_data_from_vectors", {}, None, None, "fr", 2000, "auto")
    source = _source(_open(result))
    url = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
    assert source["Mention de la source"] == (
        f"Source : Statistique Canada, {url}, 2026-09-16. Reproduit et diffusé "
        "« tel quel » avec la permission de Statistique Canada."
    )
    assert source["Modifications apportées"].startswith("Aucune :")


async def test_bank_of_canada_and_cc_by_data_flag_the_changes(hosted, fake_call):
    from maplestats_mcp.shared.licences import BOC_TERMS

    payload = {
        "observations": [{"d": "2026-10-01", "FXUSDCAD": "1.3912"}],
        "provenance": {
            "source": "boc",
            "url": "https://www.bankofcanada.ca/valet/x",
            "licence": BOC_TERMS,
        },
    }
    fake_call(payload)
    result = await workbook.export("boc_get_observations", {}, None, None, "en", 2000, "auto")
    source = _source(_open(result))
    assert source["Attribution"].endswith("Changes were made to the data: see Changes made.")
    assert "fxusdcad" in source["Changes made"]
    unchanged = await workbook.export(None, None, [{"value": 1.5}], None, "en", 2000, "auto")
    assert "Changes were made" not in _source(_open(unchanged))["Attribution"]
    assert workbook._attribution("CC BY 4.0", {}, True, None, "en").endswith("Changes made.")
    assert workbook._attribution("CC0 1.0", {}, True, None, "en") == workbook.LABELS["en"]["cite"]
