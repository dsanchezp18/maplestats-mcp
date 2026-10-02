"""reproduce_code's excel language: Power Query M queries.

No Excel runs in CI (or was available when this was written, 2026-10-02),
so each query is checked by a structural M reader below: comments, text
literals and quoted identifiers are lexed as M lexes them, brackets must
balance, every let has its in, no list or record ends in a trailing
comma, every library function called is one Power Query has, and every
step a top-level let names is defined before it is used. The URLs and the
ZIP and SDMX reading steps were checked live (scripts/verify_excel_queries.py).
"""

from __future__ import annotations

import re

import pytest

from maplestats_mcp.modules.reproduce import client
from maplestats_mcp.modules.reproduce.excel import m_text, m_value, render_excel
from maplestats_mcp.modules.reproduce.spec import Code, Filter, Spec
from maplestats_mcp.shared import cache as cache_module


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


# Every library function the queries call, as documented in the Power Query
# M function reference (learn.microsoft.com/powerquery-m).
KNOWN_FUNCTIONS = {
    "Binary.Buffer", "Binary.Decompress", "Binary.Length", "Binary.Range",
    "BinaryFormat.ByteOrder", "BinaryFormat.UnsignedInteger16", "BinaryFormat.UnsignedInteger32",
    "Character.FromNumber", "Csv.Document", "Date.FromText", "Error.Record", "Excel.Workbook",
    "Json.Document", "Json.FromValue", "List.AllTrue", "List.Combine", "List.Contains",
    "List.Count", "List.Distinct", "List.FirstN", "List.Generate", "List.IsEmpty",
    "List.Positions", "List.RemoveNulls", "List.Select", "List.Transform", "List.Zip",
    "Number.From", "Number.FromText", "Number.Power", "Record.Combine", "Record.Field",
    "Record.FieldNames", "Record.FieldOrDefault", "Record.FieldValues", "Record.FromList",
    "Record.SelectFields", "Splitter.SplitTextByCharacterTransition", "Table.AddColumn",
    "Table.Column", "Table.ColumnNames", "Table.FromColumns", "Table.FromRecords",
    "Table.IsEmpty", "Table.PromoteHeaders", "Table.RenameColumns", "Table.SelectColumns",
    "Table.SelectRows", "Table.Skip", "Table.Sort", "Table.TransformColumnNames",
    "Table.TransformColumnTypes", "Table.TransformColumns", "Table.UnpivotOtherColumns",
    "Text.Combine", "Text.Contains", "Text.EndsWith", "Text.From", "Text.FromBinary",
    "Text.Length", "Text.Lower", "Text.Middle", "Text.Split", "Text.StartsWith", "Text.ToBinary",
    "Text.ToList", "Text.Trim", "Uri.BuildQueryString", "Web.Contents", "Web.Page",
    "Xml.Document",
}  # fmt: skip
KNOWN_CONSTANTS = {
    "ByteOrder.LittleEndian", "Compression.Deflate", "MissingField.UseNull", "Order.Ascending",
    "Order.Descending", "QuoteStyle.Csv", "TextEncoding.Utf8",
}  # fmt: skip
KEYWORDS = {
    "let", "in", "each", "if", "then", "else", "and", "or", "not", "try", "otherwise",
    "error", "is", "as", "type", "null", "true", "false", "any", "text", "number", "logical",
    "list", "record", "table", "function", "binary", "date", "nullable",
}  # fmt: skip


def m_tokens(code: str) -> list[str]:
    """M tokens, with comments dropped and literals kept whole."""
    pattern = re.compile(
        r"(?P<skip>\s+|//[^\n]*|/\*.*?\*/)"
        r'|(?P<qid>#"(?:[^"]|"")*")'
        r'|(?P<str>"(?:[^"]|"")*")'
        r"|(?P<hash>#table|#\(.*?\))"
        r"|(?P<num>\d+(?:\.\d+)?)"
        r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
        r"|(?P<op>=>|<>|<=|>=|\.\.|[-+*/&=<>,;()\[\]{}?!@])",
        re.DOTALL,
    )
    tokens, position = [], 0
    while position < len(code):
        match = pattern.match(code, position)
        assert match, f"cannot lex M at {code[position : position + 40]!r}"
        if match.lastgroup != "skip":
            tokens.append(match.group())
        position = match.end()
    return tokens


