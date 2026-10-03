"""Reading a Delta File by range requests, with small synthetic zips.

The layout mirrors the real files (confirmed live 2026-10-02): codeSet.xml,
YYYYMMDD.xml and YYYYMMDD.csv, in that order, deflated; the CSV sorted
ascending by productId in contiguous blocks, with empty values for
suppressed points; HEAD carrying Last-Modified and ETag; a 404 for a day
without a release.
"""

from __future__ import annotations

import io
import re
import zipfile

import httpx
import pytest

from maplestats_mcp import config
from maplestats_mcp.modules.statcan.delta import archive, client, realtime, scan_index
from maplestats_mcp.shared import cache
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError
from maplestats_mcp.shared.remote_zip import ZipMember
from maplestats_mcp.shared.zip_stream import MemberStream, ScanLimitExceeded

DAY = "2026-10-02"
STAMP = "20261002"
URL = f"https://www150.statcan.gc.ca/n1/delta/{STAMP}.zip"
PAGE = "https://www.statcan.gc.ca/en/developers/df"
HEADER = (
    "productId,coordinate,vectorId,refPer,refPer2,symbolCode,statusCode,securityLevelCode,"
    "value,releaseTime,scalarFactorCode,decimals,frequencyCode"
)
CODESET = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<codeSet>
  <updateTime>2026-10-02T00:03</updateTime>
  <scalars>
    <scalar><scalarFactorCode>0</scalarFactorCode><scalarFactorDescEn>units</scalarFactorDescEn>
      <scalarFactorDescFr>unités</scalarFactorDescFr></scalar>
    <scalar><scalarFactorCode>3</scalarFactorCode><scalarFactorDescEn>thousands</scalarFactorDescEn>
      <scalarFactorDescFr>milliers</scalarFactorDescFr></scalar>
  </scalars>
  <frequencies>
    <frequency><frequencyCode>6</frequencyCode><frequencyDescEn>Monthly</frequencyDescEn>
      <frequencyDescFr>Mensuelle</frequencyDescFr></frequency>
  </frequencies>
  <symbols>
    <symbol><symbolCode>0</symbolCode><symbolDescEn>none</symbolDescEn>
      <symbolDescFr>aucun</symbolDescFr></symbol>
    <symbol><symbolCode>1</symbolCode><symbolDescEn>preliminary</symbolDescEn>
      <symbolDescFr>provisoire</symbolDescFr><symbolRepresentationEn>p</symbolRepresentationEn>
    </symbol>
  </symbols>
  <statuses>
    <status><statusCode>0</statusCode><statusDescEn>normal</statusDescEn>
      <statusDescFr>normal</statusDescFr></status>
    <status><statusCode>1</statusCode><statusDescEn>not available for a specific reference
      period</statusDescEn><statusDescFr>indisponible</statusDescFr></status>
  </statuses>
  <securityLevels>
    <securityLevel><securityLevelCode>0</securityLevelCode>
      <securityLevelDescEn>public</securityLevelDescEn>
      <securityLevelDescFr>public</securityLevelDescFr></securityLevel>
  </securityLevels>
