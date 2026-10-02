"""Is a CKAN dataset's licence an open one? One rule set for every portal.

Licence ids differ per portal (checked live 2026-10-02 with license_list):
federal `ca-ogl-lgo`, Ontario `OGL-ON-1.0`, BC numeric ids ("2" is the Open
Government Licence - BC, "22" is "Access Only", "25" the King's Printer
Licence), Montreal and Québec Creative Commons ids, Toronto `notspecified` or
none. The id alone is not enough, so the rules read the id and the title
together. Anything not clearly open gets a plain warning: the reader's
promise is that a number is never handed over without saying under what
terms it may be reused.
"""

from __future__ import annotations

import re
from typing import Literal

LicenceStatus = Literal["open", "non_commercial", "restricted", "not_stated", "unrecognised"]

# Terms of use, access-only and printer's-licence records are not open
# licences: Ontario other-closed / *-tou / public-sector-sda / queens-printers-on,
# BC "22" Access Only and "25" King's Printer, Alberta KPTU / OGNL, federal ab-qptu.
_RESTRICTED = re.compile(
    r"(-tou$|^tou-|terms[ -]of[ -]use|access only|other-closed|not open|not applicable|"
    r"public-sector-sda|salary disclosure|(king|queen)'?s?[ -]?printer|printers-on|"
    r"^kptu$|^qptu$|ab-qptu|^ognl$|no licence|crown copyright|reproduction of federal laws)",
    re.IGNORECASE,
)
_NON_COMMERCIAL = re.compile(
    r"(-nc(-|$)|non-?commercial|other-nc|pas d.utilisation commerciale)", re.IGNORECASE
)
_OPEN = re.compile(
    r"(ogl|open government|open data licen|open licen|open data commons|odc-|pddl|"
    r"\bcc-?by\b|cc-by|cc0|creative commons|public domain|other-open|other-pd|other-at|"
    r"gnwt|gofc|statistics[ -]canada[ -]open|statcan-open|apache|unrestricted use|"
    r"openmb|ca-odla|domaine public|attribution)",
    re.IGNORECASE,
)
_NOT_STATED = re.compile(r"^(notspecified|not specified|none|null|unspecified)?$", re.IGNORECASE)

WARNINGS = {
    "en": {
        "non_commercial": "Non-commercial licence ({licence}): do not reuse commercially.",
        "restricted": "NOT an open licence ({licence}): terms of use, access-only or "
        "printer's-licence conditions apply. Check {url} before reusing or redistributing.",
        "not_stated": "No licence is stated for this dataset: do not assume it is open. "
        "Check {url} or ask the publisher.",
        "unrecognised": "Licence '{licence}' is not one this server recognises as open. "
        "Read its terms at {url} before reusing.",
    },
    "fr": {
        "non_commercial": "Licence non commerciale ({licence}) : ne pas réutiliser à des fins "
        "commerciales.",
        "restricted": "PAS une licence ouverte ({licence}) : des conditions d'utilisation, "
        "d'accès seulement ou de licence de l'imprimeur s'appliquent. Vérifier {url} avant "
        "toute réutilisation ou redistribution.",
        "not_stated": "Aucune licence n'est indiquée pour ce jeu de données : ne pas supposer "
        "qu'il est ouvert. Vérifier {url} ou demander à l'éditeur.",
        "unrecognised": "La licence « {licence} » n'est pas reconnue comme ouverte par ce "
        "serveur. Lire ses conditions à {url} avant toute réutilisation.",
    },
}


def classify(licence_id: str | None, licence_title: str | None) -> LicenceStatus:
    """Open, non-commercial, restricted, not stated, or unrecognised."""
    ident = (licence_id or "").strip()
    title = (licence_title or "").strip()
    text = f"{ident} {title}".strip()
    if _RESTRICTED.search(ident) or _RESTRICTED.search(title):
        return "restricted"
    if _NON_COMMERCIAL.search(ident) or _NON_COMMERCIAL.search(title):
        return "non_commercial"
    # Regina's only licence id is `notspecified` titled "Open Gov. License".
    if _OPEN.search(text) or re.search(r"open gov", text, re.IGNORECASE):
        return "open"
    if _NOT_STATED.match(ident) and _NOT_STATED.match(title):
        return "not_stated"
    if _NOT_STATED.match(ident) and title.lower() in (
        "license not specified",
        "licence not specified",
    ):
        return "not_stated"
    return "unrecognised"


def warning(status: LicenceStatus, licence: str, url: str, lang: str = "en") -> str | None:
    """The plain-language warning for a licence that is not clearly open, else None."""
    if status == "open":
        return None
    return WARNINGS["fr" if lang == "fr" else "en"][status].format(licence=licence, url=url)
