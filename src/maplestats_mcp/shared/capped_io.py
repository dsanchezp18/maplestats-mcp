"""Size caps for bulk files written to disk (downloads and ZIP members).

A download or an unpacked ZIP member is written straight to the cache
folder, so a link that serves more than expected (or a ZIP whose members
inflate far past their compressed size) would fill the disk before the
cache cap, which only runs afterwards, could act. The caller passes the
cache cap: a single file larger than the whole cache could not be kept
anyway.
"""

from __future__ import annotations

from typing import IO

from maplestats_mcp.shared.errors import UpstreamError


class FileTooLarge(UpstreamError):
    """A file passed the byte cap while being written."""


def check_size(total: int, cap: int, what: str) -> None:
    """Raise FileTooLarge once `total` bytes passes `cap`."""
    if total > cap:
        raise FileTooLarge(
            f"{what} is larger than the {cap / 1e6:,.0f} MB this server keeps for one file; "
            "stopped writing it."
        )


def copy_capped(source: IO[bytes], sink: IO[bytes], cap: int, what: str) -> int:
    """Copy `source` to `sink` in 1 MB steps, raising FileTooLarge past `cap` bytes."""
    total = 0
    while chunk := source.read(1 << 20):
        total += len(chunk)
        check_size(total, cap, what)
        sink.write(chunk)
    return total


__all__ = ["FileTooLarge", "check_size", "copy_capped"]