</codeSet>
"""


def _cube(pid: int, title: str, *, cansim: str | None, correction: bool = False) -> str:
    cansim_tag = f"<cansimId>{cansim}</cansimId>" if cansim else ""
    corrections = (
        "<corrections><correction><correctionDate>2018-10-02</correctionDate>"
        "<correctionId>1075</correctionId>"
        "<correctionNoteEn>&lt;p&gt;Data for 2016 were revised.&lt;br&gt;&lt;/p&gt;"
        "</correctionNoteEn><correctionNoteFr>&lt;p&gt;Données de 2016 révisées.&lt;/p&gt;"
        "</correctionNoteFr></correction></corrections>"
        if correction
        else "<corrections/>"
    )
    return f"""<cube>
  <archiveStatusCode>2</archiveStatusCode>
  <archiveStatusEn>CURRENT - a cube available to the public</archiveStatusEn>
  <archiveStatusFr>ACTIF</archiveStatusFr>
  {cansim_tag}
  <correctionFootnotes/>
  {corrections}
  <cubeEndDate>2026-09-29</cubeEndDate>
  <cubeStartDate>1981-05-04</cubeStartDate>
  <cubeTitleEn>{title}</cubeTitleEn>
  <cubeTitleFr>{title} (Banque du Canada, données)</cubeTitleFr>
  <dimensions>
    <dimension>
      <dimensionNameEn>Geography</dimensionNameEn>
      <dimensionNameFr>Géographie</dimensionNameFr>
      <dimensionPositionId>1</dimensionPositionId>
      <hasUom>false</hasUom>
      <members>
        <member><memberId>1</memberId><memberNameEn>Canada</memberNameEn>
          <memberNameFr>Canada</memberNameFr><terminated>0</terminated></member>
        <member><memberId>2</memberId><memberNameEn>Alberta</memberNameEn>
          <memberNameFr>Alberta</memberNameFr><terminated>1</terminated></member>
      </members>
    </dimension>
  </dimensions>
  <footnotes><footnote/></footnotes>
  <frequencyCode>6</frequencyCode>
  <frequencyEn>Monthly</frequencyEn>
  <frequencyFr>Mensuelle</frequencyFr>
  <nbDatapointsCube>101968</nbDatapointsCube>
  <nbSeriesCube>28</nbSeriesCube>
  <productId>{pid}</productId>
  <releaseTime>2026-10-02T08:30</releaseTime>
  <responseStatusCode>0</responseStatusCode>
  <subjectCodes><subjectCode>10</subjectCode></subjectCodes>
  <surveyCodes><surveyCode>1</surveyCode></surveyCodes>
