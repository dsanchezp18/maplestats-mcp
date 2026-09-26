"""Client for Beyond 20/20 files on Borealis (Dataverse search and files APIs).

Checked live 2026-09-25 against borealisdata.ca:

1. File search matches file names and descriptions, not the dataset
   title: "labour force historical review" found 0 files although about
   1,160 .ivt files sit in "Labour Force Historical Review" datasets. So
   the search runs over datasets, then lists each dataset's files
   (/api/datasets/:persistentId/versions/:latest/files) and keeps .ivt.
   Some matching datasets hold only documentation (the first "Labour Force
   Historical Review" hit has a PDF and a PPT), so datasets without .ivt
   files are skipped.
2. `q` is Solr syntax and bare words are OR'd ("labour force" alone
   matched unrelated census profiles), so every word is joined with AND
   and Solr's special characters are dropped from user text.
3. When no dataset matches, a file-name search (`fileName:*.ivt`) is
   used instead; an empty query lists IVT files (3,347 in total).
4. Files download anonymously from /api/access/datafile/{id} (HTTP 206 to
   a range request); `restricted` flags the 23 that need a login.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from maplestats_mcp.modules.borealis import constants
from maplestats_mcp.modules.borealis.schemas import IvtFile, IvtSearchResult
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


def solr_query(text: str, *, ivt_files: bool) -> str:
    """Every word of `text` required; restricted to .ivt files for a file search."""
    words = re.findall(r"[\w'-]+", text)
    if ivt_files:
        words.append("fileName:*.ivt")
    return " AND ".join(words) or "*"


def r_snippet(file_id: str, file_name: str) -> str:
    path = f"data/raw/{file_name}"
    url = constants.FILE_URL.format(file_id=file_id)
    return (
        '# Install once with remotes::install_github("mountainMath/canivt").\n\n'
        "library(canivt)\n\n"
        'dir.create("data/raw", recursive = TRUE, showWarnings = FALSE)\n'
        f'download.file("{url}", "{path}", mode = "wb")\n'
        f'data <- read_ivt("{path}") |>\n  ivt_tidy()\n'
    )


async def _get(url: str, params: dict[str, Any], context: str) -> Any:
    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, params=params, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"borealis:{context} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                f"borealis:{context} did not respond in time. Try again shortly."
            ) from exc

    key = f"borealis:{url}:{sorted(params.items())}"
    payload, _ = await cached_fetch(key, constants.CACHE_TTL_SECONDS, fetch)
    data = payload.get("data") if isinstance(payload, dict) else None
    if data is None:
        raise UpstreamError(f"borealis:{context}: unexpected response shape (missing data).")
    return data


def _ivt_file(
    file_id: str,
    name: str,
    dataset: str,
    pid: str,
    size: Any,
    restricted: bool,
    published: Any,
    others: list[str],
) -> IvtFile:
    return IvtFile(
        file_id=file_id,
        file_name=name,
        dataset=dataset,
        dataset_url=constants.DATASET_URL.format(pid=pid),
        download_url=constants.FILE_URL.format(file_id=file_id),
        size_bytes=size if isinstance(size, int) else None,
        restricted=restricted,
        published=published if isinstance(published, str) else None,
        other_formats=others,
        r_snippet=r_snippet(file_id, name),
    )


async def _dataset_files(dataset: dict[str, Any]) -> list[IvtFile]:
    pid = str(dataset.get("global_id") or "")
    listing = await _get(constants.FILES_URL, {"persistentId": pid}, "dataset_files")
    entries = listing if isinstance(listing, list) else []
    names = [str(e.get("label") or "") for e in entries]
    others = sorted(n for n in names if n.lower().endswith(constants.DATA_EXTENSIONS))
    files = []
    for entry in entries:
        name = str(entry.get("label") or "")
        if not name.lower().endswith(".ivt"):
            continue
        data_file = entry.get("dataFile") or {}
        files.append(
            _ivt_file(
                str(data_file.get("id") or ""),
                name,
                str(dataset.get("name") or ""),
                pid,
                data_file.get("filesize"),
                bool(entry.get("restricted")),
                dataset.get("published_at"),
                others,
            )
        )
    return files


async def search_ivt(query: str = "", *, limit: int = constants.LIMIT_DEFAULT) -> IvtSearchResult:
    """Beyond 20/20 files in Borealis datasets matching every word of the query."""
    if limit < 1 or limit > constants.LIMIT_MAX:
        raise InvalidInput(
            f"borealis:search_ivt: limit must be between 1 and {constants.LIMIT_MAX}, got {limit}."
        )
    files: list[IvtFile] = []
    datasets_matched = 0
    if query.strip():
        found = await _get(
            constants.SEARCH_URL,
            {
                "q": solr_query(query, ivt_files=False),
                "type": "dataset",
                "per_page": constants.DATASETS_MAX,
            },
            "search_datasets",
        )
        datasets_matched = int(found.get("total_count") or 0)
        batches = await asyncio.gather(
            *(_dataset_files(item) for item in list_or_empty(found, "items"))
        )
        files = [f for batch in batches for f in batch][:limit]
    if not files:
        hits = await _get(
            constants.SEARCH_URL,
            {"q": solr_query(query, ivt_files=True), "type": "file", "per_page": limit},
            "search_files",
        )
        files = [
            _ivt_file(
                str(item.get("file_id") or ""),
                str(item.get("name") or ""),
                str(item.get("dataset_name") or ""),
                str(item.get("dataset_persistent_id") or ""),
                item.get("size_in_bytes"),
                bool(item.get("restricted")),
                item.get("published_at"),
                [],
            )
            for item in list_or_empty(hits, "items")
        ]
    return IvtSearchResult(
        files=files,
        returned_count=len(files),
        datasets_matched=datasets_matched,
        query=query,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.SEARCH_URL,
            cached=False,
            schema_name="borealis.IvtSearchResult",
            coverage=f"IVT files from the top {constants.DATASETS_MAX} matching datasets",
            limits="Only canivt (R) reads IVT files; other_formats lists any CSV twin.",
        ),
    )
