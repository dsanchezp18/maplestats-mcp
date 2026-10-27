"""Client tests on HTML and rows taken from CBSA's tariff pages and files (2026-10-26).

The Access reader is replaced by rows copied from 01-99-2026-2-eng.accdb
and -fra.accdb (test_accdb.py covers the reader itself); everything after
it (column matching, Parquet, DuckDB queries, editions) runs for real.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from maplestats_mcp.modules.cbsa_tariff import client, constants
from maplestats_mcp.modules.cbsa_tariff.accdb import Column
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

MENU_2026 = "https://www.cbsa-asfc.gc.ca/trade-commerce/tariff-tarif/2026/menu-eng.html"
MENU_2026_FR = "https://www.cbsa-asfc.gc.ca/trade-commerce/tariff-tarif/2026/menu-fra.html"
ZIP_2026_2 = (
    "https://www.cbsa-asfc.gc.ca/trade-commerce/tariff-tarif/2026/01-99/01-99-2026-2-eng.zip"
)


def _panel(label: str, when: str, stem: str, effective: str = "Effective date") -> str:
    return f"""
<section class="panel panel-default">
    <header class="panel-heading">
        <h2 class="panel-title"><span style="font-size:130%">{label}</span>
        <span class="pull-right">{effective}&nbsp;: {when}</span></h2>
    </header>
    <div class="panel-body"><ul>
        <li><a href="/trade-commerce/tariff-tarif/2026/html/tblmod-1-eng.html">By chapter</a></li>
        <li>Customs Tariff complete<ul>
            <li><a href="/trade-commerce/tariff-tarif/2026/01-99/{stem}.pdf">PDF</a></li>
            <li><a href="/trade-commerce/tariff-tarif/2026/01-99/{stem}.zip">Access</a></li>
            <!--<li><a href="/trade-commerce/tariff-tarif/2026/cadex-eng.html">CADEX</a></li>-->
        </ul></li>
    </ul></div>