def check_m(code: str) -> None:
    tokens = m_tokens(code)
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    for previous, token in zip(["", *tokens], tokens, strict=False):
        if token in "([{":
            stack.append(token)
        elif token in pairs:
            assert stack and stack.pop() == pairs[token], f"unbalanced {token}"
            assert previous != ",", f"trailing comma before {token}"
        elif token == "in":
            assert previous != ",", "trailing comma before in"
    assert not stack, f"unclosed {stack}"
    assert tokens.count("let") == tokens.count("in")
    for token in tokens:
        if "." in token and token[0].isupper() and not token[0].isdigit():
            assert token in KNOWN_FUNCTIONS | KNOWN_CONSTANTS, f"unknown M name {token}"
    # Every capitalized name used is a step, function or field defined
    # somewhere in the query (M lets a step name a later one).
    assert tokens[0] == "let" and tokens[-2:] == ["in", "Data"]
    defined = {tokens[i] for i in range(len(tokens) - 1) if tokens[i + 1] == "="}
    for index, token in enumerate(tokens):
        if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", token) or tokens[index - 1] == "[":
            continue
        assert token in defined, f"{token} is used but never defined"
    assert "Data" in defined


def _spec(**changes) -> Spec:
    base = {
        "kind": "csv",
        "url": "https://example.org/data.csv",
        "file_name": "data.csv",
        "method": "m",
    }
    return Spec(**{**base, **changes})


def test_m_text_keeps_user_text_inside_its_literal():
    assert m_text('say "hi"') == '"say ""hi"""'
    assert m_text("a#(lf)b") == '"a#(#)(lf)b"'
    assert m_text("line\nbreak\t") == '"line#(000A)break#(0009)"'
    assert m_text("#tag") == '"#tag"'
    assert m_value({"vectorId": 1, "flag": True, "none": None, "list": ["x"]}) == (
        '[#"vectorId" = 1, #"flag" = true, #"none" = null, #"list" = {"x"}]'
    )


def test_hostile_filter_values_stay_text():
    value = 'x") then error "boom" else ("#(cr)\n// in Data'
    spec = _spec(filters=[Filter("contains", ["name"], value), Filter("is", ["code"], value)])
    code, _ = render_excel(spec, "tool") or ("", [])
    check_m(code)
    assert '"boom"' not in code.replace('""boom""', "")


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("wds_get_cube_metadata", {"product_id": 18100004}),
        ("wds_get_cube_metadata", {"product_id": 18100004, "lang": "fr"}),
        ("wds_get_data_from_vectors", {"vector_ids": [41690973, 41690914], "latest_n": 3}),
        ("sdmx_get_vector_data", {"vector_id": 41690973, "last_n_observations": 6}),
        ("sdmx_get_data", {"product_id": 18100004, "key": "2.2", "last_n_observations": 3}),
        ("boc_get_observations", {"series_names": ["FXUSDCAD", "V39079"], "recent": 5}),
        (
            "socrata_query_dataset_rows",
            {"portal": "calgary", "dataset_id": "848s-4m4z", "limit": 10},
        ),
        ("ckan_datastore_search", {"portal": "on", "resource_id": "abc-123", "limit": 5}),
        ("canadabuys_search_tenders", {"query": "software", "region": "Ontario"}),
        ("canadabuys_search_contracts", {"query": "snow", "min_value": 10000}),
    ],
)
async def test_queries_are_well_formed(tool, arguments):
    result = await client.reproduce(tool, arguments, "excel")
    assert [s.language for s in result.scripts] == ["excel"], result.notes
    code = result.scripts[0].code
    check_m(code)
    assert code.startswith("// ====")
    marks = ["// 0. Setup", "// 1. Read inputs", "// 2. Check inputs", "// 3. Prepare data"]
    positions = [code.index(mark) for mark in marks]
    assert positions == sorted(positions)
    # The row check runs: M is lazy, so a later step must read Checked.
    assert re.search(r"\(\s*Checked,|\(Checked,|Table.ColumnNames\(Checked\)", code)
    assert "Power Query" in result.scripts[0].packages[0]


