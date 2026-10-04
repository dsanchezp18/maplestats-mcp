"""Licence and attribution text for `provenance.licence`, one constant per publisher's terms.

`make_provenance` fills `provenance.licence` from `licence_for(source, url)`
when a module does not pass one, so a reader always finds the terms in the
same field rather than in `limits`, `freshness` or `coverage`. A module
whose terms vary by record (a catalogue's datasets, a transit feed, a BC
Stats file built from Statistics Canada tables) passes the record's own
licence explicitly instead.

Each text names the licence or terms, links them, and gives the
attribution the publisher asks for. Wording and URLs were read from each
publisher's terms page on 2026-10-03. Where a publisher states no terms
for the data, the text says so (`terms_not_stated`) rather than assuming
an open licence.
"""

from __future__ import annotations

from maplestats_mcp.shared.i18n import t

# The Statistics Canada Open Licence text lives in shared/i18n (English and
# French); envelope.make_provenance picks the call's language.
STATCAN_LICENCE = t("provenance.statcan_licence", "en")

OGL_CANADA = (
    "Open Government Licence - Canada 2.0 (https://open.canada.ca/en/open-government-licence-canada). "
    "Attribution: 'Contains information licensed under the Open Government Licence - Canada.'"
)

OGL_ALBERTA = (
    "Open Government Licence - Alberta (https://open.alberta.ca/licence). "
    "Attribution: 'Contains information licensed under the Open Government Licence - Alberta.'"
)

OGL_BC = (
    "Open Government Licence - British Columbia 2.0 "
    "(https://www2.gov.bc.ca/gov/content/data/policy-standards/open-data/open-government-licence-bc). "
    "Attribution: 'Contains information licensed under the Open Government Licence - British "
    "Columbia.'"
)

OGL_YUKON = (
    "Open Government Licence - Yukon (https://open.yukon.ca/open-government-licence-yukon). "
    "Attribution: 'Contains information licensed under the Open Government Licence - Yukon.'"
)

OGL_NL = (
    "Open Government Licence - Newfoundland and Labrador 1.0 "
    "(https://opendata.gov.nl.ca/public/opendata/page/?page-id=licence). Attribution: 'Contains "
    "information licensed under the Open Government Licence - Newfoundland and Labrador.'"
)

BOC_TERMS = (
    "Bank of Canada Terms of Use (https://www.bankofcanada.ca/terms/): attribute the Bank of "
    "Canada as the source and indicate if changes were made, without implying the Bank endorses "
    "the use; content passed on through paid services must be identified as obtained from the "
    "Bank's website."
)

ECCC_LICENCE = (
    "Environment and Climate Change Canada Data Servers End-use Licence "
    "(https://eccc-msc.github.io/open-data/licence/readme_en/). "
    "Attribution: 'Data Source: Environment and Climate Change Canada.'"
)

# Federal web pages that are not published on open.canada.ca fall under the
# Canada.ca terms, which are narrower than the Open Government Licence.
CANADA_CA_TERMS = (
    "Government of Canada website terms (https://www.canada.ca/en/transparency/terms.html): "
    "non-commercial reproduction is allowed without permission, with the title, author and "
    "source URL cited; commercial redistribution needs written permission."
)

CIHI_TERMS = (
    "CIHI Terms of Use (https://www.cihi.ca/en/terms-of-use): free use for education, "
    "non-commercial research, internal reference and private study, crediting CIHI as the "
    "source; commercial use needs CIHI's written authorization."
)

CMHC_TERMS = (
    "CMHC Terms and Conditions (https://www.cmhc-schl.gc.ca/about-us/terms-conditions): content "
    "may be copied, downloaded and printed for personal use; redistribution or republication "
    "needs CMHC's written consent. Credit Canada Mortgage and Housing Corporation (CMHC)."
)

HOUSE_OF_COMMONS_TERMS = (
    "House of Commons Speaker's permission (https://www.ourcommons.ca/en/important-notices): "
    "reproduction of proceedings is permitted if accurate and not presented as official; it "
    "does not extend to commercial use or financial gain."
)

