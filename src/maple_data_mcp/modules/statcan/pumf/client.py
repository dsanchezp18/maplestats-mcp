"""Client for StatCan PUMF discovery, file listing and codebooks."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx

from maple_data_mcp.modules.statcan.pumf import codebooks, constants
from maple_data_mcp.modules.statcan.pumf.schemas import (
    Codebook,
    PumfFile,
    PumfFileList,
    PumfProduct,
    PumfSearchResult,
    PumfVariable,
    ZipContents,
    ZipEntry,
)
from maple_data_mcp.modules.statcan.reference import client as reference
from maple_data_mcp.shared import remote_zip
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import get_raw
from maple_data_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_CATALOGUE = re.compile(r"^[0-9A-Za-z-]{6,14}$")
_WEIGHT_NAME = re.compile(r"^(WT|WGT|BSW|FWGT)|WEIGHT|FINALWT|PERSWT|HHWT")
_WEIGHT_LABEL = re.compile(r"(?i)weight|poids|pond[eé]ration")
_NOT_WEIGHT_LABEL = re.compile(r"(?i)inclusion|flag|percei|perception|height|taille|overweight")
_REPLICATE = re.compile(r"(?i)replicate|bootstrap|r[ée]plique")
_MAIN_WEIGHT_LABEL = re.compile(
    r"(?i)survey weight|final weight|weighting factor|weights? - master|sample weight|"
    r"^weight\b|poids d.enqu|poids final|poids [ée]chantillon"
)
_OTHER_LANGUAGE = {
    "en": ("fran", "/fr/", "_fr", "lbf", "varf", "valf", "pff", " fr"),
    "fr": ("english", "/en/", "_en", "lbe", "vare", "vale", "pfe", " en."),
}
_SAS_ROLES = {
    "_i.sas": "input",
    "_lbe.sas": "labels",
    "_lbf.sas": "labels",
    "_fmt.sas": "formats",
    "_pfe.sas": "values",
    "_pff.sas": "values",
}


def _check_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != constants.ALLOWED_HOST:
        raise InvalidInput(f"url must be a {constants.ALLOWED_HOST} download link, got {url!r}.")
    if not parsed.path.lower().endswith(".zip"):
        raise InvalidInput(f"url must point to a .zip file, got {url!r}.")
    return url


async def _page(url: str) -> str:
    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise NotFound(f"statcan_pumf: no page at {url}.") from exc
            raise UpstreamError(
                f"statcan_pumf: {url} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"statcan_pumf: {url} could not be reached.") from exc
        return response.text

    text, _ = await cached_fetch(f"statcan_pumf:{url}", constants.CACHE_TTL_SECONDS, fetch)
    return text


async def search(query: str = "", *, lang: str = "en", limit: int = 25) -> PumfSearchResult:
    if limit < 1 or limit > 100:
        raise InvalidInput(f"limit must be between 1 and 100, got {limit}.")
    phrase = "public use microdata" if lang == "en" else "fichiers de microdonnées"
    result = await reference.search_data(f"{query} {phrase}".strip(), count=100, lang=lang)
    products = [
        PumfProduct(
            catalogue_number=doc.catalogue_number or "",
            title=doc.title,
            url=doc.url,
            release_date=doc.release_date,
            description=doc.description,
        )
        for doc in result.documents
        if "microd" in (doc.category or "").lower() and doc.catalogue_number
    ]
    return PumfSearchResult(
        query=query,
        products=products[:limit],
        total_matched=len(products),
        provenance=result.provenance,
    )


async def list_files(catalogue_number: str, *, lang: str = "en") -> PumfFileList:
    number = catalogue_number.strip().replace("-", "")
    if not _CATALOGUE.match(number):
        raise InvalidInput(
            f"catalogue_number looks like 71M0001X or 45-25-0001, got {catalogue_number!r}."
        )
    url = constants.CATALOGUE_URL.format(lang=lang, number=number)
    html = await _page(url)
    suffix = "-eng.htm" if lang == "en" else "-fra.htm"
    pubs = sorted(
        {
            urljoin(url, href)
            for href in re.findall(r'href="([^"]*/n1/pub/[^"]+' + suffix + ')"', html)
        }
    )[-constants.MAX_PUB_PAGES :]
    files: dict[str, PumfFile] = {}
    for page_url, page in [(url, html)] + [(p, await _page(p)) for p in pubs]:
        for href, text in re.findall(
            r'<a[^>]+href="([^"]+\.zip)"[^>]*>(.*?)</a>', page, re.DOTALL | re.IGNORECASE
        ):
            zip_url = urljoin(page_url, href)
            label = " ".join(re.sub(r"<[^>]+>", " ", text).split()) or zip_url.rsplit("/", 1)[-1]
            files.setdefault(zip_url, PumfFile(label=label, url=zip_url, page_url=page_url))
    if not files:
        raise NotFound(
            f"No direct ZIP download found for {catalogue_number}; it may be available only "
            "through the Data Liberation Initiative (DLI) or on request."
        )
    return PumfFileList(
        catalogue_number=number,
        files=list(files.values()),
        pages_read=[url, *pubs],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=False,
            schema_name="statcan_pumf.PumfFileList",
            freshness="StatCan product pages; cached 1 day",
        ),
    )


async def _members(url: str) -> tuple[list[remote_zip.ZipMember], int, bool]:
    async def fetch() -> tuple[list[remote_zip.ZipMember], int]:
        await _LIMITER.acquire()
        return await remote_zip.list_members(url)

    (members, total), cached = await cached_fetch(
        f"statcan_pumf:zip:{url}", constants.CACHE_TTL_SECONDS, fetch
    )
    return members, total, cached


def _decode(raw: bytes) -> str:
    # The French Census files are UTF-8, the rest CP1252 (checked live).
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _is_codebook(name: str) -> bool:
    lower = name.lower()
    if "bsw" in lower or lower.endswith("/"):
        return False
    return (
        (lower.endswith(".csv") and "codebook" in lower)
        or lower.endswith((".dct", ".do"))
        or re.search(r"_va[lr][ef]\.sps$", lower) is not None
    )


def _for_language(names: list[str], lang: str) -> list[str]:
    other = _OTHER_LANGUAGE[lang]
    kept = [n for n in names if not any(marker in n.lower() for marker in other)]
    return kept or names


async def list_zip(url: str) -> ZipContents:
    members, total, cached = await _members(_check_url(url))
    files = [m for m in members if not m.name.endswith("/")]
    return ZipContents(
        url=url,
        archive_bytes=total,
        entries=[ZipEntry(name=m.name, size_bytes=m.size) for m in files],
        codebook_files=[m.name for m in files if _is_codebook(m.name)],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="statcan_pumf.ZipContents",
            limits="read with HTTP range requests; the archive itself was not downloaded",
        ),
    )


async def load_codebook(url: str, lang: str = "en") -> tuple[list[PumfVariable], list[str], bool]:
    """Every variable in a PUMF ZIP's codebook, the files read, and whether cached."""
    members, _, cached = await _members(_check_url(url))
    by_name = {m.name: m for m in members}
    chosen = _for_language([m.name for m in members if _is_codebook(m.name)], lang)
    # One format is enough; the CSV codebook is the most complete when present.
    csvs = [n for n in chosen if n.lower().endswith(".csv")]
    chosen = csvs or [n for n in chosen if not n.lower().endswith("_infmt.do")]
    sas_roles: dict[str, str] = {}
    if not chosen:
        # SAS-only PUMFs (CSWC): input positions, labels, formats, PROC FORMAT values.
        sas_files = _for_language(
            [
                m.name
                for m in members
                if m.name.lower().endswith(".sas") and "bsw" not in m.name.lower()
            ],
            lang,
        )
        for name in sas_files:
            for suffix, role in _SAS_ROLES.items():
                if name.lower().endswith(suffix):
                    sas_roles[name] = role
        chosen = list(sas_roles)
    if not chosen:
        raise NotFound("No codebook this tool can read in the ZIP.")

    texts: dict[str, str] = {}
    for name in chosen:

        async def fetch(member: remote_zip.ZipMember = by_name[name]) -> str:
            await _LIMITER.acquire()
            return _decode(await remote_zip.read_member(url, member))

        texts[name], _ = await cached_fetch(
            f"statcan_pumf:member:{url}:{name}", constants.CACHE_TTL_SECONDS, fetch
        )

    variables: codebooks.Variables = {}
    # Stata label sets are often defined in one .do file (_fmt.do) and
    # attached in another (_vale.do), so the .do files are parsed as one.
    do_text = "\n".join(t for n, t in texts.items() if n.lower().endswith(".do"))
    if do_text:
        codebooks.merge(variables, codebooks.parse_stata_do(do_text))
    for name, text in texts.items():
        lower = name.lower()
        if lower.endswith(".csv"):
            codebooks.merge(variables, codebooks.parse_codebook_csv(text, lang))
        elif lower.endswith(".dct"):
            codebooks.merge(variables, codebooks.parse_stata_dct(text))
        elif lower.endswith(".sps"):
            codebooks.merge(variables, codebooks.parse_spss(text))
    if sas_roles:
        codebooks.merge(
            variables, codebooks.parse_sas({role: texts[name] for name, role in sas_roles.items()})
        )

    everything = sorted(
        variables.values(), key=lambda v: (v.position is None, v.position or 0, v.name)
    )
    return everything, chosen, cached