async def test_table_query_unzips_and_scales():
    result = await client.reproduce("wds_get_cube_metadata", {"product_id": 18100004}, "excel")
    code = result.scripts[0].code
    assert 'Web.Contents("https://www150.statcan.gc.ca/n1/tbl/csv/18100004-eng.zip")' in code
    assert "Binary.Decompress(Packed, Compression.Deflate)" in code
    assert '"metadata"' in code
    assert "[value] * Number.Power(10, [scalar_id])" in code
    french = await client.reproduce(
        "wds_get_cube_metadata", {"product_id": 18100004, "lang": "fr"}, "excel"
    )
    assert 'Delimiter = ";"' in french.scripts[0].code
    assert "valeur_normalisee" in french.scripts[0].code


async def test_vectors_query_posts_the_same_body():
    result = await client.reproduce(
        "wds_get_data_from_vectors", {"vector_ids": [41690973], "latest_n": 3}, "excel"
    )
    code = result.scripts[0].code
    assert 'Json.FromValue({[#"vectorId" = 41690973, #"latestN" = 3]})' in code
    assert '#"Content-Type" = "application/json"' in code
    assert 'Record.Field(item, "object")' in code and '"vectorDataPoint"' in code


async def test_sdmx_data_reads_the_key_not_the_table():
    result = await client.reproduce(
        "sdmx_get_data", {"product_id": 18100004, "key": "2.2", "last_n_observations": 3}
    )
    by_language = {s.language: s.code for s in result.scripts}
    url = "https://www150.statcan.gc.ca/t1/wds/sdmx/statcan/rest/data/DF_18100004/2.2"
    assert f'"{url}?lastNObservations=3"' in by_language["excel"]
    assert "Xml.Document(Raw)" in by_language["excel"]
    assert "get_cansim" in by_language["r"]  # the scripts still read the full table
    assert any("SDMX" in note for note in result.notes)


async def test_filters_and_sort_repeat_the_tool():
    result = await client.reproduce(
        "canadabuys_search_contracts", {"query": "snow removal", "min_value": 10000}, "excel"
    )
    code = result.scripts[0].code
    assert "Text.Contains(Text.Lower(Text.Combine({" in code and '"snow")' in code
    assert "n >= 10000.0" in code
    assert '{{"totalContractValue-valeurTotaleContrat", Order.Descending}}' in code


async def test_all_includes_excel_and_explains_a_missing_query():
    result = await client.reproduce("wds_get_cube_metadata", {"product_id": 18100004})
    assert [s.language for s in result.scripts] == ["r", "python", "stata", "julia", "excel"]
    ivt = await client.reproduce(
        "statcan_census_tables_get_downloads", {"pid": "93658", "release": "2006"}, "excel"
    )
    assert ivt.scripts == []
    assert any("No excel script" in note for note in ivt.notes)


def test_kinds_m_cannot_read_get_no_query():
    for kind in ("feed", "ivt", "file", "zip"):
        assert render_excel(_spec(kind=kind), "tool") is None
    assert render_excel(_spec(native={"python": Code([], "x")}), "tool") is None


def test_other_kinds_are_well_formed():
    specs = [
        _spec(kind="xlsx", sheet="Table 1", skip_rows=1),
        _spec(kind="html_table", html_table_index=2),
        _spec(kind="json", records_path=["result", "records"]),
        _spec(kind="json", records_path=["features"], record_field="attributes"),
        _spec(kind="json", records_path=["seriesDetail"], records_dict=True),
        _spec(kind="json", columnar=True),
        _spec(kind="json", single_object=True),
        _spec(kind="json", records_path=["d"], name_value=True),
        _spec(kind="csv", delimiter=";", na_values=["NULL", "--"], header_prefix="#"),
        _spec(kind="csv", post_form={"a": "b"}, headers={"Accept": "text/csv"}),
        _spec(kind="zip_csv", member_pattern="data"),
    ]
    for spec in specs:
        rendered = render_excel(spec, "tool")
        assert rendered is not None, spec
        check_m(rendered[0])


@pytest.mark.parametrize(
    "bad",
    [
        'let\n    Data = Text.Lowr("x")\nin\n    Data',
        "let\n    Data = Number.From((1)\nin\n    Data",
        "let\n    Data = {1, 2,}\nin\n    Data",
        "let\n    Data = Missing\nin\n    Data",
        'let\n    Data = "open\nin\n    Data',
        "let\n    Raw = 1,\nin\n    Data",
    ],
)
def test_the_m_checker_catches_mistakes(bad):
    with pytest.raises(AssertionError):
        check_m(bad)
