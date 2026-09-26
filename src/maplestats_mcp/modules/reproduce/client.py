"""reproduce_code: the same data, fetched and cleaned by an R, Python, Stata
or Julia script the server writes.

Three routes, most exact first:

1. builders.py: the request is rebuilt from the tool's arguments (StatCan
   tables and vectors, Valet, Socrata, CKAN DataStore, PUMF, census
   tables), or the tool downloads a whole file and filters it itself, so
   the script repeats those filters (CanadaBuys, CER, GC InfoBase, CIHI,
   IRCC, StatCan indicators). IP Horizons patents join bulk files
   (ip_horizons.py).
2. Every other tool runs once while shared/http.py records its upstream
   requests; the data request (URL with every parameter, POST body,
   Accept header) is replayed once to confirm the format and find the
   rows (probe.py). Arguments that never reached the source are listed,
   since the script cannot repeat them.
3. Where no script can fetch the data (a browser-session form, a page
   of prose), the result says so instead of returning a broken script.

render.py writes each script in the house layout: header, numbered
sections, every package loaded in setup, downloads saved under data/raw/.
"""

from __future__ import annotations

import json
from typing import Any

from maplestats_mcp.modules.reproduce import builders, ip_horizons, probe
from maplestats_mcp.modules.reproduce.render import RENDERERS
from maplestats_mcp.modules.reproduce.schemas import (
    Language,
    LanguageChoice,
    ReproductionCode,
    Script,
)
from maplestats_mcp.modules.reproduce.spec import Spec
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.http import RecordedRequest, recording

_NOT_DATA = ("reproduce_code", "plan_query", "search_tools", "call_tool")
_IP_HORIZONS = ("ised_ip_horizons_get_patent", "ised_ip_horizons_search_patents")


async def _run_tool(
    tool: str, args: dict[str, Any]
) -> tuple[dict[str, Any], list[RecordedRequest]]:
    """The tool's result and every upstream request it made (cache bypassed)."""
    # Lazy import: the server imports this module's tools at startup.
    from fastmcp import Client
    from mcp.types import TextContent

    from maplestats_mcp.server import mcp

    with recording() as requests:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "call_tool", {"name": tool, "arguments": args}, raise_on_error=False
            )
    text = next((block.text for block in result.content if isinstance(block, TextContent)), "")
    if result.is_error:
        raise InvalidInput(
            f"{tool} failed with these arguments, so there is nothing to reproduce: {text[:300]}"
        )
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise NotFound(f"{tool} did not return a structured result.") from exc
    return (payload if isinstance(payload, dict) else {}), list(requests)


async def _spec(tool: str, args: dict[str, Any]) -> Spec:
    builder = builders.builder_for(tool, args)
    if builder is not None and builders.argument_only(tool, args):
        return await builder(args, {})
    payload, requests = await _run_tool(tool, args)
    if tool in _IP_HORIZONS:
        return await ip_horizons.build(tool, args, payload)
    if builder is not None:
        return await builder(args, payload)
    chosen, pages = probe.choose(requests, str(payload.get("provenance", {}).get("url") or ""))
    if chosen is None and requests and all(r.method == "HEAD" for r in requests):
        # canadabuys_list_bulk_files only checks that each file exists
        # (HEAD); its base URL is a directory that answers 404.
        return Spec(
            kind="none",
            url=str(payload.get("provenance", {}).get("url") or ""),
            file_name="",
            method="none",
            notes=[
                (
                    "This tool only lists download links (it checks each file with HEAD). "
                    "Reproduce the tool that reads the file you pick, or download its URL."
                )
            ],
        )
    if chosen is None:
        url = str(payload.get("provenance", {}).get("url") or "")
        if not url.startswith("http"):
            return Spec(
                kind="none",
                url=url,
                file_name="",
                method="none",
                notes=[
                    (
                        "This tool reads MapleStats' own registry or cache, not a source "
                        "download, so there is nothing to fetch."
                    )
                ],
            )
        # A module-level cache served the result; replay its source URL.
        chosen = RecordedRequest("GET", url, b"", "", status=200)
        pages = 1
    spec = await probe.spec_from_request(chosen, pages)
    unsent = probe.unsent_arguments(args, chosen)
    if unsent and spec.kind != "none":
        spec.notes.append(
            "The tool applied these arguments itself after downloading, so the script "
            f"returns the unfiltered response: {', '.join(unsent)}."
        )
    return spec


async def reproduce(
    tool: str, arguments: dict[str, Any], language: LanguageChoice = "all"
) -> ReproductionCode:
    requested: list[Language] = (
        ["r", "python", "stata", "julia"] if language == "all" else [language]  # type: ignore[list-item]
    )
    if any(lang not in RENDERERS for lang in requested):
        raise InvalidInput(
            f"language must be 'all' or one of {sorted(RENDERERS)}, got {language!r}."
        )
    if tool in _NOT_DATA:
        raise InvalidInput(f"{tool} does not fetch data, so there is nothing to reproduce.")
    try:
        spec = await _spec(tool, arguments)
    except KeyError as exc:
        raise InvalidInput(f"{tool} is missing the argument {exc.args[0]!r}.") from exc

    scripts: list[Script] = []
    skipped: list[str] = []
    for lang in requested:
        rendered = (
            RENDERERS[lang](spec, tool) if spec.kind != "none" and lang in spec.languages else None
        )
        if rendered is None:
            skipped.append(lang)
            continue
        code, packages = rendered
        scripts.append(Script(language=lang, code=code, packages=packages))
    notes = list(spec.notes)
    if skipped and spec.kind not in ("none",):
        reason = {
            "ivt": "Beyond 20/20 files are read only by canivt (R)",
            "html_table": "Julia has no maintained HTML table reader",
            "feed": "Julia has no maintained RSS/Atom reader",
        }.get(spec.kind, "this language cannot read the source")
        notes.append(f"No {', '.join(skipped)} script: {reason}.")
    if spec.kind == "zip":
        notes.append("The script unzips the archive; pick the data file inside it.")
    return ReproductionCode(
        tool=tool,
        scripts=scripts,
        source_url=spec.url,
        method=spec.method,
        notes=notes,
        provenance=make_provenance(
            source="maplestats-reproduce",
            url=spec.url or "about:blank",
            cached=False,
            schema_name="reproduce.ReproductionCode",
        ),
    )
