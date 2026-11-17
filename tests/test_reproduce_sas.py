"""reproduce_code's sas language: SAS programs.

No SAS runs in CI (none was available when this was written, 2026-11-17), so
each program is checked by a small structural reader: strings and comments
are lexed as SAS lexes them, then every DATA and PROC step must end with RUN
or QUIT, DO and END must balance, and every %MACRO needs its %MEND. The tests
also check what the program says for each source kind, and that text from the
caller never leaves its string literal.
"""

from __future__ import annotations

import re

import pytest

from maplestats_mcp.modules.reproduce import client
from maplestats_mcp.modules.reproduce.sas import render_sas, sas_name
from maplestats_mcp.modules.reproduce.spec import Code, Filter, Spec

URL = "https://example.org/data/table.csv"


def _strip_strings_and_comments(code: str) -> str:
    """The code with comments and quoted text removed, raising on an open one."""
    out: list[str] = []
    i = 0
    while i < len(code):
        if code.startswith("/*", i):
            end = code.find("*/", i + 2)
            assert end != -1, "unterminated comment"
            i = end + 2
        elif code[i] in "'\"":
            quote = code[i]
            j = i + 1
            while True:
                end = code.find(quote, j)
                assert end != -1, f"unterminated {quote} string"
                if code.startswith(quote * 2, end):  # a doubled quote is one quote
                    j = end + 2
                    continue
                break
            out.append(" ")
            i = end + 1
        else:
            out.append(code[i])
            i += 1
    return "".join(out)


def _check_structure(code: str) -> None:
    bare = _strip_strings_and_comments(code)
    statements = [s.strip().lower() for s in bare.split(";")]
    opened = 0
    for statement in statements:
        first = statement.split(None, 1)[0] if statement.split() else ""
        if (
            re.match(r"(data|proc)\b", statement)
            and not statement.startswith("proc http")
            or statement.startswith("proc http")
        ):
            opened += 1
        elif first in ("run", "quit"):
            opened -= 1
    assert opened == 0, "a DATA or PROC step is not closed by RUN or QUIT"
    words = re.findall(r"\b(do|end)\b(?!\s*=)", bare.lower())  # not set ... end=last
    assert words.count("do") == words.count("end"), "DO and END do not balance"
    assert len(re.findall(r"%macro\b", bare, re.IGNORECASE)) == len(
        re.findall(r"%mend\b", bare, re.IGNORECASE)
    )
    assert bare.count("(") == bare.count(")"), "parentheses do not balance"
    assert bare.count("{") == bare.count("}"), "braces do not balance"


def _render(spec: Spec, tool: str = "t") -> str:
    rendered = render_sas(spec, tool)
    assert rendered is not None
    code, packages = rendered
    _check_structure(code)
    assert packages and packages[0].startswith("Base SAS")
    return code


def _csv(**overrides) -> Spec:
    fields = {"kind": "csv", "url": URL, "file_name": "table.csv", "method": "from arguments"}
    return Spec(**{**fields, **overrides})


def test_csv_layout_and_text_columns():
    code = _render(_csv(filters=[Filter("contains", ["Title"], "Water")]))
    assert code.lstrip().startswith("/* ====")
    marks = ["0. Setup", "1. Read inputs", "2. Check inputs", "3. Prepare data"]
    positions = [code.index(mark) for mark in marks]
    assert positions == sorted(positions)
    assert "proc http url='https://example.org/data/table.csv' method=\"get\"" in code
    assert "length v1-v&ncols. $32767;" in code  # every column as text
    assert "dsd delimiter=','" in code
    assert "work.maple_data" in code
    assert "%clean_data" in code and "best32." in code
    assert "if (index(lowcase(title), 'water') > 0);" in code


def test_the_downloaded_file_is_checked_and_empty_results_stop():
    code = _render(_csv())
    assert "&sys_prochttp_status_code. ne 200" in code
    assert "if &row_count. = 0" in code and "abort cancel" in code