SENATE_TERMS = (
    "Senate of Canada intellectual property terms (https://sencanada.ca/en/intellectual-property/): "
    "reproduction of proceedings is permitted if accurate and not for financial gain; identify "
    "the Senate as author with the title and source URL."
)

ELECTIONS_CANADA_TERMS = (
    "Elections Canada terms (https://www.elections.ca/content.aspx?section=pri&document=index&lang=e): "
    "non-commercial reproduction is allowed, citing the title, author and source URL; "
    "commercial redistribution needs written permission."
)

PBO_TERMS = (
    "Parliamentary Budget Officer terms (https://www.pbo-dpb.ca): PBO materials may be used and "
    "reproduced for personal and non-commercial use without permission, unaltered and with "
    "attribution to the PBO."
)

IESO_TERMS = (
    "IESO Terms of Use (https://www.ieso.ca/en/Terms-of-Use): limited licence to use and "
    "reproduce provided every reproduction carries the notice 'Copyright 2004-2022 Independent "
    "Electricity System Operator, all rights reserved. This information is subject to the Terms "
    "of Use set out in the IESO's website (www.ieso.ca).'"
)

# statistique.quebec.ca links its reuse terms to the Québec government's
# copyright page, which requires prior authorization (no open licence).
ISQ_LICENCE = (
    "Gouvernement du Québec copyright (https://www.quebec.ca/en/copyright): reproduction, "
    "adaptation or publication needs prior authorization from the Québec government. Credit: "
    "'Source: Institut de la statistique du Québec.'"
)

EDMONTON_TERMS = (
    "City of Edmonton Open Data Terms of Use "
    "(https://data.edmonton.ca/stories/s/City-of-Edmonton-Open-Data-Terms-of-Use/msh8-if28/). "
    "Credit: City of Edmonton."
)

REPRESENT_TERMS = (
    "Open North's Represent API (https://represent.opennorth.ca) states no licence of its own. "
    "Boundary sets carry their publisher's licence (licence_url on each set); representative "
    "records are gathered from official sites and their reuse terms are not stated."
)

TERMS_NOT_STATED = (
    "Terms not stated by the publisher: no licence or terms of use were found for this data. "
    "Do not assume it is openly licensed; check with the publisher before redistributing."
)

PER_RECORD_LICENCE = (
    "Licences differ by dataset on this platform: each dataset's own licence is in its "
    "licence fields. Check it before reusing."
)


def terms_not_stated(publisher: str, url: str) -> str:
    """`TERMS_NOT_STATED` naming the publisher and the page that was checked."""
    return (
        f"Terms not stated by the publisher ({publisher}): no licence or terms of use were found "
        f"at {url}. Do not assume it is openly licensed; check with the publisher before "
        "redistributing."
    )


def derived_from_statcan(own_licence: str) -> str:
    """Licence text for a file an agency builds from Statistics Canada data.

    Both apply: the agency's own terms for its compilation, and the
    Statistics Canada Open Licence (with its attribution) for the
    underlying data.
    """
    return f"{own_licence} Underlying data from Statistics Canada: {STATCAN_LICENCE}"


NL_STATS_TERMS = derived_from_statcan(
    "Government of Newfoundland and Labrador website terms (https://www.gov.nl.ca/disclaimer/): "
    "the public may use the information on its sites. Credit: Newfoundland and Labrador "
    "Statistics Agency."
)

AB_ECONOMIC_TERMS = (
    f"{OGL_ALBERTA} Indicators the dashboard builds from Statistics Canada tables (the source "
    f"field names the table) also fall under: {STATCAN_LICENCE}"
)


