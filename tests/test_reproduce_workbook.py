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
        async def call(tool, arguments):
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
