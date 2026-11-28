"""The chat demo's "Download CSV" writes a file a spreadsheet opens safely (review, 2026-11-26).

A series title, unit or status comes from an upstream source, and a cell that starts with
`=`, `+`, `-`, `@`, a tab or a carriage return is run as a formula by Excel and LibreOffice.
The file also has to start with a UTF-8 byte order mark, or Excel reads the accents of a
French title as Windows-1252. The page's CSV helpers sit between two marker comments; this
runs that part in node, as chat/tests/test_exports.py does for the page's STRINGS.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "chat" / "static" / "index.html"
BOM = "\N{BYTE ORDER MARK}"
BEGIN = "  // ---- CSV text (tests/test_review3_chat_csv.py runs this part in node) ----"
END = "  // ---- end CSV text ----"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

_DRIVER = """
const { header, rows } = JSON.parse(require("fs").readFileSync(0, "utf8"));
(async () => {
  const text = csvText(header, rows);
  const bytes = new Uint8Array(await new Blob([text], { type: "text/csv" }).arrayBuffer());
  process.stdout.write(JSON.stringify({ text, start: Array.from(bytes.slice(0, 3)) }));
})();
"""


def _csv(header: list[str], rows: list[list]) -> dict:
    page = PAGE.read_text(encoding="utf-8")
    assert BEGIN in page and END in page, "the CSV helpers lost their marker comments"
    helpers = page[page.index(BEGIN) : page.index(END)]
    result = subprocess.run(
        [shutil.which("node") or "node", "-e", helpers + _DRIVER],
        input=json.dumps({"header": header, "rows": rows}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
    )
    return json.loads(result.stdout)


def _body(rows: list[list]) -> list[str]:
    """The file's lines under a one-column header, after the byte order mark."""
    text = _csv(["Cell"], rows)["text"]
    assert text.startswith(BOM + "Cell\n")
    return text[len(BOM + "Cell\n") :].split("\n")


def test_the_file_starts_with_a_utf8_byte_order_mark():
    result = _csv(["Série", "Période"], [["Taux de chômage", "2026-10"]])
    assert result["start"] == [0xEF, 0xBB, 0xBF]
    assert result["text"] == BOM + "Série,Période\nTaux de chômage,2026-10"


def test_a_cell_that_would_run_as_a_formula_gets_a_leading_apostrophe():
    rows = [
        ["=SUM(A1:A9)"],
        ["+1+1"],
        ["-2+3"],
        ["@SUM(1)"],
        ["\t=1"],
        ["-"],
        ['=HYPERLINK("http://example.org","x")'],
        ["=1,2"],
    ]
    assert _body(rows) == [
        "'=SUM(A1:A9)",
        "'+1+1",
        "'-2+3",
        "'@SUM(1)",
        "'\t=1",
        "'-",
        '"\'=HYPERLINK(""http://example.org"",""x"")"',
        '"\'=1,2"',
    ]
    # A carriage return both starts a formula and forces quotes.
    assert _csv(["Cell"], [["\r=1"]])["text"].endswith('\n"\'\r=1"')


def test_a_plain_number_stays_a_number():
    rows = [[-12.5], [7], [0], [1e-7], ["-12.5"], ["+3"], ["-0.5e3"], ["-.5"], [None], [""]]
    assert _body(rows) == ["-12.5", "7", "0", "1e-7", "-12.5", "+3", "-0.5e3", "-.5", "", ""]


def test_a_number_written_for_reading_stays_a_number():
    # Thousands commas in groups of three, a decimal part and a percent sign. A cell with a
    # comma is quoted, which is the CSV's business, not the apostrophe's.
    rows = [
        ["-1,234.5"],
        ["-5%"],
        ["-1,234,567"],
        ["-12.5%"],
        ["-.5%"],
        ["+1,000"],
        ["1,234.5%"],
        ["-0%"],
    ]
    assert _body(rows) == [
        '"-1,234.5"',
        "-5%",
        '"-1,234,567"',
        "-12.5%",
        "-.5%",
        '"+1,000"',
        '"1,234.5%"',
        "-0%",
    ]


def test_anything_else_that_starts_like_a_number_is_still_neutralized():
    rows = [
        ["-Infinity"],
        ["+Infinity"],
        ["-1+2"],
        ["-1,23"],
        ["-1,2345"],
        ["-1,234.5+1"],
        ["-5%+1"],
        ["-%"],
        ["-,5"],
        ["-1,234.5 USD"],
        ["=1%"],
        ["@5%"],
        ["-5%\t"],
    ]
    assert _body(rows) == [
        "'-Infinity",
        "'+Infinity",
        "'-1+2",
        '"\'-1,23"',
        '"\'-1,2345"',
        '"\'-1,234.5+1"',
        "'-5%+1",
        "'-%",
        '"\'-,5"',
        '"\'-1,234.5 USD"',
        "'=1%",
        "'@5%",
        "'-5%\t",
    ]


def test_text_that_only_contains_a_formula_character_is_left_alone():
    rows = [["Mean = 5"], ["x-1"], ["a@b.ca"], [" =1"], ["Chômage"]]
    assert _body(rows) == ["Mean = 5", "x-1", "a@b.ca", " =1", "Chômage"]


def test_quotes_commas_and_line_breaks_are_quoted():
    rows = [["a,b"], ['say "hi"'], ["one\ntwo"], ["one\rtwo"], ["plain"]]
    lines = _csv(["Cell"], rows)["text"].split("\n")
    assert lines[1] == '"a,b"'
    assert lines[2] == '"say ""hi"""'
    assert lines[3] == '"one'
    assert lines[4] == 'two"'
    assert _csv(["Cell"], [["one\rtwo"]])["text"].endswith('"one\rtwo"')
    assert lines[-1] == "plain"


def test_the_download_hands_the_text_to_a_utf8_blob():
    page = PAGE.read_text(encoding="utf-8")
    assert 'new Blob([csv], { type: "text/csv;charset=utf-8" })' in page
    assert "csvText(" in page[page.index("download.onclick") :]
