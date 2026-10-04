"""Resume points for one Delta File's CSV, kept in memory and on disk.

A scan of the CSV records a verified deflate access point (see
`shared/zip_stream.py`) about every 16 MB of compressed data, with the
productId of the row it falls in. A later read of the same file version
(same date and ETag) starts at the last point before its table instead of
at byte 0, and a scan stopped by the time ceiling leaves its points
behind, so the next call continues from where it stopped.

The CSV is sorted by productId (confirmed on 20260929, 20261001 and
20261002), so a point whose row belongs to an earlier productId lies
before every row of the requested table.
"""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from maplestats_mcp import config
from maplestats_mcp.shared.zip_stream import AccessPoint

_VERSION = 1
# Indexes for files past retention are useless; about 47 business days
# are kept, and one index is at most a few MB.
_MAX_FILES = 60


@dataclass(frozen=True)
class IndexedPoint:
    product_id: int  # productId of the row holding the byte just before the point
    point: AccessPoint


@dataclass
class ScanIndex:
    key: str
    header: str | None = None  # the CSV's header line, needed when resuming
    points: list[IndexedPoint] = field(default_factory=list)

    @property
    def furthest(self) -> IndexedPoint | None:
        return self.points[-1] if self.points else None


_indexes: dict[str, ScanIndex] = {}


def _key(date: str, etag: str | None) -> str:
    return f"{date}|{etag or ''}"


def _path(key: str) -> Path | None:
    root = config.get_delta_index_dir()
    if root is None:
        return None
    date, _, etag = key.partition("|")
    digest = hashlib.sha1(etag.encode()).hexdigest()[:12]
    return root / f"{date}_{digest}.json"


def point_product_id(window: bytes) -> int | None:
    """productId of the line holding the window's last byte; 0 for the header.

    None when the window does not hold that line's start, so the point
    cannot be placed and is not kept.
    """
    if not window:
        return 0
    cut = window.rfind(b"\n", 0, len(window) - 1)
    if cut < 0 and len(window) >= 32 * 1024:
        return None
    line = window[cut + 1 :]
    head = line.split(b",", 1)[0]
    return int(head) if head.isdigit() else 0


def load(date: str, etag: str | None) -> ScanIndex:
    key = _key(date, etag)
    if key in _indexes:
        return _indexes[key]
    index = _read(key) or ScanIndex(key=key)
    _indexes[key] = index
    return index


def _read(key: str) -> ScanIndex | None:
    path = _path(key)
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != _VERSION or payload.get("key") != key:
            return None
        points = [
            IndexedPoint(
                product_id=int(item["product_id"]),
                point=AccessPoint(
                    bit_offset=int(item["bit_offset"]),
                    out_offset=int(item["out_offset"]),
                    window=zlib.decompress(base64.b64decode(item["window"])),
                ),
            )
            for item in payload["points"]
        ]
    except (OSError, ValueError, KeyError, TypeError, zlib.error):
        # A damaged or older index only costs a scan from the start.
        return None
    return ScanIndex(key=key, header=payload.get("header"), points=points)


def _write(index: ScanIndex) -> None:
    path = _path(index.key)
    if path is None:
        return
    payload = {
        "version": _VERSION,
        "key": index.key,
        "header": index.header,
        "points": [
            {
                "product_id": item.product_id,
                "bit_offset": item.point.bit_offset,
                "out_offset": item.point.out_offset,
                "window": base64.b64encode(zlib.compress(item.point.window, 6)).decode("ascii"),
            }
            for item in index.points
        ],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part")
        part.write_text(json.dumps(payload), encoding="utf-8")
        part.replace(path)
        _enforce_cap(path.parent)
    except OSError:
        # The memory copy still serves this process.
        return


def _enforce_cap(root: Path) -> None:
    files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in files[_MAX_FILES:]:
        stale.unlink(missing_ok=True)


def record(index: ScanIndex, header: str | None, points: list[AccessPoint]) -> int:
    """Add a scan's points (and the header, when it read one); returns how many were new."""
    changed = bool(header and not index.header)
    if changed:
        index.header = header
    known = {item.point.bit_offset for item in index.points}
    added = 0
    for point in points:
        product_id = point_product_id(point.window)
        if product_id is None or point.bit_offset in known:
            continue
        index.points.append(IndexedPoint(product_id=product_id, point=point))
        known.add(point.bit_offset)
        added += 1
    if added or changed:
        index.points.sort(key=lambda item: item.point.bit_offset)
        _write(index)
    return added


def best_start(index: ScanIndex, product_id: int) -> IndexedPoint | None:
    """The last point before every row of `product_id`, or None to start at byte 0."""
    if not index.header:
        return None
    chosen = None
    for item in index.points:
        if item.product_id < product_id:
            chosen = item
        else:
            break
    return chosen


def clear() -> None:
    """Forget the in-memory indexes (tests)."""
    _indexes.clear()
