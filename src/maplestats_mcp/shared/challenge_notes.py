"""What to tell a caller when a publisher puts a page behind Cloudflare's bot check.

shared/http.py's `raise_if_cloudflare_challenge` adds the note that matches the
challenged URL to its "unavailable" error, so every tool that meets the check
says the same thing: who changed what, what still works, and the closest route
MapleStats still has to the same data. The notes are plain data (no module
imports), so loading them never imports a module's code.

Statistics Canada, checked live 2026-11-18 from a cloud host with this
project's client (HTTP/2, the maplestats-mcp User-Agent):

- Challenged (HTTP 403, Cf-Mitigated: challenge): the SDMX REST API
  (/t1/wds/sdmx/), the CIMT trade API (/t1/cimt/), The Daily's RSS feeds
  (/n1/rss/), the catalogue, search and publication pages (/n1/en/...,
  /n1/pub/... pages), and all of www12 (census pages).
- Not challenged: the Web Data Service JSON API (/t1/wds/rest/), the full-table
  CSV and SDMX zips (/n1/tbl/csv/, /n1/tbl/sdmx/), the Delta File zips
  (/n1/delta/), PUMF and LODE zips under /n1/pub/, The Daily's articles and
  its release-schedule JSON (/n1/dai-quo/ssi/), the indicators JSON, and the
  table viewer pages (/t1/tbl1/).

StatCan announced on 2026-11-16 that it would disable automated full-table
downloads; others (MountainMath's {cansim} R package) reported the zips
challenged on 2026-11-18, while from cloud hosts and the hosted MapleStats server
they still downloaded on 2026-11-20 (statcan_check_access). Which paths are
checked can differ by network and day, so the notes say what to do when a path
is challenged, not that it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ChallengeNote:
    host: str
    # Path prefixes the note covers; empty matches every path on the host.
    prefixes: tuple[str, ...]
    en: str
    fr: str


_STATCAN_EN = (
    "Statistics Canada started putting parts of its website behind this check in "
    "November 2026: a person in a web browser can pass it, but no script or automated "
    "client can, so this is StatCan's change, not a MapleStats fault, and it affects "
    "every tool and package that reads StatCan automatically. StatCan's Web Data "
    "Service (the wds_ tools: table search, metadata, series by vector or by table and "
    "coordinate, revision history, full-table links) still answers automated requests."
)
_STATCAN_FR = (
    "Statistique Canada a commencé en novembre 2026 à placer des parties de son site "
    "derrière cette vérification : une personne dans un navigateur peut la passer, mais "
    "aucun script ni client automatisé ne le peut. Il s'agit donc d'un changement de "
    "StatCan, et non d'une panne de MapleStats, qui touche tous les outils et paquets "
    "qui lisent StatCan automatiquement. Le Service de données Web de StatCan (outils "
    "wds_ : recherche de tableaux, métadonnées, séries par vecteur ou par tableau et "
    "coordonnée, historique des révisions, liens vers les tableaux complets) répond "
    "toujours aux requêtes automatisées."
)

NOTES: tuple[ChallengeNote, ...] = (
    ChallengeNote(
        "www150.statcan.gc.ca",
        ("/t1/wds/sdmx/",),
        "sdmx_get_data, sdmx_get_vector_data and sdmx_get_structure already switch to "
        "WDS on their own when SDMX is blocked; if this error still reached you, ask "
        "WDS directly: wds_get_data_from_cube_coord takes the table and a coordinate (an "
        "SDMX key with one member per dimension, e.g. 2.2 for 18-10-0004), and "
        "wds_get_cube_metadata lists the members.",
        "sdmx_get_data, sdmx_get_vector_data et sdmx_get_structure passent déjà d'eux-mêmes "
        "au WDS quand le SDMX est bloqué ; si cette erreur vous parvient quand même, "
        "interrogez le WDS directement : wds_get_data_from_cube_coord prend le tableau et "
        "une coordonnée (une clé SDMX avec un membre par dimension, p. ex. 2.2 pour "
        "18-10-0004), et wds_get_cube_metadata liste les membres.",
    ),
    ChallengeNote(
        "www150.statcan.gc.ca",
        ("/t1/cimt/",),
        "Trade by HS commodity (the cimt_ tools) has no automated route while this lasts. "
        "The closest published tables answer through WDS: 12-10-0011-01 (all countries and "
        "principal trading partners, monthly), 12-10-0163-01 (by product, NAPCS, monthly), "
        "12-10-0175-01 (by province, product and principal partner, monthly) and "
        "12-10-0171-01 to 12-10-0173-01 (by country, province and HS product section, "
        "annual); read them with wds_get_cube_metadata and wds_get_data_from_cube_coord. "
        "The HS-level figures can still be looked up by a person in the CIMT web "
        "application (https://www150.statcan.gc.ca/n1/pub/71-607-x/2021004/exp-eng.htm).",
        "Le commerce par marchandise du SH (outils cimt_) n'a pas d'accès automatisé tant "
        "que cela dure. Les tableaux publiés les plus proches répondent par le WDS : "
        "12-10-0011-01 (tous les pays et principaux partenaires commerciaux, mensuel), "
        "12-10-0163-01 (par produit, SCPAN, mensuel), 12-10-0175-01 (par province, produit "
        "et principal partenaire, mensuel) et 12-10-0171-01 à 12-10-0173-01 (par pays, "
        "province et section de produits du SH, annuel) ; lisez-les avec "
        "wds_get_cube_metadata et wds_get_data_from_cube_coord. Les chiffres au niveau du "
        "SH restent consultables par une personne dans l'application web du CICM "
        "(https://www150.statcan.gc.ca/n1/pub/71-607-x/2021004/exp-fra.htm).",
    ),
    ChallengeNote(
        "www150.statcan.gc.ca",
        ("/n1/tbl/", "/n1/delta/"),
        "This is a file download: open the link in a web browser, pass the check, and save "
        "the file. For a full table, wds_get_full_table_download also returns a Python script "
        "that rebuilds the same CSV through WDS, which StatCan still serves to scripts, and "
        "reproduce_code's R, Python and Stata scripts for it switch to WDS on their own at "
        "the captcha.",
        "Il s'agit d'un téléchargement de fichier : ouvrez le lien dans un navigateur, "
        "passez la vérification et enregistrez le fichier. Pour un tableau complet, "
        "wds_get_full_table_download fournit aussi un script Python qui reconstruit le même "
        "CSV par le WDS, que StatCan sert toujours aux scripts, et les scripts R, Python et "
        "Stata de reproduce_code passent d'eux-mêmes au WDS devant la vérification.",
    ),
    ChallengeNote(
        "www150.statcan.gc.ca",
        ("/n1/rss/",),
        "The Daily's RSS feeds are blocked: statcan_daily_get_releases with subject='all' "
        "reads the latest releases from The Daily's release archive instead, and "
        "statcan_daily_search_archive finds releases on a subject by words in their titles.",
        "Les fils RSS du Quotidien sont bloqués : statcan_daily_get_releases avec "
        "subject='all' lit les dernières diffusions dans l'archive des diffusions du "
        "Quotidien, et statcan_daily_search_archive trouve les diffusions d'un sujet par les "
        "mots de leur titre.",
    ),
    ChallengeNote(
        "www150.statcan.gc.ca",
        (),
        "This is one of StatCan's web pages (catalogue, search, publication or feed): open "
        "it in a web browser. To find tables, wds_search_cubes searches StatCan's table "
        "list through WDS; The Daily's articles and release schedule (statcan_daily_ tools) "
        "still answer. For public use microdata (PUMFs), borealis_odesi_search_datasets finds "
        "StatCan's files as deposited by Canadian university libraries (ODESI on Borealis; "
        "the Labour Force Survey of September 2026 was there on 2026-11-18), and "
        "statcan_pumf_list_zip and statcan_pumf_tabulate still read a PUMF zip from its "
        "link.",
        "Il s'agit d'une page web de StatCan (catalogue, recherche, publication ou fil) : "
        "ouvrez-la dans un navigateur. Pour trouver des tableaux, wds_search_cubes cherche "
        "dans la liste des tableaux de StatCan par le WDS ; les articles et le calendrier "
        "des diffusions du Quotidien (outils statcan_daily_) répondent toujours. Pour les "
        "microdonnées à grande diffusion (FMGD), borealis_odesi_search_datasets trouve les "
        "fichiers de StatCan déposés par les bibliothèques universitaires canadiennes (ODESI "
        "sur Borealis ; l'Enquête sur la population active de septembre 2026 y était le "
        "2026-11-18), et statcan_pumf_list_zip et statcan_pumf_tabulate lisent toujours un zip "
        "de FMGD à partir de son lien.",
    ),
    ChallengeNote(
        "www12.statcan.gc.ca",
        (),
        "The census pages on www12 have been behind this check since October 2026. 2021 "
        "Census Profile figures come through statcan_census_profile_ (api.statcan.gc.ca, "
        "not challenged), and census geography tables through statcan_geosuite_.",
        "Les pages du recensement sur www12 sont derrière cette vérification depuis octobre "
        "2026. Les chiffres du Profil du recensement de 2021 passent par "
        "statcan_census_profile_ (api.statcan.gc.ca, non bloqué), et les tableaux de "
        "géographie du recensement par statcan_geosuite_.",
    ),
)

_PUBLISHER: dict[str, tuple[str, str]] = {
    "www150.statcan.gc.ca": (_STATCAN_EN, _STATCAN_FR),
    "www12.statcan.gc.ca": (_STATCAN_EN, _STATCAN_FR),
}


def note_for(host: str, path: str) -> tuple[str, str] | None:
    """(English, French) for a challenge at host+path, or None when there is no note.

    The publisher's paragraph comes first, then the first note whose prefix
    matches the path (a note with no prefixes catches the rest of the host).
    """
    publisher = _PUBLISHER.get(host)
    specific = next(
        (
            n
            for n in NOTES
            if n.host == host and (not n.prefixes or any(path.startswith(p) for p in n.prefixes))
        ),
        None,
    )
    if publisher is None and specific is None:
        return None
    parts_en = [p for p in (publisher[0] if publisher else None, specific and specific.en) if p]
    parts_fr = [p for p in (publisher[1] if publisher else None, specific and specific.fr) if p]
    return " ".join(parts_en), " ".join(parts_fr)


# Where reproduce_code writes no script: services StatCan blocks for automated
# clients (live 2026-11-18). A script there would fail when run, so the user is
# told why instead. WDS (/t1/wds/rest/), the full-table zips (/n1/tbl/: they still
# answer most networks, and the full-table scripts rebuild through WDS where they
# get the captcha; until 2026-11-20 they were refused here), the Delta File, PUMF
# and LODE zips, and The Daily's archive JSON get scripts.
_NO_SCRIPT_PREFIXES: dict[str, tuple[str, ...]] = {
    "www150.statcan.gc.ca": (
        "/t1/wds/sdmx/",
        "/t1/cimt/",
        "/n1/rss/",
        "/n1/en/",
        "/n1/fr/",
    ),
    "www12.statcan.gc.ca": ("",),
}

_NO_SCRIPT_EN = (
    "No script: Statistics Canada blocks automated access to {url} (since November 2026 "
    "it answers scripts with a captcha only a person in a web browser can pass), so a "
    "script would fail when run. Scripts are still written for StatCan's Web Data "
    "Service: reproduce wds_get_data_from_vectors or wds_get_data_from_cube_coord for "
    "the same series."
)
_NO_SCRIPT_FR = (
    "Aucun script : Statistique Canada bloque l'accès automatisé à {url} (depuis novembre "
    "2026, il répond aux scripts par une vérification anti-robot que seule une personne "
    "dans un navigateur peut passer), si bien qu'un script échouerait. Des scripts sont "
    "toujours écrits pour le Service de données Web de StatCan : reproduisez "
    "wds_get_data_from_vectors ou wds_get_data_from_cube_coord pour les mêmes séries."
)


def script_refusal(url: str) -> tuple[str, str] | None:
    """(English, French) saying why no script is written for `url`, or None when one can be.

    A /n1/pub/ page is blocked but its .zip files are not, so only pages count there.
    """
    parsed = urlsplit(url)
    host, path = parsed.hostname or "", parsed.path
    blocked = any(path.startswith(p) for p in _NO_SCRIPT_PREFIXES.get(host, ()))
    if host == "www150.statcan.gc.ca" and path.startswith("/n1/pub/"):
        blocked = not path.lower().endswith(".zip")
    if not blocked:
        return None
    return _NO_SCRIPT_EN.format(url=url), _NO_SCRIPT_FR.format(url=url)
