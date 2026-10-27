"""The Jet 4 row reader on hand-built pages shaped like CBSA's TPHS table.

No Access file can be written here, so these build the byte layout
accdb.py reads, with the quirks found in 01-99-2026-2-eng.accdb: a
deleted variable column keeping its offset slot, a row moved to another
page, a deleted slot, and a page the table owns that is not in its usage
map (long memo text).
"""

from __future__ import annotations

import struct
from datetime import datetime

from maplestats_mcp.modules.cbsa_tariff.accdb import AccessTable, Column, decode_text

PAGE = 4096
TABLE_PAGE = 5

# TARIFF, EFF_DATE, CHANGE, (a deleted text column: id 3, variable slot 1),
# DESC1 (memo), MFN, row_id: 7 column ids, 6 live columns.
COLUMNS = [
    Column("TARIFF", 10, 0, 0, False, 0),
    Column("EFF_DATE", 8, 1, 0, True, 0),
    Column("CHANGE", 7, 2, 0, True, 8),
    Column("DESC1", 12, 4, 2, False, 0),
    Column("MFN", 10, 5, 3, False, 0),
    Column("row_id", 4, 6, 0, True, 16),
]


def compressed(text: str) -> bytes:
    return b"\xff\xfe" + text.encode("latin-1")


def inline_memo(text: str) -> bytes:
    data = compressed(text)
    return struct.pack("<III", len(data) | 0x80000000, 0, 0) + data


def record(tariff: str, desc: str, mfn: str, row_id: int, field_count: int = 7) -> bytes:
    days = (datetime(2026, 9, 1) - datetime(1899, 12, 30)).days
    fixed = struct.pack("<ddi", float(days), 1.0, row_id)
    parts = [compressed(tariff), b"", inline_memo(desc), compressed(mfn)]
    offsets = [2 + len(fixed)]
    for part in parts:
        offsets.append(offsets[-1] + len(part))
    tail = b"".join(struct.pack("<H", o) for o in reversed(offsets))
    mask = bytes([0b1110111])  # every id but the deleted column 3
    return (
        struct.pack("<H", field_count)
        + fixed
        + b"".join(parts)
        + tail
        + struct.pack("<H", len(parts))
        + mask
    )


def page(owner: int, records: list[tuple[bytes, int]]) -> bytes:
    """A data page: rows packed from the end backwards, with their slot flags."""
    body = bytearray(PAGE)
    body[0:2] = b"\x01\x01"
    struct.pack_into("<I", body, 4, owner)
    struct.pack_into("<H", body, 12, len(records))
    end = PAGE
    for i, (data, flags) in enumerate(records):
        start = end - len(data)
        body[start:end] = data
        struct.pack_into("<H", body, 14 + 2 * i, start | flags)
        end = start
    return bytes(body)


def table() -> AccessTable:
    usage = bytes([0]) + struct.pack("<I", 0) + bytes([0b00000100])  # page 2 only
    pages = [
        bytes(PAGE),
        page(TABLE_PAGE, [(usage, 0)]),
        page(
            TABLE_PAGE,
            [
                (record("01.01", "Live horses, asses, mules and hinnies.", "", 1), 0),
                (record("0101.21.00", "stale", "9 %", 2), 0x8000),
                (struct.pack("<I", (3 << 8) | 0), 0x4000),
                (record("0101.29.00", "Other", "Free", 4), 0),
            ],
        ),
        page(TABLE_PAGE, [(record("0101.21.00", "Pure-bred breeding animals", "Free", 3), 0xC000)]),
        page(TABLE_PAGE, [(record("9999.99.99", "memo page, not rows", "", 9), 0)]),
    ]
    reader = AccessTable.__new__(AccessTable)
    reader._data = b"".join(pages)
    reader._page_size = PAGE
    reader._table_page = TABLE_PAGE
    reader._usage_map = (1 << 8) | 0
    reader.columns = COLUMNS
    return reader


def test_compressed_text_switches_to_utf16_after_a_zero_byte():
    assert decode_text(b"\xff\xfeCaf\xe9") == "Café"
    assert decode_text(b"\xff\xfe-\x00\xb2\x03\x00-D") == "-β-D"
    assert decode_text("Sirop d'érable".encode("utf-16-le")) == "Sirop d'érable"


def test_rows_follow_the_usage_map_skip_deleted_and_follow_overflow():
    rows = [dict(zip([c.name for c in COLUMNS], r, strict=True)) for r in table().rows()]
    assert [r["TARIFF"] for r in rows] == ["01.01", "0101.21.00", "0101.29.00"]
    moved = rows[1]
    assert moved["DESC1"] == "Pure-bred breeding animals"
    assert moved["MFN"] == "Free"
    assert moved["row_id"] == 3
    assert moved["EFF_DATE"] == datetime(2026, 9, 1)
    assert moved["CHANGE"] == 1.0


def test_a_deleted_variable_column_keeps_its_offset_slot():
    # Ranking live variable columns (TARIFF, DESC1, MFN = 0, 1, 2) would read
    # DESC1 from the deleted column's empty slot and MFN from the memo.
    row = table()._row(record("8703.80.00", "Other vehicles", "6.1 %", 7))
    assert row[3] == "Other vehicles"
    assert row[4] == "6.1 %"


def test_columns_added_after_a_row_was_written_read_as_missing():
    row = table()._row(record("0101.21.00", "Horses", "Free", 8, field_count=6))
    assert row[5] is None  # row_id (column id 6) is past the row's 6 columns
    assert row[0] == "0101.21.00"