def weight_names(variables: list[PumfVariable]) -> list[str]:
    """Likely weights, main weight first.

    Names alone mislead (checked 2026-09-24): CSWC's WTQ_05 is "Working
    time - Works at night" and CCHS's DOHWT is "Height and weight -
    Inclusion Flag". Real weights are wide numeric fields (5 to 16
    columns), so a known width under 4 rules a variable out.
    """
    candidates = [
        v
        for v in variables
        if (_WEIGHT_NAME.search(v.name) or _WEIGHT_LABEL.search(v.label or ""))
        and not _NOT_WEIGHT_LABEL.search(v.label or "")
        and (v.width is None or v.width >= 4)
    ]

    def rank(v: PumfVariable) -> tuple[int, int]:
        label = v.label or ""
        replicate = bool(_REPLICATE.search(label) or re.search(r"\d$", v.name))
        return (1 if replicate else 0, 0 if _MAIN_WEIGHT_LABEL.search(label) else 1)

    return [v.name for v in sorted(candidates, key=rank)]


def main_weight(variables: list[PumfVariable]) -> str | None:
    names = weight_names(variables)
    by_name = {v.name: v for v in variables}
    for name in names:
        label = by_name[name].label or ""
        if not _REPLICATE.search(label) and not re.search(r"\d$", name):
            return name
    return None


async def get_codebook(
    url: str,
    *,
    query: str | None = None,
    lang: str = "en",
    limit: int = constants.VARIABLES_DEFAULT,
) -> Codebook:
    if limit < 1 or limit > constants.VARIABLES_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.VARIABLES_MAX}, got {limit}.")
    loaded, chosen, cached = await load_codebook(url, lang)
    # Copies: the loaded list is cached per ZIP, and values are truncated below.
    everything = [v.model_copy(deep=True) for v in loaded]
    needle = (query or "").strip().lower()
    matched = [
        v
        for v in everything
        if not needle
        or needle in v.name.lower()
        or needle in (v.label or "").lower()
        or any(needle in value.label.lower() for value in v.values)
    ]
    kept = matched[:limit]
    for variable in kept:
        if len(variable.values) > constants.VALUES_PER_VARIABLE:
            variable.values = variable.values[: constants.VALUES_PER_VARIABLE]
            variable.values_truncated = True
    return Codebook(
        url=url,
        source_files=chosen,
        variables=kept,
        total_variables=len(everything),
        matched_variables=len(matched),
        weight_variables=weight_names(everything),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="statcan_pumf.Codebook",
            limits="codebook files read from inside the ZIP by range request; microdata not downloaded",
        ),
    )