def test_delimiters_title_lines_and_blank_line_stop():
    code = _render(_csv(delimiter=";", skip_rows=3, stop_at_blank=True, na_values=["NULL"]))
    assert "delimiter=';'" in code
    assert "firstobs=4 obs=4" in code and "firstobs=5" in code
    assert "if lengthn(strip(_infile_)) = 0 then stop;" in code
    assert "in ('NULL')" in code
    tab = _render(_csv(delimiter="\t"))
    assert "delimiter='09'x" in tab


def test_header_prefix_sort_and_post_requests():
    code = _render(
        _csv(
            header_prefix="#",
            sort_by="Event ID",
            sort_descending=True,
            post_json={"a": 1},
            headers={"Accept": "text/csv"},
        )
    )
    assert "if substr(header, 1, 1) = '#' then" in code
    assert "by descending event_id;" in code
    assert 'method="post"' in code and "in='{\"a\": 1}'" in code
    assert "headers 'Accept'='text/csv' 'Content-Type'='application/json';" in code


def test_every_filter_operator():
    spec = _csv(
        filters=[
            Filter("terms", ["Title", "Body"], ["water", ["plan", "plans"]]),
            Filter("is", ["Place"], " Alberta "),
            Filter("in", ["Place"], ["AB", "BC"]),
            Filter("starts", ["Year"], "20"),
            Filter("ge", ["Value"], 1000),
            Filter("le", ["Date"], "2024-01-01"),
        ]
    )
    code = _render(spec)
    assert "index(lowcase(catx(' ', title, body)), 'water') > 0" in code
    assert "(index(lowcase(catx(' ', title, body)), 'plan') > 0 or" in code
    assert "lowcase(strip(place)) = 'alberta'" in code
    assert "lowcase(strip(place)) in ('ab', 'bc')" in code
    assert "year =: '20'" in code
    # A missing number is smaller than every number in SAS, so it is left out.
    assert "not missing(input(value, ?? best32.)) and input(value, ?? best32.) >= 1000" in code
    assert "not missing(date) and date <= '2024-01-01'" in code


def test_text_from_the_caller_stays_inside_its_string():
    nasty = "x'; %let boom = 1; &danger \n*/ data _null_; run; /*"
    spec = _csv(
        url="https://example.org/a?b=1&c=%25'x",
        filters=[Filter("contains", ["Title"], nasty), Filter("in", ["Place"], [nasty])],
        na_values=[nasty],
        title=nasty,
        details=[nasty],
        header_prefix=nasty,
    )
    code = _render(spec)
    # The structural reader above already refused an open string or comment.
    assert "'x''; %let boom = 1;" in code  # one literal, its quote doubled
    assert "%let boom" not in _strip_strings_and_comments(code)
    assert "&danger" not in _strip_strings_and_comments(code)


def test_zip_csv_picks_the_data_file_from_the_archive():
    spec = Spec(kind="zip_csv", url=URL, file_name="a.zip", method="m")
    code = _render(spec)
    assert 'filename zipin zip "data/raw/a.zip";' in code
    assert "index(lowcase(member), 'metadata') = 0" in code
    assert 'infile zipin("&member.")' in code
    pattern = _render(
        Spec(kind="zip_csv", url=URL, file_name="a.zip", method="m", member_pattern="obs")
    )
    assert "index(member, 'obs') > 0" in pattern


def test_zip_and_file_download_only():
    archive = _render(Spec(kind="zip", url=URL, file_name="a.zip", method="m"))
    assert "work._members" in archive and "2. Check inputs" not in archive
    plain = _render(Spec(kind="file", url=URL, file_name="a.txt", method="m"))
    assert "proc http" in plain and "3. Prepare data" not in plain


def test_xlsx_sheet_range_and_numbers_as_text_in_filters():
    code = _render(
        Spec(
            kind="xlsx",
            url=URL,
            file_name="a.xlsx",
            method="m",
            sheet="Table 1",
            filters=[Filter("is", ["Code"], "7")],
        )
    )
    assert "dbms=xlsx" in code and "sheet='Table 1';" in code
    assert "strip(vvalue(code))" in code  # Excel numbers are numeric variables
    ranged = _render(
        Spec(kind="xlsx", url=URL, file_name="a.xlsx", method="m", sheet="T", skip_rows=4)
    )
    assert 'range="T$A5:XFD1048576"' in ranged


