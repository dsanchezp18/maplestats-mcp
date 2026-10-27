"""Read one table of a Microsoft Access (Jet 4 / ACE) file in pure Python.

`access-parser` reads the file header, the catalogue and the table
definition (column names, types, offsets); this module reads the rows,
because access-parser 0.0.6 drops or misreads them on the CBSA tariff
file. Checked 2026-10-26 on 01-99-2026-2-eng.accdb (25 MB, table TPHS,
36 live columns, 48 column ids after past deletions):

1. The null mask at the end of a row is as long as the row's own column
   count (48 here), not the table's live column count (36). access-parser
   uses 36, reads the variable-length offsets from the wrong place and
   returns only the 2 fixed columns of every row.
2. The variable-length offset table keeps a slot for each deleted
   variable column, so a column's offset is found by its
   `variable_column_number`, not by its rank among live columns.
3. A row moved to another page ("overflow", slot flag 0x4000) is sliced
   up to the previous slot's offset; access-parser masks that offset only
   for some flags and read 1,600 bytes for one row, failing its memo.
4. Pages are taken from the table's row usage map, not from every page
   naming the table as owner: the 57 owner-only pages hold long memo
   text (LVAL), not rows.

The result was 22,461 rows, one per `row_id`, and every slot not flagged
deleted (30,020 slots, 7,559 deleted). The table header says 22,402 rows:
Access updates that count lazily, so it is not used as a check.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_DELETED = 0x8000
_OVERFLOW = 0x4000
_OFFSET_MASK = 0x1FFF
_DATA_PAGE = 0x01
_MEMO_INLINE = 0x80000000
_MEMO_ONE_PAGE = 0x40000000
_MEMO_LENGTH = 0x3FFFFFFF
_ACCESS_EPOCH = datetime(1899, 12, 30)

# Jet column types (mdbtools' names).
_BOOL, _BYTE, _INT, _LONG, _MONEY, _FLOAT, _DOUBLE, _DATETIME = 1, 2, 3, 4, 5, 6, 7, 8
_TEXT, _MEMO = 10, 12


class AccessFormatError(ValueError):
    """The file is not an Access file this reader understands."""


@dataclass(frozen=True)
class Column:
    name: str
    type: int
    column_id: int
    variable_number: int
    fixed: bool
    fixed_offset: int


def decode_text(raw: bytes) -> str:
    """Jet 4 text: UTF-16LE, or "compressed" after the FF FE marker.

    Compressed text is one byte per character until a 0x00 byte switches
    to two-byte UTF-16LE characters (and back): used for runs of Latin-1.
    """
    if not raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16-le", errors="replace")
    out: list[str] = []
    compressed = True
    i = 2
    while i < len(raw):
        if raw[i] == 0:
            compressed = not compressed
            i += 1
        elif compressed:
            out.append(chr(raw[i]))
            i += 1
        else:
            out.append(raw[i : i + 2].decode("utf-16-le", errors="replace"))
            i += 2
    return "".join(out)


class AccessTable:
    def __init__(self, path: Path, table: str) -> None:
        # Imported here: the module is loaded only when a tariff file is read.
        from access_parser import AccessParser

        try:
            parser = AccessParser(str(path))
        except Exception as exc:
            raise AccessFormatError(f"{path.name} is not a readable Access file: {exc!r}") from exc
        if parser.version < 4:
            raise AccessFormatError(f"{path.name} is a Jet 3 file; only Jet 4 / ACE is read.")
        page = parser.catalog.get(table)
        if page is None:
            raise AccessFormatError(f"{path.name} has no table {table!r}.")
        # get_table() unpacks a None column list when the definition fails to parse.
        try:
            definition = parser.get_table(table)
        except TypeError:
            definition = None
        header = definition.table_header if definition is not None else None
        if definition is None or header is None or not definition.columns:
            raise AccessFormatError(f"{path.name}: the definition of {table!r} could not be read.")
        self._data: bytes = parser.db_data
        self._page_size: int = parser.page_size
        self._table_page = page
        self.columns = [
            Column(
                name=c.col_name_str,
                type=c.type,
                column_id=c.column_id,
                variable_number=c.variable_column_number,
                fixed=bool(c.column_flags.fixed_length),
                fixed_offset=c.fixed_offset,
            )
            for _, c in sorted(definition.columns.items())
        ]
        self._usage_map = header.row_page_map

    def _page(self, number: int) -> bytes:
        start = number * self._page_size
        page = self._data[start : start + self._page_size]
        if len(page) != self._page_size:
            raise AccessFormatError(f"page {number} is past the end of the file.")
        return page

    @staticmethod
    def _slots(page: bytes) -> list[int]:
        count = struct.unpack_from("<H", page, 12)[0]
        return list(struct.unpack_from(f"<{count}H", page, 14))

    def _slice(self, page: bytes, slots: list[int], index: int) -> bytes:
        # Rows are stored from the end of the page backwards: row i ends
        # where row i-1 starts, whatever flags row i-1 carries.
        start = slots[index] & _OFFSET_MASK
        end = self._page_size if index == 0 else slots[index - 1] & _OFFSET_MASK
        return page[start:end]

    def _record(self, pointer: int) -> bytes:
        page = self._page(pointer >> 8)
        slots = self._slots(page)
        index = pointer & 0xFF
        if index >= len(slots):
            raise AccessFormatError(f"row pointer {pointer:#x} is past its page's last row.")
        return self._slice(page, slots, index)

    def _row_pages(self) -> list[int]:
        record = self._record(self._usage_map)
        pages: list[int] = []
        if record[0] == 0:
            first = struct.unpack_from("<I", record, 1)[0]
            bitmap, base = record[5:], first
            pages += [base + i for i in range(len(bitmap) * 8) if bitmap[i // 8] >> (i % 8) & 1]
        elif record[0] == 1:
            per_map = (self._page_size - 4) * 8
            for k in range((len(record) - 1) // 4):
                map_page = struct.unpack_from("<I", record, 1 + 4 * k)[0]
                if not map_page:
                    continue
                bitmap = self._page(map_page)[4:]
                pages += [
                    k * per_map + i for i in range(len(bitmap) * 8) if bitmap[i // 8] >> (i % 8) & 1
                ]
        else:
            raise AccessFormatError(f"unknown usage map type {record[0]}.")
        return pages

    def _memo(self, raw: bytes) -> str:
        length, pointer = struct.unpack_from("<II", raw, 0)
        size = length & _MEMO_LENGTH
        if length & _MEMO_INLINE:
            data = raw[12 : 12 + size]
        elif length & _MEMO_ONE_PAGE:
            data = self._record(pointer)[:size]
        else:
            parts: list[bytes] = []
            seen: set[int] = set()
            while pointer and pointer not in seen:
                seen.add(pointer)
                chunk = self._record(pointer)
                parts.append(chunk[4:])
                pointer = struct.unpack_from("<I", chunk, 0)[0]
            data = b"".join(parts)[:size]
        return decode_text(data)

    def _value(self, column: Column, raw: bytes) -> Any:
        kind = column.type
        if kind == _TEXT:
            return decode_text(raw)
        if kind == _MEMO:
            return self._memo(raw) if len(raw) >= 12 else ""
        if kind == _LONG:
            return struct.unpack_from("<i", raw)[0]
        if kind == _INT:
            return struct.unpack_from("<h", raw)[0]
        if kind == _BYTE:
            return raw[0]
        if kind == _DOUBLE:
            return struct.unpack_from("<d", raw)[0]
        if kind == _FLOAT:
            return struct.unpack_from("<f", raw)[0]
        if kind == _MONEY:
            return struct.unpack_from("<q", raw)[0] / 10_000
        if kind == _DATETIME:
            return _ACCESS_EPOCH + timedelta(days=struct.unpack_from("<d", raw)[0])
        return None

    def _row(self, record: bytes) -> list[Any]:
        field_count = struct.unpack_from("<H", record, 0)[0]
        mask_length = (field_count + 7) // 8
        mask = record[len(record) - mask_length :]
        end = len(record) - mask_length
        var_count = struct.unpack_from("<H", record, end - 2)[0]
        # var_count + 1 offsets, stored backwards before the count; the last
        # one is where the variable-length data ends.
        offsets = [
            struct.unpack_from("<H", record, end - 4 - 2 * i)[0] for i in range(var_count + 1)
        ]
        row: list[Any] = []
        for column in self.columns:
            cid = column.column_id
            present = cid < field_count and bool(mask[cid // 8] >> (cid % 8) & 1)
            if column.type == _BOOL:
                row.append(present)
                continue
            if not present:
                row.append(None)
                continue
            if column.fixed:
                row.append(self._value(column, record[2 + column.fixed_offset :]))
                continue
            k = column.variable_number
            if k >= var_count:
                row.append(None)
                continue
            raw = record[offsets[k] : offsets[k + 1]]
            row.append(self._value(column, raw) if raw else "")
        return row

    def rows(self) -> Iterator[list[Any]]:
        """Every live row, values in the order of `columns`."""
        for number in self._row_pages():
            page = self._page(number)
            if page[0] != _DATA_PAGE or struct.unpack_from("<I", page, 4)[0] != self._table_page:
                continue
            slots = self._slots(page)
            for index, slot in enumerate(slots):
                if slot & _DELETED:
                    continue
                record = self._slice(page, slots, index)
                if slot & _OVERFLOW:
                    record = self._record(struct.unpack_from("<I", record, 0)[0])
                yield self._row(record)