</section>"""


MENU_HTML = (
    "<html><body><main>"
    + _panel("T2026-2", "2026-09-01", "01-99-2026-2-eng")
    + _panel("T2026-1", "2026-08-06", "01-99-2026-1-eng")
    # The 2023 page had an edition inside a comment; it is not offered.
    + "<!--"
    + _panel("T2026-9", "2026-07-01", "01-99-2026-9-eng")
    + "-->"
    + _panel("T2026", "2026-01-01", "01-99-2026-0-eng")
    + "</main></body></html>"
)
MENU_HTML_FR = (
    "<html><body>"
    + _panel("T2026-2", "2026-09-01", "01-99-2026-2-fra", "Date d'entrée en vigueur")
    + "</body></html>"
)

# Column names as access-parser returns them: French names with U+FFFD for accents.
NAMES_EN = ["TARIFF", "EFF_DATE", "CHANGE", "SUB_CHAP", "DESC1", "DESC2", "DESC3", "FOOTNOTE",
            "UOM", "MFN", "General Tariff", "GPT", "UST", "MXT", "CEUT", "CPTPT", "CPUKT",
            "row_id"]  # fmt: skip
NAMES_FR = ["TARIF", "DATE_EFF", "CHANGEMENT", "SOUS_CHAP", "DESC1", "DESC2", "DESC3",
            "NOTE DE BAS DE PAGE", "UDM", "NPF", "Tarif g�n�ral", "TPG", "T�U",
            "TMX", "TCUE", "TPTGP", "TUKGP", "row_id"]  # fmt: skip
D = datetime(2026, 9, 1)
OLD = datetime(1998, 1, 1)
ROWS_EN: list[list[Any]] = [
    ["87.03", OLD, 0.0, None, ("Motor cars and other motor vehicles principally designed for "
     "the transport of persons (other than those of heading 87.02), including station wagons "
     "and racing cars."), None, None, None, "", "", "", "", "", "", "", "", "", 1],
    ["8703.80.00", D, 1.0, None, "Other vehicles, with only electric motor for propulsion",
     None, None, None, "", "6.1 %", "35%", "6 %", "Free", "Free", "Free", "Free", "Free", 2],
    ["8703.80.00.10", D, 0.0, None, "New", None, None, None, "NMB", "", "", "", "", "", "",
     "", "", 3],
    ["0401.10.10", D, 1.0, None, "Within access commitment", None, None, None, "", "7.5 %",
     "35%", "7.5 %", "Free", "", "Free", "Free", "Free", 4],
    ["9913.00.00", D, 1.0, None, "The following pharmaceutical ingredients;\r\nAbacavir, Dol",
     "asetron, Domazoline", None, None, "", "Free", "35%", "Free", "Free", "Free", "Free",
     "Free", "Free", 5],
    ["1702.20.00", D, 0.0, None, "Maple sugar and maple syrup", None, None, None, "", "Free",
     "35%", "Free", "Free", "Free", "Free", "Free", "Free", 6],
    ["8479.89.10", D, 0.0, None, "Artificial fog or smoke generators;\x0bAutomatic loaders",
     None, None, None, "-", "Free", "35%", "Free", "Free", "Free", "Free", "Free", "Free", 7],
    # 5206.41.00.00 is in the 2026-2 file twice, identical but for row_id.
    ["5206.41.00.00", D, 0.0, None, "Measuring per single yarn 714.29 decitex", None, None,
     None, "KGM", "Free", "", "", "", "", "", "", "", 8],
    ["5206.41.00.00", D, 0.0, None, "Measuring per single yarn 714.29 decitex", None, None,
     None, "KGM", "Free", "", "", "", "", "", "", "", 8],
    # Rows whose number carries a stray line break (7217.20.00.5 in 2026-2).
    ["7217.20.00.5\n", D, 0.0, None, "Other", None, None, None, "", "", "", "", "", "", "", "",
     "", 9],
]  # fmt: skip
ROWS_FR: list[list[Any]] = [
    ["1702.20.00", D, 0.0, None, "Sucre et sirop d'érable", None, None, None, "", "En fr.",
     "35 %", "En fr.", "En fr.", "En fr.", "En fr.", "En fr.", "En fr.", 6],
    ["2711.12.90", D, 1.0, None, "Autres", None, None, None, "", "En fr.", "35 %", "En fr.",
     "En fr.", "En fr.", "En fr.", "En fr.", "En fr.", 10],
]  # fmt: skip


class FakeTable:
    """Stands in for accdb.AccessTable: the file's name says which rows it holds."""

    def __init__(self, path: Path, table: str) -> None:
        assert table == "TPHS"
        french = path.read_bytes() == b"fr"
        names = NAMES_FR if french else NAMES_EN
        self.columns = [Column(n, 10, i, i, False, 0) for i, n in enumerate(names)]
        self._rows = ROWS_FR if french else ROWS_EN

    def rows(self):
        return iter(self._rows)


