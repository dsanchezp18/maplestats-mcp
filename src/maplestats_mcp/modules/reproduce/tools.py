"""reproduce_code: the same data as an R, Python, Stata or Julia script or an
Excel Power Query; reproduce_workbook: the data as a formatted Excel workbook."""

from __future__ import annotations

from typing import Any, Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.reproduce import client, workbook
from maplestats_mcp.modules.reproduce.schemas import (
    ExcelWorkbook,
    LanguageChoice,
    ReproductionCode,
)


@tool
async def reproduce_code(
    tool_name: str, arguments: dict[str, Any], language: LanguageChoice = "all"
) -> ReproductionCode:
    """Get R, Python, Stata, Julia or Excel Power Query code that refetches the same data.

    Use for: moving any data tool's result into an analysis script
    reproducibly. Pass the tool name and the arguments you called it
    with; the server writes the scripts, ready to run. Tools that return
    documents or text (StatCan articles and Daily releases, Gazette
    notices) get no script. It rebuilds the exact request: from
    the arguments (StatCan tables via cansim, Beyond 20/20 via canivt,
    Valet, Socrata, CKAN), or by recording the upstream request the tool
    makes (every query parameter, POST body and header). Where the tool
    filters a downloaded file itself (CER, GC InfoBase, CIHI,
    IRCC, PHAC Health Infobase, IP Horizons patents) or parses HTML tables
    (CFIA), the script repeats those steps. Scripts
    follow a header plus numbered sections (setup, read, check, prepare),
    save downloads under data/raw/, and clean names, text and numbers;
    Python uses polars, Julia TidierFiles, Stata import delimited (JSON
    and filtered files go through Stata's built-in Python). language
    "excel" is a Power Query M query to paste into Excel (Get Data > Blank
    Query > Advanced Editor): it calls the same URL, filters and cleans the
    same way, and refreshes inside Excel, with nothing to install. notes
    say what a script cannot repeat and why a language is missing;
    language picks one.
    Keywords: reproducible, R code, Python code, Stata do-file, Julia,
    Excel, Power Query, M query, script, cansim, download data,
    replication, code generation.
    Mots-clés : reproductible, code R, code Python, Stata, Julia, Excel,
    Power Query, requête M, script, télécharger les données, réplication,
    génération de code.
    """
    return await client.reproduce(tool_name, arguments, language)


@tool
async def reproduce_workbook(
    tool_name: str | None = None,
    arguments: dict[str, Any] | None = None,
    rows: list[dict[str, Any]] | None = None,
    title: str | None = None,
    max_rows: int = workbook.DEFAULT_ROWS,
    delivery: Literal["auto", "base64", "file"] = "auto",
    lang: Literal["en", "fr"] = "en",
) -> ExcelWorkbook:
    """Get any data tool's result as a formatted Excel workbook (.xlsx).

    Use for: handing data to someone who works in Excel. Pass the tool
    name and its arguments (the tool runs once), or rows you already have.
    The workbook holds the rows, cleaned as the R scripts clean them, in
    one Excel table with a frozen header, number formats and fitted
    column widths; a native, editable line or bar chart when the rows are
    a time series or a short list; and a Source sheet with the call, the
    source URL, dates, licence and attribution. lang sets the labels
    (English or French). A hosted server returns the file as base64
    (decode it and save it as file_name), so keep max_rows small (default
    2,000, at most 20,000; the file is capped at 2 MB); a local server
    saves it to your Downloads folder (or MAPLE_EXPORT_DIR) instead. For
    a refreshable query over the full data, use reproduce_code with
    language "excel".
    Keywords: Excel, workbook, spreadsheet, xlsx, export, download table,
    chart, formatted table, save data, Excel file.
    Mots-clés : Excel, classeur, tableur, chiffrier, xlsx, exporter,
    télécharger le tableau, graphique, fichier Excel, enregistrer les
    données.
    """
    return await workbook.export(tool_name, arguments, rows, title, lang, max_rows, delivery)