</cube>"""


# 30000000 is in the metadata but has no data rows (a metadata-only change).
METADATA = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cubes>'
    + _cube(10100001, "Interest rates", cansim="176-0048", correction=True)
    + _cube(20000001, "Exchange rates", cansim=None)
    + _cube(30000000, "Metadata only", cansim=None)
    + _cube(40000001, "Last table", cansim=None)
    + "</cubes>"
)


def _csv(blocks: dict[int, int], *, empty_every: int = 7) -> str:
    lines = [HEADER]
    for pid, count in blocks.items():
        for n in range(count):
            vector = pid * 10 + n
            empty = n % empty_every == 3
            symbol, status = (1, 0) if n % 5 == 0 else (0, 1 if empty else 0)
            value = "" if empty else f"{n}.25"
            lines.append(
                f"{pid},1.{n}.0.0.0.0.0.0.0.0,{vector},2026-09,,{symbol},{status},0,{value},"
                f"2026-10-02T08:30,{3 if pid == 20000001 else 0},2,6"
            )
    return "\n".join(lines) + "\n"


def _zip(csv: str, stamp: str = STAMP, metadata: str = METADATA) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("codeSet.xml", CODESET)
        bundle.writestr(f"{stamp}.xml", metadata)
        bundle.writestr(f"{stamp}.csv", csv)
    return buffer.getvalue()


BLOCKS = {10100001: 40, 20000001: 3000, 40000001: 2500}


def _serve(body: bytes, *, requests: list[tuple[str, str]] | None = None):
    def respond(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append((request.method, request.headers.get("range", "")))
        if request.method == "HEAD":
            return httpx.Response(
                200,
                headers={
                    "content-length": str(len(body)),
                    "last-modified": "Fri, 02 Oct 2026 12:30:27 GMT",
                    "etag": '"1636a-65cdab285a80b"',
                    "accept-ranges": "bytes",
                },
            )
        start, end = map(int, re.findall(r"\d+", request.headers["range"]))
        return httpx.Response(206, content=body[start : end + 1])

    return respond


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cache._caches.clear()
    scan_index.clear()
    monkeypatch.setenv("MAPLE_DELTA_INDEX_DIR", str(tmp_path / "delta-index"))
    # The 2 s spacing between range requests is real time; tests
    # check it separately with a short interval.
    monkeypatch.setattr(archive, "SCAN_REQUEST_INTERVAL_SECONDS", 0.0)


@pytest.fixture
def small_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive, "SCAN_CHUNK_BYTES", 2048)


def _mock_day(httpx_mock, csv: str | None = None, requests=None) -> bytes:
    body = _zip(csv if csv is not None else _csv(BLOCKS))
    httpx_mock.add_callback(_serve(body, requests=requests), url=URL, is_reusable=True)
    return body


async def test_list_tables_reads_the_metadata_only(httpx_mock):
    requests: list[tuple[str, str]] = []
    body = _mock_day(httpx_mock, requests=requests)
    result = await archive.list_tables(DAY)
    assert result.table_count == 4
    assert result.zip_size_bytes == len(body)
    assert result.last_modified == "Fri, 02 Oct 2026 12:30:27 GMT"
    assert result.etag == '"1636a-65cdab285a80b"'
    first = result.tables[0]
    assert first.product_id == 10100001
    assert first.cansim_id == "176-0048"
    assert first.title_fr is not None
    assert "données" in first.title_fr
    assert first.frequency == "Monthly"
    assert first.release_time == "2026-10-02T08:30"
    assert first.series_count == 28
    assert first.correction_count == 1
    assert first.corrections is None
    assert first.dimensions[0].member_count == 2
    assert first.dimensions[0].members is None
    assert result.tables[1].cansim_id is None
    # The CSV member is never requested: its bytes start after the metadata.
    csv_start = max(r for r in requests if r[0] == "GET")
    assert result.provenance.as_of is not None
    assert csv_start is not None


async def test_list_tables_detail_for_one_table_and_french(httpx_mock):
    _mock_day(httpx_mock)
    result = await archive.list_tables(DAY, product_id=10100001, detail=True, lang="fr")
    table = result.tables[0]
    assert result.table_count == 4
    assert result.returned == 1
    assert table.frequency == "Mensuelle"
    assert table.archive_status == "ACTIF"
    assert [m.name_en for m in table.dimensions[0].members or []] == ["Canada", "Alberta"]
    assert (table.dimensions[0].members or [])[1].terminated is True
    assert table.corrections is not None
    assert table.corrections[0].note == "Données de 2016 révisées."
    assert table.corrections[0].date == "2018-10-02"


async def test_list_tables_filters_and_caps(httpx_mock):
    _mock_day(httpx_mock)
    by_title = await archive.list_tables(DAY, query="exchange")
    assert [t.product_id for t in by_title.tables] == [20000001]
    capped = await archive.list_tables(DAY, max_tables=2)
    assert capped.returned == 2
    assert capped.truncated is True
    with pytest.raises(NotFound, match="999"):
        await archive.list_tables(DAY, product_id=999)
    with pytest.raises(InvalidInput, match="product_id"):
        await archive.list_tables(DAY, detail=True)
    with pytest.raises(InvalidInput, match="YYYY-MM-DD"):
        await archive.list_tables("02/10/2026")


async def test_read_table_block_in_the_middle(httpx_mock, small_chunks):
    requests: list[tuple[str, str]] = []
    body = _mock_day(httpx_mock, requests=requests)
    result = await archive.read_table(DAY, 20000001, max_rows=5000)
    assert result.row_count == 3000
    assert result.truncated is False
    assert result.csv_rows_found is True
    assert result.title_en == "Exchange rates"
    assert result.cansim_id is None
    assert result.series_count == 28
    first, fourth = result.rows[0], result.rows[3]
    assert first.vector_id == 200000010
    assert first.coordinate == "1.0.0.0.0.0.0.0.0.0"
    assert first.value == 0.25
    assert first.symbol_code == 1
    assert first.scalar_factor_code == 3
    assert first.ref_period == "2026-09"
    assert first.ref_period_end is None
    # A suppressed point has an empty value and status 1, never 0.
    assert fourth.value is None
    assert fourth.status_code == 1
    assert result.legend.symbols == {0: "none", 1: "preliminary"}
    assert result.legend.statuses[1].startswith("not available")
    assert result.legend.scalar_factors == {3: "thousands"}
    assert result.legend.frequencies == {6: "Monthly"}
    assert {r.vector_id for r in result.rows} == {200000010 + n for n in range(3000)}
    # The table after the block (40000001) is not read: the scan stops at the
    # first batch past it, so fewer bytes are fetched than the whole file.
    assert result.compressed_bytes_scanned < len(body)
    assert any("Values are raw" in note for note in result.notes)


async def test_read_table_stops_early_for_the_first_block(httpx_mock, small_chunks):
    body = _mock_day(httpx_mock)
    result = await archive.read_table(DAY, 10100001, lang="fr")
    assert result.row_count == 40
    assert result.legend.symbols[1] == "provisoire"
    assert result.legend.scalar_factors == {0: "unités"}
    csv_member = zipfile.ZipFile(io.BytesIO(body)).getinfo(f"{STAMP}.csv")
    assert result.compressed_bytes_scanned < csv_member.compress_size


async def test_read_table_vector_filter_and_row_cap(httpx_mock, small_chunks):
    _mock_day(httpx_mock)
    wanted = [200000010, 200000012, 777]
    filtered = await archive.read_table(DAY, 20000001, vector_ids=wanted)
    assert [r.vector_id for r in filtered.rows] == [200000010, 200000012]
    assert filtered.vector_filter == [777, 200000010, 200000012]
    assert filtered.truncated is False
    capped = await archive.read_table(DAY, 20000001, max_rows=10)
    assert capped.row_count == 10
    assert capped.truncated is True
    exact = await archive.read_table(DAY, 10100001, max_rows=40)
    assert exact.row_count == 40
    assert exact.truncated is False
    with pytest.raises(InvalidInput, match="max_rows"):
        await archive.read_table(DAY, 10100001, max_rows=0)


async def test_read_table_in_metadata_without_rows(httpx_mock, small_chunks):
    _mock_day(httpx_mock)
    result = await archive.read_table(DAY, 30000000)
    assert result.row_count == 0
    assert result.csv_rows_found is False
    assert any("metadata-only" in note for note in result.notes)


async def test_read_table_not_in_the_release_does_not_touch_the_csv(httpx_mock):
    requests: list[tuple[str, str]] = []
    _mock_day(httpx_mock, requests=requests)
    with pytest.raises(NotFound, match="wds_get_full_table_download"):
        await archive.read_table(DAY, 99999999)
    csv_reads = [r for r in requests if r[0] == "GET"]
    # Directory tail, local headers and the two small XML members only.
    assert len(csv_reads) <= 6


async def test_read_table_past_the_scan_ceiling_points_to_wds(
    httpx_mock, small_chunks, monkeypatch
):
    _mock_day(httpx_mock)
    monkeypatch.setattr(config, "get_delta_max_scan_bytes", lambda: 3000)
    with pytest.raises(UpstreamError) as caught:
        await archive.read_table(DAY, 40000001)
    message = str(caught.value)
    assert "wds_get_changed_series_data" in message
    assert "wds_get_full_table_download" in message
    assert "was not reached" in message
    assert "up to productId 20000001" in message
    assert "No resume point" in message


# Large enough for several deflate blocks (about 600 KB compressed).
DEEP_BLOCKS = {10100001: 30000, 20000001: 30000, 30000001: 30000, 40000001: 1500}


def _deep_metadata() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cubes>'
        + "".join(_cube(pid, f"Table {pid}", cansim=None) for pid in DEEP_BLOCKS)
        + "</cubes>"
    )


@pytest.fixture
def deep_day(httpx_mock, monkeypatch):
    """A day whose last table lies past several calls' ceiling."""
    text = _csv(DEEP_BLOCKS)
    body = _zip(text, metadata=_deep_metadata())
    requests: list[tuple[str, str]] = []
    httpx_mock.add_callback(_serve(body, requests=requests), url=URL, is_reusable=True)
    monkeypatch.setattr(archive, "SCAN_CHUNK_BYTES", 32 * 1024)
    monkeypatch.setattr(archive, "SCAN_POINT_SPACING", 24 * 1024)
    monkeypatch.setattr(config, "get_delta_max_scan_bytes", lambda: 150 * 1024)
    return text, requests