# Source name (exactly as passed to make_provenance) -> licence. A module
# whose source name is not here, and whose URL is not a StatCan one, gets
# no licence text: tests/test_shared_licences.py fails for that case, so a
# new module has to add its entry.
SOURCE_LICENCES: dict[str, str] = {
    # Alberta
    "ab-economic": AB_ECONOMIC_TERMS,
    "ab-opendata": OGL_ALBERTA,
    "open-alberta": OGL_ALBERTA,
    "ab_wildfire": OGL_ALBERTA + " Credit: Alberta Wildfire, Government of Alberta.",
    "aer": (
        "Alberta Energy Regulator copyright terms (https://www.aer.ca/copyright-disclaimer): "
        "non-commercial reproduction is allowed without permission, identifying the AER as "
        "the source and not presenting it as official; commercial redistribution needs the "
        "AER's written permission."
    ),
    "epcor": terms_not_stated("EPCOR", "https://apps.epcor.ca"),
    "eps": terms_not_stated(
        "Edmonton Police Service", "https://communitysafetydataportal.edmontonpolice.ca"
    ),
    "ets": EDMONTON_TERMS,
    "provincial-election-results": (
        "Terms differ by election agency; see the per-province licence notes in limits."
    ),
    "elections-provincial": (
        "Terms differ by election agency; see the per-province licence notes in limits."
    ),
    # British Columbia, Yukon, Newfoundland and Labrador
    "bc_lobbyists": (
        "Open Data Licence for the Office of the Registrar of Lobbyists for British Columbia "
        "(https://www.lobbyistsregistrar.bc.ca/media/1285/open-data-licence-for-the-office-of-"
        "the-registrar-of-lobbyists-for-british-columbia.pdf). Attribution: 'Contains "
        "information licensed under the Open Data Licence for the Office of the Registrar of "
        "Lobbyists for British Columbia.' The licence grants no rights to personal information."
    ),
    "bc-stats": PER_RECORD_LICENCE,
    "bc-stats-files": PER_RECORD_LICENCE,
    "bcgw": OGL_BC
    + " Some BC Geographic Warehouse layers carry other terms; check the layer's record.",
    "drivebc": OGL_BC + " The Open511 API is also under the BC Government API Terms of Use.",
    "yukon-stats": OGL_YUKON,
    "yukon-bureau-of-statistics": OGL_YUKON,
    "nl-opendata": OGL_NL,
    "nl-stats": NL_STATS_TERMS,
    "nl-statistics-agency": NL_STATS_TERMS,
    "bc-environment": f"{OGL_BC} Source: BC Ministry of Environment and Parks.",
    "nwt-bureau-of-statistics": (
        "Open Government Licence - Northwest Territories, as the territory's open data "
        "catalogue lists for these files; the general terms of use linked from statsnwt.ca "
        "ask for permission before commercial use. Check which applies to your use."
    ),
    # Ontario
    "oeb": (
        "Source: Ontario Energy Board open data (https://www.oeb.ca/ontarios-energy-sector/"
        "open-data). Contains information licensed under the Open Government Licence - Ontario."
    ),
    "crea": (
        "Source: The Canadian Real Estate Association (CREA), MLS Home Price Index. CREA's "
        "terms (https://www.crea.ca/legal/) apply; this is not an open licence."
    ),
    # International
    "worldbank-wdi": (
        "Source: World Bank, World Development Indicators. Creative Commons Attribution 4.0 "
        "(https://datacatalog.worldbank.org/public-licenses)."
    ),
    # Quebec
    "isq": ISQ_LICENCE,
    # Federal: open.canada.ca and departmental open-data services (OGL - Canada)
    "cdc": OGL_CANADA,
    "cer": OGL_CANADA,
    "cgc": OGL_CANADA,
    "cgc-grain-statistics-weekly": OGL_CANADA,
    "cgc-exports-licensed-facilities": OGL_CANADA,
    "cwfis": OGL_CANADA,
    "cwfis-sitrep": OGL_CANADA,
    "earthquakes-canada": OGL_CANADA,
    "gc-infobase": OGL_CANADA,
    "ircc-monthly": OGL_CANADA,
    "ised-corporations": OGL_CANADA,
    "ised-spectrum": OGL_CANADA,
    "ised-ip-horizons": OGL_CANADA,
    "ised-clean-growth": OGL_CANADA,
    "national-forestry-database": OGL_CANADA,
    "nfd": OGL_CANADA,
    "nrcan-geo": OGL_CANADA,
    "nrcan-nbac": OGL_CANADA,
    "phac-infobase": OGL_CANADA,
    "recalls": OGL_CANADA,
    "tc-recalls": OGL_CANADA,
    # Federal web pages and services outside open.canada.ca
    "competition-bureau": CANADA_CA_TERMS,
    "cra_digital_economy_registry": CANADA_CA_TERMS,
    "cfia": CANADA_CA_TERMS,
    "fcac": CANADA_CA_TERMS,
    "gazette": CANADA_CA_TERMS,
    "ircc-express-entry": CANADA_CA_TERMS,
    "ised-cipo": CANADA_CA_TERMS,
    "nrcan-energy-use": CANADA_CA_TERMS,
    "pmprb": CANADA_CA_TERMS,
    "health_products": OGL_CANADA,
    "finance_canada": CANADA_CA_TERMS,
    "nrcan_minerals": CANADA_CA_TERMS,
    "dfo-iwls": terms_not_stated(
        "Fisheries and Oceans Canada, Canadian Hydrographic Service",
        "https://api-iwls.dfo-mpo.gc.ca",
    ),
    # Federal agencies with their own terms
    "boc": BOC_TERMS,
    "valet": BOC_TERMS,
    "cihi": CIHI_TERMS,
    "cmhc": CMHC_TERMS,
    "cmhc-dt": CMHC_TERMS,
    "eccc": ECCC_LICENCE,
    "eccc-data-catalogue": OGL_CANADA,
    "pbo": PBO_TERMS,
    "electricity": "Terms differ by operator; see the operator's terms in this result.",
    # Parliament and elections
    "ourcommons": HOUSE_OF_COMMONS_TERMS,
    "house-of-commons-open-data": HOUSE_OF_COMMONS_TERMS,
    "senate": SENATE_TERMS,
    "represent": REPRESENT_TERMS,
    "elections_financial_returns": ELECTIONS_CANADA_TERMS,
    "elections-results": ELECTIONS_CANADA_TERMS,
    "elections-canada-official-voting-results": OGL_CANADA,
    "harvard-dataverse-who-runs-federal-candidates": (
        "Harvard Dataverse dataset terms: see the dataset page for its licence "
        "(Dataverse defaults to CC0 1.0 unless the depositor sets other terms)."
    ),
    "borealis-winer-ferris-federal-elections": (
        "Borealis dataset terms: see the dataset page for its licence and terms of use."
    ),
    # Catalogue families and repositories: terms are per dataset or per feed
    "borealis": PER_RECORD_LICENCE,
    "ckan": PER_RECORD_LICENCE,
    "arcgis-hub": PER_RECORD_LICENCE,
    "socrata": PER_RECORD_LICENCE,
    "opendatasoft-vancouver": PER_RECORD_LICENCE,
    "transit": (
        "Each transit feed carries its agency's own licence and attribution (licence and "
        "attribution fields on each agency)."
    ),
    "transit:statcan": derived_from_statcan(
        "Canadian Public Transit Network Database compilation; each feed also carries its "
        "agency's own terms (licence_url, attribution)."
    ),
}


