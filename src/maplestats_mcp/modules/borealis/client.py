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
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from maplestats_mcp.modules.borealis import constants
from maplestats_mcp.modules.borealis.schemas import (
    IvtFile,
    IvtSearchResult,
    OdesiDataset,
    OdesiDatasetDetail,
    OdesiFile,
    OdesiSearchResult,
    OdesiVariable,
    OdesiVariableResult,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get, get_raw
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.licences import terms_not_stated
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


# --- ODESI collection (DDI metadata for StatCan PUMFs, polls, census) -------
#
# Checked live 2026-10-02:
# 1. `subtree=` accepts several aliases, so "every public collection" is one
#    search; the DLI-licensed collection is left out (its files are restricted).
# 2. The `oai_ddi` export gives study-level DDI for every dataset; the full
#    `ddi` export adds variable-level metadata but answers HTTP 403
#    {"message": "Export Failed"} for datasets without tabular variables
#    (e.g. a CORA poll whose only data is a .csv/.dta upload), which is
#    treated as "no variable metadata", not as an error.
# 3. `restricted` on a file is the only access signal: false means anyone can
#    download without logging in, even where the DDI terms still say the data
#    are for DLI members or non-commercial use. Abstracts, sampling and
#    universe come as escaped HTML (&lt;p&gt;) and are flattened to text.


def _doi(persistent_id: str) -> str:
    """Normalise 'doi:...', 'https://doi.org/...' or '10.5683/...' to 'doi:10.5683/...'."""
    text = persistent_id.strip()
    text = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", text, flags=re.IGNORECASE)
    if not re.fullmatch(r"10\.\d{4,9}/\S+", text):
        raise InvalidInput(
            f"borealis:odesi: persistent_id must be a DOI such as 'doi:10.5683/SP3/TVVQPG', "
            f"got {persistent_id!r}."
        )
    return f"doi:{text}"


def _plain(text: str | None, *, chars: int | None = None) -> str | None:
    if not text:
        return None
    # Block-level tags become spaces first; joining every text node with a space
    # would put one before the full stop after an inline <b>.
    spaced = re.sub(r"<(br|/p|/li|/ul|/h\d)[^>]*>", " ", text, flags=re.IGNORECASE)
    flat = " ".join(BeautifulSoup(spaced, "html.parser").get_text().split())
    if not flat:
        return None
    if chars is not None and len(flat) > chars:
        return flat[: chars - 1].rstrip() + "…"
    return flat


async def _get_ddi(persistent_id: str, exporter: str, context: str) -> str | None:
    """DDI XML text, or None when Borealis cannot export it (HTTP 403 'Export Failed')."""
    params = {"exporter": exporter, "persistentId": persistent_id}

    async def fetch() -> str | None:
        await _LIMITER.acquire()
        try:
            response = await get_raw(constants.DDI_EXPORT_URL, params=params, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 403:
                return None
            if status == 404:
                raise NotFound(
                    f"borealis:{context}: no dataset found for {persistent_id}."
                ) from exc
            raise UpstreamError(f"borealis:{context} returned HTTP {status}.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                f"borealis:{context} did not respond in time. Try again shortly."
            ) from exc
        return response.content.decode("utf-8", errors="replace")

    body, _ = await cached_fetch(
        f"borealis:ddi:{exporter}:{persistent_id}", constants.CACHE_TTL_SECONDS, fetch
    )
    return body


def _parse_xml(body: str, context: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise UpstreamError(f"borealis:{context}: the DDI record was not valid XML.") from exc


def _texts(root: ElementTree.Element, path: str) -> list[str]:
    found = (_plain("".join(el.itertext())) for el in root.findall(path, constants.DDI_NAMESPACE))
    return [text for text in found if text]


def _first(root: ElementTree.Element, path: str, *, chars: int | None = None) -> str | None:
    element = root.find(path, constants.DDI_NAMESPACE)
    return _plain("".join(element.itertext()), chars=chars) if element is not None else None


def _search_dataset(item: dict[str, Any]) -> OdesiDataset:
    file_count = item.get("fileCount")
    return OdesiDataset(
        title=str(item.get("name") or ""),
        persistent_id=str(item.get("global_id") or ""),
        url=str(item.get("url") or ""),
        collection=item.get("name_of_dataverse") or None,
        description=_plain(item.get("description"), chars=constants.DESCRIPTION_CHARS),
        keywords=[str(k) for k in list_or_empty(item, "keywords")],
        producers=[str(p) for p in list_or_empty(item, "producers")],
        file_count=file_count if isinstance(file_count, int) else None,
        published=item.get("published_at") or None,
    )


async def search_odesi_datasets(
    query: str = "",
    *,
    collection: str = "all_public",
    limit: int = constants.LIMIT_DEFAULT,
    start: int = 0,
) -> OdesiSearchResult:
    """ODESI datasets whose title, description or keywords match every word of the query."""
    if limit < 1 or limit > constants.LIMIT_MAX:
        raise InvalidInput(
            f"borealis:search_odesi_datasets: limit must be between 1 and "
            f"{constants.LIMIT_MAX}, got {limit}."
        )
    if start < 0:
        raise InvalidInput(f"borealis:search_odesi_datasets: start must be 0 or more, got {start}.")
    if collection == "all_public":
        aliases = constants.ODESI_PUBLIC_ALIASES
    elif collection in constants.ODESI_COLLECTIONS:
        aliases = constants.ODESI_COLLECTIONS[collection]
    else:
        raise InvalidInput(
            "borealis:search_odesi_datasets: collection must be 'all_public' or one of "
            f"{sorted(constants.ODESI_COLLECTIONS)}, got {collection!r}."
        )
    found = await _get(
        constants.SEARCH_URL,
        {
            "q": solr_query(query, ivt_files=False),
            "type": "dataset",
            "subtree": aliases,
            "per_page": limit,
            "start": start,
        },
        "search_odesi_datasets",
    )
    datasets = [_search_dataset(item) for item in list_or_empty(found, "items")]
    return OdesiSearchResult(
        query=query,
        collection=collection,
        datasets=datasets,
        returned_count=len(datasets),
        total_matched=int(found.get("total_count") or 0),
        access_note=(
            "Searches the public ODESI collections only. The DLI-licensed collection (about "
            "414 datasets, e.g. the Postal Code Conversion File) is left out: its data files "
            "need a login at a DLI-member institution. Use borealis_odesi_get_dataset to see, "
            "per dataset, which files can be downloaded without one."
        ),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.SEARCH_URL,
            cached=False,
            schema_name="borealis.OdesiSearchResult",
            coverage=f"ODESI collection on Borealis: {', '.join(aliases)}",
            limits="Every word must match; results are by Borealis relevance.",
        ),
    )


async def get_odesi_dataset(persistent_id: str) -> OdesiDatasetDetail:
    """Study-level DDI metadata and file access for one ODESI dataset."""
    pid = _doi(persistent_id)
    body = await _get_ddi(pid, "oai_ddi", "get_odesi_dataset")
    if body is None:
        raise NotFound(f"borealis:get_odesi_dataset: no DDI record for {pid}.")
    root = _parse_xml(body, "get_odesi_dataset")
    study = "d:stdyDscr/"

    periods = [
        f"{el.get('event') or 'period'} {''.join(el.itertext()).strip()}"
        for el in root.findall(f"{study}d:stdyInfo/d:sumDscr/d:timePrd", constants.DDI_NAMESPACE)
    ]
    start_end = {p.split(" ", 1)[0]: p.split(" ", 1)[1] for p in periods if " " in p}
    time_period = (
        f"{start_end['start']} to {start_end['end']}"
        if "start" in start_end and "end" in start_end
        else "; ".join(start_end.values()) or None
    )
    restriction = _first(root, f"{study}d:dataAccs/d:useStmt/d:restrctn")
    licence = _first(root, f"{study}d:dataAccs/d:notes", chars=400)
    terms = " ".join(part for part in (restriction, licence) if part) or None
    keywords = [k for k in _texts(root, f"{study}d:stdyInfo/d:subject/d:keyword")]

    listing = await _get(constants.FILES_URL, {"persistentId": pid}, "get_odesi_dataset_files")
    entries = listing if isinstance(listing, list) else []
    public: list[OdesiFile] = []
    restricted: list[str] = []
    for entry in entries:
        name = str(entry.get("label") or "")
        data_file = entry.get("dataFile") or {}
        if entry.get("restricted"):
            restricted.append(name)
            continue
        file_id = str(data_file.get("id") or "")
        size = data_file.get("filesize")
        public.append(
            OdesiFile(
                file_id=file_id,
                name=name,
                content_type=data_file.get("contentType") or None,
                size_bytes=size if isinstance(size, int) else None,
                download_url=constants.FILE_URL.format(file_id=file_id),
            )
        )
    total = len(entries)
    if total == 0:
        summary = "The dataset lists no files."
    elif not restricted:
        summary = f"All {total} files are public: download without a login."
    elif not public:
        summary = (
            f"All {total} files are restricted (DLI-licensed): they need a login at a "
            "DLI-member institution, so no download links are given."
        )
    else:
        summary = (
            f"{len(public)} of {total} files are public; {len(restricted)} are restricted "
            "(DLI-licensed) and have no link here."
        )
    version = _first(root, "d:docDscr/d:citation/d:verStmt/d:version")
    return OdesiDatasetDetail(
        title=_first(root, f"{study}d:citation/d:titlStmt/d:titl") or "",
        persistent_id=pid,
        url=f"https://doi.org/{pid.removeprefix('doi:')}",
        alt_titles=_texts(root, f"{study}d:citation/d:titlStmt/d:altTitl"),
        series=_first(root, f"{study}d:citation/d:serStmt/d:serName"),
        producers=_texts(root, f"{study}d:citation/d:prodStmt/d:producer"),
        version=f"V{version}" if version else None,
        abstract=_first(root, f"{study}d:stdyInfo/d:abstract", chars=2000),
        keywords=keywords,
        topic=_first(root, f"{study}d:stdyInfo/d:subject/d:topcClas"),
        time_period=time_period,
        geographic_coverage=_first(root, f"{study}d:stdyInfo/d:sumDscr/d:geogCover"),
        analysis_unit=_first(root, f"{study}d:stdyInfo/d:sumDscr/d:anlyUnit"),
        universe=_first(root, f"{study}d:stdyInfo/d:sumDscr/d:universe", chars=800),
        sampling=_first(root, f"{study}d:method/d:dataColl/d:sampProc", chars=800),
        collection_mode=_first(root, f"{study}d:method/d:dataColl/d:collMode"),
        terms_of_use=terms,
        citation=_first(root, "d:docDscr/d:citation/d:biblCit"),
        public_files=public,
        restricted_file_names=restricted,
        access_summary=summary,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.DDI_EXPORT_URL}?exporter=oai_ddi&persistentId={pid}",
            cached=False,
            schema_name="borealis.OdesiDatasetDetail",
            limits=(
                "File 'public' means no Borealis login; the terms of use can still limit "
                "redistribution or commercial use."
            ),
            # The dataset's own DDI terms, the same text as terms_of_use.
            licence=(
                f"Dataset terms of use (from its DDI record): {terms}"
                if terms
                else terms_not_stated(
                    "the dataset's depositor on Borealis",
                    f"https://doi.org/{pid.removeprefix('doi:')}",
                )
            ),
        ),
    )