async def _read_resuming(product_id: int, calls: int = 20, **kwargs):
    messages = []
    for _ in range(calls):
        try:
            return await archive.read_table(DAY, product_id, **kwargs), messages
        except UpstreamError as exc:
            messages.append(str(exc))
    raise AssertionError(f"not reached after {calls} calls: {messages[-1]}")


async def test_a_deep_table_is_reached_by_calling_again(deep_day, monkeypatch):
    text, _ = deep_day
    result, messages = await _read_resuming(40000001, max_rows=5000)
    assert messages, "the ceiling should have stopped the first call"
    assert "Progress is saved" in messages[0]
    assert "up to productId" in messages[0]
    assert "a saved resume point" in messages[-1]
    assert result.row_count == 1500
    assert result.block_complete is True
    assert result.scan_started_at_byte > 0
    assert any("resume point saved by an earlier scan" in note for note in result.notes)
    # Exactly the rows a plain read of the CSV gives.
    expected = [line.split(",")[2] for line in text.splitlines() if line.startswith("40000001,")]
    assert [str(row.vector_id) for row in result.rows] == expected
    assert result.rows[3].value is None

    # The next read of a nearby table starts near it, not at byte 0.
    again = await archive.read_table(DAY, 40000001, max_rows=5000)
    assert again.scan_started_at_byte == result.scan_started_at_byte
    assert again.compressed_bytes_scanned < 150 * 1024


