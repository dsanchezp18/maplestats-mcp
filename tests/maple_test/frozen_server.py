"""Serve MapleStats over stdio with its upstream HTTP frozen in a cassette.

A Maple Test run asks the publishers for the same figures on every pass and every rerun,
and the figures move: StatCan revised C-14 between two runs, and WDS has blocked this
laptop after heavy use. With `run --frozen CASSETTE`, the maplestats arm starts the server
through this file instead, which wraps every HTTP request the server makes:

- `auto` (default): a request already in the cassette is answered from it; a new one goes
  to the publisher and its response is added. The first run records, later runs replay.
- `replay`: only the cassette; a request not in it fails as a network error (the server
  reports the source as unreachable), so a run is fully offline and cannot drift.
- `record`: always the publisher, overwriting what the cassette held.

Requests are matched on method, URL and body. The cassette is a gzipped JSON lines file;
keep one per key build (`v4/cassettes/<date>.jsonl.gz`), outside git if it grows large.
Only MapleStats can be frozen this way: other arms are other people's servers.

This file runs inside the served checkout's environment (`uv run --directory <checkout>
python <this file>`), so it imports nothing from this repository's tests.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

import httpx

KEPT_HEADERS = ("content-type", "content-disposition", "etag", "last-modified", "location")
DECODED = ("content-encoding", "content-length", "transfer-encoding")


def _key(request: httpx.Request) -> str:
    body = hashlib.sha256(request.content or b"").hexdigest()
    return f"{request.method} {request.url} {body}"


class Cassette:
    def __init__(self, path: Path, mode: str) -> None:
        self.path, self.mode = path, mode
        self.lock = threading.Lock()
        self.items: dict[str, dict[str, Any]] = {}
        if path.exists() and mode != "record":
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        row = json.loads(line)
                        self.items[row["key"]] = row

    def add(self, key: str, response: httpx.Response, body: bytes) -> None:
        row = {
            "key": key,
            "status": response.status_code,
            "headers": {k: v for k, v in response.headers.items() if k.lower() in KEPT_HEADERS},
            "body": base64.b64encode(body).decode(),
        }
        with self.lock:
            self.items[key] = row
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(self.path, "at", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")


def install(cassette: Cassette) -> None:
    """Patch httpx.AsyncClient.send, under MapleStats' BreakerClient and every source."""
    real_send = httpx.AsyncClient.send

    async def send(self: httpx.AsyncClient, request: httpx.Request, *args: Any, **kwargs: Any):
        key = _key(request)
        row = cassette.items.get(key) if cassette.mode != "record" else None
        if row is not None:
            return httpx.Response(
                row["status"],
                headers=row["headers"],
                content=base64.b64decode(row["body"]),
                request=request,
            )
        if cassette.mode == "replay":
            raise httpx.ConnectError(f"not in the cassette: {key[:200]}", request=request)
        response = await real_send(self, request, *args, **kwargs)
        body = await response.aread()
        cassette.add(key, response, body)
        # The body is decoded already: replaying content-encoding would decode it twice.
        headers = {k: v for k, v in response.headers.items() if k.lower() not in DECODED}
        return httpx.Response(response.status_code, headers=headers, content=body, request=request)

    httpx.AsyncClient.send = send  # type: ignore[method-assign]


def main() -> int:
    parser = argparse.ArgumentParser(prog="frozen_server.py")
    parser.add_argument("--cassette", type=Path, required=True)
    parser.add_argument("--mode", choices=("auto", "replay", "record"), default="auto")
    args = parser.parse_args()
    install(Cassette(args.cassette, args.mode))
    os.environ.setdefault("MAPLE_TRANSPORT", "stdio")
    from maplestats_mcp.__main__ import main as serve

    serve([])
    return 0


if __name__ == "__main__":
    sys.exit(main())