def _zip(content: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("01-99-2026-2-eng.accdb", content)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MAPLE_CBSA_TARIFF_CACHE_DIR", str(tmp_path / "tariff"))
    monkeypatch.setattr(client, "AccessTable", FakeTable)
    monkeypatch.setattr(client, "_this_year", lambda: 2026)
    client._downloads.clear()


def _serve(httpx_mock, *, french: bool = False) -> None:
    if french:
        httpx_mock.add_response(url=MENU_2026_FR, text=MENU_HTML_FR)
        httpx_mock.add_response(url=ZIP_2026_2.replace("-eng", "-fra"), content=_zip(b"fr"))
    else:
        httpx_mock.add_response(url=MENU_2026, text=MENU_HTML)
        httpx_mock.add_response(url=ZIP_2026_2, content=_zip(b"en"))


def test_menu_skips_commented_editions_and_reads_links():
    editions = client.parse_menu(MENU_HTML, 2026, "en")
    assert [e.edition for e in editions] == ["2026-2", "2026-1", "2026"]
    latest = editions[0]
    assert latest.effective_date == date(2026, 9, 1)
    assert latest.access_zip_url == ZIP_2026_2
    assert latest.pdf_url and latest.pdf_url.endswith("01-99-2026-2-eng.pdf")
    assert latest.html_url and "/html/" in latest.html_url
    french = client.parse_menu(MENU_HTML_FR, 2026, "fr")
    assert french[0].effective_date == date(2026, 9, 1)


def test_french_column_names_with_replacement_characters_still_match():
    fields, rates = client._column_index(NAMES_FR)
    assert fields["tariff"] == 0 and fields["footnote"] == 7 and fields["uom"] == 8
    assert rates["MFN"] == 9 and rates["GT"] == 10 and rates["UST"] == 12
    assert rates["CEUT"] == 14 and rates["CPUKT"] == 16


def test_2018_column_names():
    _, rates = client._column_index(["TARIFF", "MFN", "GT", "MT", "MUST", "UAT"])
    assert set(rates) == {"MFN", "GT", "MXT", "MUST", "UAT"}


@pytest.mark.parametrize(
    ("text", "percent"),
    [("Free", 0.0), ("En fr.", 0.0), ("6.5 %", 6.5), ("35%", 35.0), ("6,5 %", 6.5),
     ("$1.23/kg", None), ("5 % but not less than 2¢/kg", None)],
)  # fmt: skip
def test_percent(text: str, percent: float | None):
    assert client.percent_of(text) == percent


async def test_lookup_tariff_item_with_heading_and_children(httpx_mock):
    _serve(httpx_mock)
    result = await client.lookup("8703.80.00", edition="latest")
    assert result.edition.edition == "2026-2"
    item = result.item
    assert item is not None and item.level == "tariff_item"
    assert item.mfn == "6.1 %" and item.general == "35%"
    assert [r.code for r in item.rates][:3] == ["MFN", "GT", "GPT"]
    assert {r.code: r.percent for r in item.rates}["GPT"] == 6.0
    assert item.rates[0].name == "Most-Favoured-Nation Tariff"
    assert item.effective_date == date(2026, 9, 1) and item.changed_in_edition
    assert [a.tariff for a in result.ancestors] == ["87.03"]
    assert [c.tariff for c in result.children] == ["8703.80.00.10"]
    assert result.children[0].unit_of_measure == "NMB"
    assert result.provenance.as_of == datetime(2026, 9, 1)
    assert result.provenance.url == ZIP_2026_2


async def test_parquet_is_reused_and_cleans_rows(httpx_mock):
    _serve(httpx_mock)
    await client.lookup("8703", edition="2026-2")
    # No second download: the zip response is registered once.
    result = await client.lookup("8479.89.10", edition="T2026-2")
    assert result.provenance.cached
    item = result.item
    assert item is not None
    assert item.description == "Artificial fog or smoke generators;\nAutomatic loaders"
    assert item.unit_of_measure is None
    long = await client.lookup("9913.00.00", edition="2026-2")
    assert long.item is not None
    assert long.item.description == (
        "The following pharmaceutical ingredients;\nAbacavir, Dolasetron, Domazoline"
    )
    stray = await client.lookup("7217.20.00.5", edition="2026-2")
    assert stray.item is not None and stray.item.tariff == "7217.20.00.5"


async def test_duplicate_rows_are_dropped(httpx_mock):
    _serve(httpx_mock)
    result = await client.search("decitex", edition="2026-2")
    assert result.total_matches == 1


async def test_lookup_of_a_missing_line_under_a_heading(httpx_mock):
    _serve(httpx_mock)
    result = await client.lookup("8703.80.99", edition="2026-2")
    assert result.item is None and result.note
    assert [a.tariff for a in result.ancestors] == ["87.03"]
    with pytest.raises(NotFound):
        await client.lookup("0000.00", edition="2026-2")


async def test_search_words_chapter_and_limit(httpx_mock):
    _serve(httpx_mock)
    result = await client.search("MAPLE syrup", edition="2026-2")
    assert [line.tariff for line in result.lines] == ["1702.20.00"]
    assert result.lines[0].mfn == "Free"
    chapter = await client.search("", chapter="87", limit=1, edition="2026-2")
    assert chapter.chapter == "87"
    assert chapter.total_matches == 3 and chapter.returned_count == 1
    assert chapter.provenance.limits and "1 of 3" in chapter.provenance.limits
    padded = await client.search("", chapter="4", edition="2026-2")
    assert [line.tariff for line in padded.lines] == ["0401.10.10"]


async def test_french_file_and_accent_free_search(httpx_mock):
    _serve(httpx_mock, french=True)
    result = await client.search("sirop d'erable", lang="fr", edition="2026-2")
    assert [line.tariff for line in result.lines] == ["1702.20.00"]
    line = result.lines[0]
    assert line.mfn == "En fr." and line.general == "35 %"
    assert line.rates[0].percent == 0.0
    assert line.rates[0].name == "Tarif de la nation la plus favorisée"
    assert {r.code for r in line.rates} >= {"UST", "CEUT", "CPUKT"}


async def test_edition_by_date(httpx_mock):
    httpx_mock.add_response(url=MENU_2026, text=MENU_HTML)
    chosen = await client.resolve_edition("2026-08-20", "en")
    assert chosen.edition == "2026-1"
    first = await client.resolve_edition("2026", "en")
    assert first.edition == "2026"


async def test_date_before_this_years_first_edition_reads_last_year(httpx_mock):
    # Only the 2025 page is read for a 2025 date.
    httpx_mock.add_response(url=MENU_2026.replace("2026", "2025"), text=MENU_HTML.replace(
        "2026", "2025"))  # fmt: skip
    chosen = await client.resolve_edition("2025-12-31", "en")
    assert chosen.edition == "2025-2" and chosen.year == 2025


async def test_missing_year_page_is_empty_not_an_error(httpx_mock):
    httpx_mock.add_response(url=MENU_2026, text=MENU_HTML)
    httpx_mock.add_response(url=MENU_2026.replace("2026", "2025"), status_code=404)
    editions = await client.list_editions()
    assert [e.edition for e in editions.editions] == ["2026-2", "2026-1", "2026"]
    assert editions.years == [2026, 2025]


async def test_input_errors(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.lookup("cheese")
    with pytest.raises(InvalidInput):
        await client.lookup("1")
    with pytest.raises(InvalidInput):
        await client.search("")
    with pytest.raises(InvalidInput):
        await client.search("cheese", limit=500)
    with pytest.raises(InvalidInput):
        await client.search("cheese", chapter="100")
    with pytest.raises(InvalidInput):
        await client.list_editions(year=2010)
    with pytest.raises(InvalidInput):
        await client.resolve_edition("next week", "en")
    httpx_mock.add_response(url=MENU_2026, text=MENU_HTML)
    with pytest.raises(NotFound):
        await client.resolve_edition("2026-9", "en")


async def test_zip_without_a_database(httpx_mock):
    httpx_mock.add_response(url=MENU_2026, text=MENU_HTML)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "moved")
    httpx_mock.add_response(url=ZIP_2026_2, content=buffer.getvalue())
    with pytest.raises(UpstreamError, match="no Access database"):
        await client.lookup("8703", edition="2026-2")


async def test_gone_zip_is_not_found(httpx_mock):
    httpx_mock.add_response(url=MENU_2026, text=MENU_HTML)
    httpx_mock.add_response(url=ZIP_2026_2, status_code=404)
    with pytest.raises(NotFound):
        await client.lookup("8703", edition="2026-2")


async def test_cache_keeps_the_newest_editions(tmp_path: Path):
    root = tmp_path / "cap"
    root.mkdir()
    for i in range(constants.MAX_CACHED_EDITIONS + 2):
        (root / f"e{i}.parquet").write_bytes(b"x")
    keep = root / "e0.parquet"
    client._enforce_cache_cap(root, keep)
    assert keep.exists()
    assert len(list(root.glob("*.parquet"))) <= constants.MAX_CACHED_EDITIONS + 1