async def test_saved_points_survive_a_restart_and_a_new_etag_starts_over(deep_day, tmp_path):
    await _read_resuming(40000001, max_rows=5000)
    files = list((tmp_path / "delta-index").glob("2026-10-02_*.json"))
    assert len(files) == 1
    scan_index.clear()
    cache._caches.clear()
    reloaded = scan_index.load(DAY, '"1636a-65cdab285a80b"')
    assert reloaded.header is not None
    assert reloaded.header.startswith("productId,")
    assert len(reloaded.points) >= 3
    assert [p.product_id for p in reloaded.points] == sorted(p.product_id for p in reloaded.points)
    result = await archive.read_table(DAY, 40000001, max_rows=5000)
    assert result.scan_started_at_byte > 0
    # Another file version (ETag) has no points.
    assert scan_index.load(DAY, '"other"').points == []


async def test_a_damaged_index_file_is_ignored(deep_day, tmp_path):
    await _read_resuming(10100001, max_rows=10)
    scan_index.clear()
    folder = tmp_path / "delta-index"
    folder.mkdir(exist_ok=True)
    for path in folder.glob("*.json"):
        path.write_text("{not json", encoding="utf-8")
    key_file = folder / "2026-10-02_x.json"
    key_file.write_text("{not json", encoding="utf-8")
    result = await archive.read_table(DAY, 10100001, max_rows=10)
    assert result.scan_started_at_byte == 0
    assert result.row_count == 10


async def test_the_ceiling_inside_a_table_returns_its_first_rows(deep_day, monkeypatch):
    # 20000001's block is far longer than one call may read.
    monkeypatch.setattr(config, "get_delta_max_scan_bytes", lambda: 40 * 1024)
    result, _ = await _read_resuming(20000001, vector_ids=[200000010 + 29_999], max_rows=10)
    assert result.block_complete is False
    assert result.row_count == 0
    assert any(note.startswith("Incomplete") for note in result.notes)
    assert any("wds_get_full_table_download" in note for note in result.notes)