# French text for a licence, keyed by its English text, so a call made with
# lang="fr" reads its terms in French whichever source carries them. Names and
# URLs are the publishers' own French ones, checked on 2026-10-04; a licence
# not listed here stays in English. The IESO notice is quoted in English
# because the IESO requires that exact wording on every reproduction.
LICENCES_FR: dict[str, str] = {
    OGL_CANADA: (
        "Licence du gouvernement ouvert – Canada 2.0 "
        "(https://ouvert.canada.ca/fr/licence-du-gouvernement-ouvert-canada). Attribution : "
        "« Contient des informations visées par la Licence du gouvernement ouvert – Canada. »"
    ),
    CANADA_CA_TERMS: (
        "Avis du site Web du gouvernement du Canada (https://www.canada.ca/fr/transparence/"
        "avis.html) : la reproduction non commerciale est permise sans autorisation, en citant "
        "le titre, l'auteur et l'adresse URL de la source ; la redistribution commerciale exige "
        "une autorisation écrite."
    ),
    BOC_TERMS: (
        "Conditions d'utilisation de la Banque du Canada "
        "(https://www.banqueducanada.ca/conditions-utilisation-avis/) : indiquer la Banque du "
        "Canada comme source et signaler toute modification, sans laisser entendre que la "
        "Banque approuve l'utilisation ; le contenu transmis par un service payant doit être "
        "présenté comme provenant du site Web de la Banque."
    ),
    ECCC_LICENCE: (
        "Licence d'utilisation finale des serveurs de données d'Environnement et Changement "
        "climatique Canada (https://eccc-msc.github.io/open-data/licence/readme_fr/). "
        "Attribution : « Source des données : Environnement et Changement climatique Canada. »"
    ),
    CMHC_TERMS: (
        "Conditions d'utilisation de la SCHL "
        "(https://www.cmhc-schl.gc.ca/info-schl/conditions-dutilisation) : le contenu peut être "
        "copié, téléchargé et imprimé pour un usage personnel ; la redistribution ou la "
        "republication exige le consentement écrit de la SCHL. Mentionner la Société "
        "canadienne d'hypothèques et de logement (SCHL)."
    ),
    PBO_TERMS: (
        "Conditions du directeur parlementaire du budget (https://www.pbo-dpb.ca/fr) : les "
        "documents du DPB peuvent être utilisés et reproduits à des fins personnelles et non "
        "commerciales sans autorisation, sans modification et en mentionnant le DPB."
    ),
    IESO_TERMS: (
        "Conditions d'utilisation de la Société indépendante d'exploitation du réseau "
        "d'électricité (SIERE) (https://www.ieso.ca/en/Terms-of-Use) : licence limitée "
        "d'utilisation et de reproduction, à condition que chaque reproduction porte l'avis "
        "suivant, en anglais : 'Copyright 2004-2022 Independent Electricity System Operator, "
        "all rights reserved. This information is subject to the Terms of Use set out in the "
        "IESO's website (www.ieso.ca).'"
    ),
    PER_RECORD_LICENCE: (
        "Les licences diffèrent d'un jeu de données à l'autre sur cette plateforme : la licence "
        "de chaque jeu de données figure dans ses champs de licence. Vérifiez-la avant toute "
        "réutilisation."
    ),
    SOURCE_LICENCES["aer"]: (
        "Conditions de droit d'auteur de l'Alberta Energy Regulator "
        "(https://www.aer.ca/copyright-disclaimer) : la reproduction non commerciale est "
        "permise sans autorisation, en indiquant l'AER comme source et sans la présenter comme "
        "officielle ; la redistribution commerciale exige l'autorisation écrite de l'AER."
    ),
    SOURCE_LICENCES["crea"]: (
        "Source : Association canadienne de l'immeuble (ACI), Indice des prix des propriétés "
        "MLS®. Les conditions de l'ACI (https://www.crea.ca/fr/renseignements-juridiques/) "
        "s'appliquent ; il ne s'agit pas d'une licence ouverte."
    ),
    SOURCE_LICENCES["worldbank-wdi"]: (
        "Source : Banque mondiale, Indicateurs du développement dans le monde. Licence Creative "
        "Commons Attribution 4.0 (https://datacatalog.worldbank.org/public-licenses)."
    ),
    SOURCE_LICENCES["electricity"]: (
        "Les conditions diffèrent selon l'exploitant ; voir les conditions de l'exploitant dans "
        "ce résultat."
    ),
    SOURCE_LICENCES["ab_wildfire"]: (
        "Licence du gouvernement ouvert – Alberta (https://open.alberta.ca/licence). "
        "Attribution : « Contient des informations visées par la Licence du gouvernement "
        "ouvert – Alberta. » Mention : Alberta Wildfire, gouvernement de l'Alberta."
    ),
    CIHI_TERMS: (
        "Conditions d'utilisation de l'ICIS (https://www.cihi.ca/fr/conditions-dutilisation) : "
        "utilisation gratuite à des fins d'éducation, de recherche non commerciale, de "
        "consultation interne et d'étude personnelle, en citant l'ICIS comme source ; "
        "l'utilisation commerciale exige l'autorisation écrite de l'ICIS."
    ),
    HOUSE_OF_COMMONS_TERMS: (
        "Autorisation du Président de la Chambre des communes "
        "(https://www.noscommunes.ca/fr/avis-importants) : la reproduction des délibérations "
        "est permise si elle est exacte et n'est pas présentée comme une version officielle ; "
        "elle ne s'étend pas à l'usage commercial ni à un gain financier."
    ),
    SENATE_TERMS: (
        "Propriété intellectuelle du Sénat du Canada "
        "(https://sencanada.ca/fr/propriete-intellectuelle/) : la reproduction des "
        "délibérations est permise si elle est exacte et sans but lucratif ; indiquer le Sénat "
        "comme auteur, avec le titre et l'adresse URL de la source."
    ),
    ELECTIONS_CANADA_TERMS: (
        "Avis d'Élections Canada "
        "(https://www.elections.ca/content.aspx?section=pri&document=index&lang=f) : la "
        "reproduction non commerciale est permise en citant le titre, l'auteur et l'adresse URL "
        "de la source ; la redistribution commerciale exige une autorisation écrite."
    ),
    REPRESENT_TERMS: (
        "L'API Represent d'Open North (https://represent.opennorth.ca) n'énonce aucune licence "
        "propre. Les ensembles de limites relèvent de la licence de leur éditeur (licence_url de "
        "chaque ensemble) ; les fiches des élus proviennent de sites officiels et leurs "
        "conditions de réutilisation ne sont pas précisées."
    ),
    SOURCE_LICENCES["elections-provincial"]: (
        "Les conditions varient selon l'organisme électoral ; voir les notes de licence par "
        "province dans limits."
    ),
    SOURCE_LICENCES["dfo-iwls"]: (
        "Conditions non précisées par l'éditeur (Pêches et Océans Canada, Service hydrographique "
        "du Canada) : aucune licence ni condition d'utilisation n'a été trouvée à "
        "https://api-iwls.dfo-mpo.gc.ca. Ne présumez pas une licence ouverte ; vérifiez auprès "
        "de l'éditeur avant toute redistribution."
    ),
    SOURCE_LICENCES["harvard-dataverse-who-runs-federal-candidates"]: (
        "Conditions du jeu de données Harvard Dataverse : voir la page du jeu de données pour sa "
        "licence (Dataverse applique CC0 1.0 par défaut, sauf si le déposant fixe d'autres "
        "conditions)."
    ),
    SOURCE_LICENCES["borealis-winer-ferris-federal-elections"]: (
        "Conditions du jeu de données Borealis : voir la page du jeu de données pour sa licence "
        "et ses conditions d'utilisation."
    ),
}


def licence_in(text: str, lang: str = "en") -> str:
    """`text` in French when lang is "fr" and a translation exists, else as given."""
    if lang.strip().lower().startswith("fr"):
        return LICENCES_FR.get(text, text)
    return text


# Platform families name their source after the portal ("ckan-on",
# "arcgis-halifax", "socrata-calgary") or the feed ("transit:stm").
_FAMILY_PREFIXES = ("arcgis-", "ckan-", "socrata-")


def licence_for(source: str, url: str) -> str | None:
    """The licence text for a source name, falling back on a StatCan URL check."""
    known = SOURCE_LICENCES.get(source)
    if known is not None:
        return known
    if source.startswith(_FAMILY_PREFIXES):
        return PER_RECORD_LICENCE
    if ":" in source and source.split(":", 1)[0] in SOURCE_LICENCES:
        return SOURCE_LICENCES[source.split(":", 1)[0]]
    if source.lower().startswith("statcan") or "statcan.gc.ca" in url.lower():
        return STATCAN_LICENCE
    return None