async def search_odesi_variables(
    persistent_id: str, query: str = "", *, limit: int = constants.VARIABLES_LIMIT_DEFAULT
) -> OdesiVariableResult:
    """Variable names and labels from one dataset's variable-level DDI."""
    pid = _doi(persistent_id)
    if limit < 1 or limit > constants.VARIABLES_LIMIT_MAX:
        raise InvalidInput(
            f"borealis:search_odesi_variables: limit must be between 1 and "
            f"{constants.VARIABLES_LIMIT_MAX}, got {limit}."
        )
    body = await _get_ddi(pid, "ddi", "search_odesi_variables")
    url = f"{constants.DDI_EXPORT_URL}?exporter=ddi&persistentId={pid}"
    provenance = make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=url,
        cached=False,
        schema_name="borealis.OdesiVariableResult",
    )
    if body is None:
        return OdesiVariableResult(
            persistent_id=pid,
            query=query,
            returned_count=0,
            total_matched=0,
            total_variables=0,
            note=(
                "Borealis has no variable-level DDI for this dataset (its export fails when "
                "the data are not ingested as tabular files). Read the codebook among its "
                "files (borealis_odesi_get_dataset) instead."
            ),
            provenance=provenance,
        )
    root = _parse_xml(body, "search_odesi_variables")
    file_names = {
        f.get("ID"): _first(f, "d:fileTxt/d:fileName")
        for f in root.findall("d:fileDscr", constants.DDI_NAMESPACE)
    }
    variables: list[OdesiVariable] = []
    for var in root.findall("d:dataDscr/d:var", constants.DDI_NAMESPACE):
        location = var.find("d:location", constants.DDI_NAMESPACE)
        label = var.find("d:labl", constants.DDI_NAMESPACE)
        variables.append(
            OdesiVariable(
                name=var.get("name") or "",
                label=_plain("".join(label.itertext())) if label is not None else None,
                file_name=file_names.get(location.get("fileid")) if location is not None else None,
                categories=len(var.findall("d:catgry", constants.DDI_NAMESPACE)),
            )
        )
    words = re.findall(r"\w+", query.casefold())
    matched = [
        v for v in variables if all(w in f"{v.name} {v.label or ''}".casefold() for w in words)
    ]
    page = matched[:limit]
    return OdesiVariableResult(
        persistent_id=pid,
        query=query,
        variables=page,
        returned_count=len(page),
        total_matched=len(matched),
        total_variables=len(variables),
        provenance=provenance,
    )