async def test_live_shaped_rows_of_20261001(httpx_mock, small_chunks):
    """Lines copied from 20261001.csv (read live by range 2026-10-03): no BOM, LF
    endings; 35100027 republishes its history with the original release
    time (2013-06-13T08:30) and fiscal years as refPer/refPer2; daily FX
    rates (33100036) with an empty value and status 1."""
    lines = [
        HEADER,
        "10100139,1.12.0.0.0.0.0.0.0.0,39050,2026-09-25,,0,0,0,2.2802,2026-10-01T08:30,0,4,1",
        "33100036,1.1.0.0.0.0.0.0.0.0,111666224,2026-09-26,,0,1,0,,2026-10-01T08:30,0,4,1",
        "35100027,9.20.4.2.2.1.0.0.0.0,55452564,2007,2008,0,0,0,58,2013-06-13T08:30,0,0,12",
        "35100027,9.39.1.4.1.3.0.0.0.0,55471610,2014,2015,0,1,0,,2026-10-01T08:30,0,0,12",
    ]
    metadata = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cubes>'
        + "".join(_cube(pid, "t", cansim=None) for pid in (10100139, 33100036, 35100027))
        + "</cubes>"
    )
    body = _zip("\n".join(lines) + "\n", metadata=metadata)
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    courts = await archive.read_table(DAY, 35100027)
    assert [r.ref_period for r in courts.rows] == ["2007", "2014"]
    assert [r.ref_period_end for r in courts.rows] == ["2008", "2015"]
    assert courts.rows[0].release_time == "2013-06-13T08:30"
    assert courts.rows[1].value is None
    assert courts.rows[1].status_code == 1
    assert courts.rows[0].frequency_code == 12
    fx = await archive.read_table(DAY, 33100036)
    assert fx.rows[0].ref_period == "2026-09-26"
    assert fx.rows[0].value is None


async def test_every_delta_request_opens_a_fresh_connection(httpx_mock, small_chunks):
    """www150 pins a connection to one backend (shared/http.py), so the HEAD,
    the directory read and every CSV range carry Connection: close."""
    _mock_day(httpx_mock)
    await archive.read_table(DAY, 20000001)
    sent = httpx_mock.get_requests()
    assert {r.method for r in sent} == {"HEAD", "GET"}
    assert len(sent) > 5
    assert all(r.headers["connection"] == "close" for r in sent)
    assert all(r.headers["user-agent"].startswith("maplestats") for r in sent)
    assert all("range" in r.headers for r in sent if r.method == "GET")


async def test_unsorted_csv_is_an_error(httpx_mock, small_chunks):
    rows = _csv({20000001: 3, 10100001: 3})
    _mock_day(httpx_mock, csv=rows)
    with pytest.raises(UpstreamError, match="sorted"):
        await archive.read_table(DAY, 20000001)


async def test_missing_csv_column_is_an_error(httpx_mock):
    _mock_day(httpx_mock, csv=_csv(BLOCKS).replace("vectorId", "vector"))
    with pytest.raises(UpstreamError, match="vectorId"):
        await archive.read_table(DAY, 10100001)


async def test_archive_without_the_three_members_is_an_error(httpx_mock):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("other.txt", "x")
    httpx_mock.add_callback(_serve(buffer.getvalue()), url=URL, is_reusable=True)
    with pytest.raises(UpstreamError, match="codeSet.xml"):
        await archive.list_tables(DAY)


def _page(stamps: list[str]) -> str:
    rows = "".join(
        f'<tr><th scope="row"><a href="https://www150.statcan.gc.ca/delta/{s}.zip">{s}.zip</a>'
        f'</th><td>Table updates from <em class="placeholder">{s}</em></td></tr>'
        for s in stamps
    )
    return f"<html><body><table><tbody>{rows}</tbody></table></body></html>"


# 20260930 is a holiday, 20260926 and 20260927 a weekend.
LISTED = ["20261002", "20261001", "20260929", "20260928", "20260925", "20260924"]