@pytest.mark.parametrize(
    "spec",
    [
        Spec(kind="json", url=URL, file_name="a.json", method="m"),
        Spec(kind="sdmx", url=URL, file_name="a.xml", method="m"),
        Spec(kind="html_table", url=URL, file_name="a.html", method="m"),
        Spec(kind="feed", url=URL, file_name="a.xml", method="m"),
        Spec(kind="none", url="", file_name="", method="none"),
        # No sheet name to build the range from.
        Spec(kind="xlsx", url=URL, file_name="a.xlsx", method="m", skip_rows=2),
        Spec(kind="xlsx", url=URL, file_name="a.xlsx", method="m", sheet='a"b'),
        # A Python step means the generic read is not enough.
        Spec(kind="csv", url=URL, file_name="a.csv", method="m", prepare={"python": Code([], "x")}),
        Spec(kind="csv", url=URL, file_name="a.csv", method="m", native={"python": Code([], "x")}),
    ],
)
def test_sources_sas_cannot_read_get_no_program(spec):
    assert render_sas(spec, "t") is None


def test_an_r_only_native_read_does_not_block_sas():
    # The StatCan table builder gives R a cansim call; the others read the CSV ZIP.
    spec = Spec(
        kind="zip_csv", url=URL, file_name="a.zip", method="m", native={"r": Code(["cansim"], "x")}
    )
    assert "infile zipin" in _render(spec)


def test_sas_name_matches_the_programs_rule():
    assert sas_name("REF_DATE") == "ref_date"
    assert sas_name("Value (CAD)") == "value_cad"
    assert sas_name("2020 total") == "x2020_total"
    assert sas_name("???") == "x"
    assert len(sas_name("a" * 50)) == 32


def test_cleaning_keeps_codes_and_leading_zeros_as_text():
    code = _render(_csv())
    assert "coordinate|vector" in code and "naics" in code
    assert "^-?0[0-9]" in code
    assert "lengthn(__text{__i}) > 32" in code


@pytest.fixture
def no_tool_run(monkeypatch):
    # The full-table builder reads only the arguments, so the tool's run is
    # replaced and no request leaves the test.
    async def run_tool(name, args, lang="en"):
        return {}, []

    monkeypatch.setattr(client, "_run_tool", run_tool)


async def test_reproduce_returns_a_sas_script_for_a_table(no_tool_run):
    result = await client.reproduce("wds_get_full_table_download", {"product_id": 18100004}, "sas")
    assert [s.language for s in result.scripts] == ["sas"]
    assert "work.maple_data" in result.scripts[0].code
    assert not any(n.startswith("No sas script") for n in result.notes)


async def test_reproduce_explains_a_source_sas_cannot_read(no_tool_run):
    result = await client.reproduce("wds_get_full_table_download", {"product_id": 18100004}, "all")
    assert "sas" in [s.language for s in result.scripts]
    # A WDS vector answer is JSON, which SAS has no reader for here.
    vectors = {"vector_ids": [41690973], "latest_n": 3}
    sdmx = await client.reproduce("wds_get_data_from_vectors", vectors, "all")
    assert "sas" not in [s.language for s in sdmx.scripts]
    assert any(n.startswith("No sas script: SAS reads delimited text") for n in sdmx.notes)
    assert not any("Julia has no" in n and "sas" in n for n in sdmx.notes)
    french = await client.reproduce("wds_get_data_from_vectors", vectors, "all", "fr")
    assert any(n.startswith("Pas de script sas\xa0: SAS ne lit que") for n in french.notes)


async def test_summary_leaves_sas_out_with_a_note(no_tool_run):
    result = await client.reproduce(
        "wds_get_full_table_download", {"product_id": 18100256}, "all", summary=True
    )
    assert "sas" not in [s.language for s in result.scripts]
    assert any("No stata, julia, sas" in n or "sas" in n for n in result.notes)
