"""Resolve bulk download links for archived (pre-2021) Census Profiles.

See constants.py for what was confirmed live and how each year's
resolver was found. Links are constructed from the confirmed URL
templates rather than re-verified with a live request per call --
several of these files are tens to hundreds of megabytes (2011
dissemination areas CSV is roughly 194 MB), so fetching one on every
`get_download_link` call would be slow and wasteful for what is a
deterministic, already-confirmed substitution.
"""

from __future__ import annotations

from maplestats_mcp.modules.statcan.census_profile_archive import constants
from maplestats_mcp.modules.statcan.census_profile_archive.schemas import (
    DownloadLink,
    GeographyLevelList,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import CloudflareChallenge, InvalidInput
from maplestats_mcp.shared.http import get_raw


async def _blocked_note() -> str | None:
    """A provenance.limits note while www12 serves its Cloudflare challenge.

    These tools only build URLs, and every URL points at www12, so a success
    would otherwise hide that scripts cannot download the files (checked
    2026-10-02: 403 managed challenge). One cheap page request, cached for
    15 minutes, tells whether that still holds; any other failure adds no note
    (the tool has not claimed the files are fetchable).
    """

    async def probe() -> bool:
        try:
            await get_raw(constants.REACHABILITY_URL, timeout=15.0)
        except CloudflareChallenge:
            return True
        except Exception:  # noqa: BLE001 - only the challenge matters here
            return False
        return False

    blocked, _ = await cached_fetch(
        "statcan-census-profile-archive:www12-blocked", constants.PROBE_TTL_SECONDS, probe
    )
    return constants.BLOCKED_NOTE if blocked else None


async def list_geography_levels(year: int) -> GeographyLevelList:
    """List the geography levels and file formats available for one archived census year."""
    config = constants.YEAR_CONFIG.get(year)
    if config is None:
        raise InvalidInput(
            f"statcan_census_profile_archive:list_geography_levels: year must be one of "
            f"{sorted(constants.YEAR_CONFIG)}, got {year!r}."
        )
    return GeographyLevelList(
        year=year,
        levels=sorted(config["levels"]),
        formats=list(config["formats"]),
        provenance=make_provenance(
            source="statcan-census-profile-archive",
            url=config["base_url"],
            cached=False,
            schema_name="statcan_census_profile_archive.GeographyLevelList",
            limits=await _blocked_note(),
        ),
    )


async def get_download_link(
    year: int, level: str, file_format: str, lang: str = "en"
) -> DownloadLink:
    """Resolve the direct bulk-download URL for one archived census year/level/format.

    `lang="fr"` returns the French-language file (translated headers and
    characteristic names), not just a French landing page.
    """
    config = constants.YEAR_CONFIG.get(year)
    if config is None:
        raise InvalidInput(
            f"statcan_census_profile_archive:get_download_link: year must be one of "
            f"{sorted(constants.YEAR_CONFIG)}, got {year!r}."
        )
    level_code = config["levels"].get(level)
    if level_code is None:
        raise InvalidInput(
            f"statcan_census_profile_archive:get_download_link: level must be one of "
            f"{sorted(config['levels'])} for year {year}, got {level!r}."
        )
    file_format = file_format.upper()
    if file_format not in config["formats"]:
        raise InvalidInput(
            f"statcan_census_profile_archive:get_download_link: file_format must be one of "
            f"{config['formats']} for year {year}, got {file_format!r}."
        )

    if config["style"] == "geono":
        lang_code = "F" if lang == "fr" else "E"
        url = f"{config['base_url']}?Lang={lang_code}&FILETYPE={file_format}&GEONO={level_code}"
    else:
        catalogue = config["catalogue_fr"] if lang == "fr" else config["catalogue"]
        url = f"{config['base_url']}?CTLG={catalogue}&FMT={file_format}{level_code}"

    return DownloadLink(
        year=year,
        level=level,
        file_format=file_format,
        language=lang,
        url=url,
        provenance=make_provenance(
            source="statcan-census-profile-archive",
            url=config["base_url"],
            cached=False,
            schema_name="statcan_census_profile_archive.DownloadLink",
            limits=await _blocked_note(),
        ),
    )