async def test_missing_date_says_holiday_weekend_retention_or_future(httpx_mock):
    httpx_mock.add_response(url=PAGE, text=_page(LISTED), is_reusable=True)
    for stamp in ("20260930", "20260926", "20260101", "20261105"):
        httpx_mock.add_response(
            method="HEAD",
            url=f"https://www150.statcan.gc.ca/n1/delta/{stamp}.zip",
            status_code=404,
        )
    expectations = {
        "2026-09-30": "holiday",
        "2026-09-26": "weekend",
        "2026-01-01": "past retention",
        "2026-11-05": "not yet published",
    }
    for day, phrase in expectations.items():
        with pytest.raises(NotFound, match=phrase):
            await archive.list_tables(day)


async def test_list_files_reports_status_and_sizes(httpx_mock):
    httpx_mock.add_response(url=PAGE, text=_page(LISTED), is_reusable=True)
    result = await archive.list_files(date="2026-09-30")
    assert result.count == 6
    assert result.newest == "2026-10-02"
    assert result.oldest == "2026-09-24"
    assert result.files[0].weekday == "Friday"
    assert result.files[0].url == "https://www150.statcan.gc.ca/n1/delta/20261002.zip"
    assert result.files[0].size_bytes is None
    assert result.requested_status is not None
    assert result.requested_status.startswith("no release that day")
    available = await archive.list_files(date="2026-10-01")
    assert available.requested_status == "available"
    assert (await archive.list_files(date="2026-08-01")).requested_status is not None
    assert (await archive.list_files(date="2026-08-01")).requested_status == (
        "past retention (the oldest file kept is 2026-09-24; about 47 business days are available)"
    )
    assert any("5 releases" in note for note in result.notes)


async def test_list_files_with_sizes_survives_a_failed_head(httpx_mock):
    httpx_mock.add_response(url=PAGE, text=_page(LISTED[:3]))
    for stamp in LISTED[:2]:
        httpx_mock.add_response(
            method="HEAD",
            url=f"https://www150.statcan.gc.ca/n1/delta/{stamp}.zip",
            headers={"content-length": "91000", "etag": '"abc"', "last-modified": "Fri, 02 Oct"},
        )
    httpx_mock.add_response(
        method="HEAD",
        url=f"https://www150.statcan.gc.ca/n1/delta/{LISTED[2]}.zip",
        status_code=404,
    )
    result = await archive.list_files(include_sizes=True)
    by_date = {f.date: f for f in result.files}
    assert by_date["2026-10-02"].size_bytes == 91000
    assert by_date["2026-10-02"].etag == '"abc"'
    assert by_date["2026-09-29"].size_bytes is None


async def test_list_files_page_without_links_is_an_error(httpx_mock):
    httpx_mock.add_response(url=PAGE, text="<html>nothing</html>")
    with pytest.raises(UpstreamError, match="no Delta File links"):
        await archive.list_files()


async def test_get_file_link_carries_headers_and_notes(httpx_mock):
    httpx_mock.add_response(
        method="HEAD",
        url="https://www150.statcan.gc.ca/delta/20261002.zip",
        headers={
            "content-length": "90986",
            "last-modified": "Fri, 02 Oct 2026 12:30:27 GMT",
            "etag": '"1636a-65cdab285a80b"',
        },
    )
    link = await client.get_file_link(DAY)
    assert link.exists is True
    assert link.last_modified == "Fri, 02 Oct 2026 12:30:27 GMT"
    assert link.etag == '"1636a-65cdab285a80b"'
    assert any("8:30 ET" in note for note in link.notes)
    assert any("cubemetadata.zip" in note for note in link.notes)


def test_real_time_list_is_complete_and_consistent():
    result = realtime.list_real_time_tables()
    assert result.count == 19
    real_time_ids = [t.real_time_product_id for t in result.tables]
    assert len(set(real_time_ids)) == 19
    assert len({t.regular_product_id for t in result.tables}) == 19
    assert 36100491 in real_time_ids
    gdp = next(t for t in result.tables if t.real_time_product_id == 36100491)
    assert gdp.regular_product_id == 36100434
    assert gdp.real_time_table == "36-10-0491"
    assert gdp.regular_table == "36-10-0434"
    assert gdp.wds_available is True
    unavailable = [t for t in result.tables if not t.wds_available]
    assert sorted(t.real_time_product_id for t in unavailable) == [16100118, 16100119, 20100019]
    assert all(t.real_time_title_fr is None and t.note for t in unavailable)
    inactive = [t for t in result.tables if t.real_time_title_en.endswith(", inactive")]
    assert len(inactive) == 6
    assert all(t.note and "inactive" in t.note for t in inactive)


def test_real_time_list_filters_by_word_and_id():
    assert realtime.list_real_time_tables("gross domestic").count == 3
    assert realtime.list_real_time_tables("36100434").count == 1
    assert realtime.list_real_time_tables("produit intérieur").count == 3
    assert realtime.list_real_time_tables("nothing like this").count == 0


def _stream_fixture(text: str, method: int = zipfile.ZIP_DEFLATED) -> tuple[bytes, ZipMember]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("data.csv", text, compress_type=method)
    info = zipfile.ZipFile(io.BytesIO(buffer.getvalue())).getinfo("data.csv")
    return buffer.getvalue(), ZipMember(
        "data.csv", info.compress_size, info.file_size, info.compress_type, info.header_offset
    )


@pytest.mark.parametrize("method", [zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED])
async def test_member_stream_yields_complete_lines(httpx_mock, method):
    text = "id,v\r\n" + "\r\n".join(f"{n},{n * 2}" for n in range(3000)) + "\r\nlast,line"
    body, member = _stream_fixture(text, method)
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    stream = MemberStream(
        URL, member, chunk_bytes=512, max_scan_bytes=10**9, max_inflated_bytes=10**9
    )
    lines = [line async for batch in stream.batches() for line in batch]
    assert lines[0] == b"id,v"
    assert lines[-1] == b"last,line"
    assert len(lines) == 3002
    assert stream.scanned == member.compressed_size


async def test_member_stream_stops_at_the_scan_ceiling_and_the_clock(httpx_mock):
    text = "id,v\n" + "\n".join(f"{n},{n}" for n in range(20000))
    body, member = _stream_fixture(text, zipfile.ZIP_STORED)
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    limited = MemberStream(
        URL, member, chunk_bytes=1000, max_scan_bytes=3000, max_inflated_bytes=10**9
    )
    with pytest.raises(ScanLimitExceeded) as caught:
        _ = [batch async for batch in limited.batches()]
    assert caught.value.scanned == 3000
    timed = MemberStream(
        URL,
        member,
        chunk_bytes=1000,
        max_scan_bytes=10**9,
        max_inflated_bytes=10**9,
        max_seconds=-1.0,
    )
    with pytest.raises(ScanLimitExceeded, match="passed"):
        _ = [batch async for batch in timed.batches()]
    inflated = MemberStream(
        URL, member, chunk_bytes=1000, max_scan_bytes=10**9, max_inflated_bytes=500
    )
    with pytest.raises(ScanLimitExceeded, match="inflated"):
        _ = [batch async for batch in inflated.batches()]


async def test_member_stream_corrupt_deflate_and_changed_archive(httpx_mock):
    body, member = _stream_fixture("id\n" + "1\n" * 5000)
    damaged = bytearray(body)
    damaged[member.header_offset + 40 : member.header_offset + 60] = b"\xff" * 20
    httpx_mock.add_callback(_serve(bytes(damaged)), url=URL, is_reusable=True)
    stream = MemberStream(
        URL, member, chunk_bytes=4096, max_scan_bytes=10**9, max_inflated_bytes=10**9
    )
    with pytest.raises(UpstreamError, match="deflate"):
        _ = [batch async for batch in stream.batches()]
    moved = ZipMember(
        "data.csv", member.compressed_size, member.size, 8, member.header_offset + 100
    )
    stream = MemberStream(
        URL, moved, chunk_bytes=4096, max_scan_bytes=10**9, max_inflated_bytes=10**9
    )
    with pytest.raises(UpstreamError, match="changed while"):
        _ = [batch async for batch in stream.batches()]
