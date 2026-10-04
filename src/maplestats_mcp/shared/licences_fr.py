"""French text for the licences in shared/licences.py, for a call made with lang="fr".

`licence_for_lang(source, url, lang)` gives the same terms as
`licence_for(source, url)`, in French when `lang` is French and a French
text exists here; otherwise the English text. A module passes the result
as `licence=` to make_provenance. The French names and links are the
publishers' own French pages (Licence du gouvernement ouvert – Canada:
ouvert.canada.ca; Canada.ca terms: canada.ca/fr/transparence/avis.html).
"""

from __future__ import annotations

from maplestats_mcp.shared import licences
from maplestats_mcp.shared.fr_typography import french_spacing
from maplestats_mcp.shared.i18n import normalize_lang

OGL_CANADA_FR = (
    "Licence du gouvernement ouvert – Canada 2.0 "
    "(https://ouvert.canada.ca/fr/licence-du-gouvernement-ouvert-canada). Attribution : "
    "« Contient des informations visées par la Licence du gouvernement ouvert – Canada. »"
)

OGL_ALBERTA_FR = (
    "Licence du gouvernement ouvert – Alberta (https://open.alberta.ca/licence). Attribution : "
    "« Contient des informations visées par la Licence du gouvernement ouvert – Alberta. »"
)

CANADA_CA_TERMS_FR = (
    "Avis du gouvernement du Canada (https://www.canada.ca/fr/transparence/avis.html) : la "
    "reproduction non commerciale est permise sans autorisation, en citant le titre, l'auteur "
    "et l'adresse URL de la source ; la redistribution commerciale exige une autorisation écrite."
)

CIHI_TERMS_FR = (
    "Conditions d'utilisation de l'ICIS (https://www.cihi.ca/fr/conditions-dutilisation) : "
    "utilisation gratuite à des fins d'éducation, de recherche non commerciale, de consultation "
    "interne et d'étude personnelle, en citant l'ICIS comme source ; l'utilisation commerciale "
    "exige l'autorisation écrite de l'ICIS."
)

HOUSE_OF_COMMONS_TERMS_FR = (
    "Autorisation du Président de la Chambre des communes "
    "(https://www.noscommunes.ca/fr/avis-importants) : la reproduction des délibérations est "
    "permise si elle est exacte et n'est pas présentée comme une version officielle ; elle ne "
    "s'étend pas à l'usage commercial ni à un gain financier."
)

SENATE_TERMS_FR = (
    "Propriété intellectuelle du Sénat du Canada (https://sencanada.ca/fr/propriete-intellectuelle/) "
    ": la reproduction des délibérations est permise si elle est exacte et sans but lucratif ; "
    "indiquer le Sénat comme auteur, avec le titre et l'adresse URL de la source."
)

ELECTIONS_CANADA_TERMS_FR = (
    "Avis d'Élections Canada (https://www.elections.ca/content.aspx?section=pri&document=index&lang=f) "
    ": la reproduction non commerciale est permise en citant le titre, l'auteur et l'adresse URL "
    "de la source ; la redistribution commerciale exige une autorisation écrite."
)

REPRESENT_TERMS_FR = (
    "L'API Represent d'Open North (https://represent.opennorth.ca) n'énonce aucune licence "
    "propre. Les ensembles de limites relèvent de la licence de leur éditeur (licence_url de "
    "chaque ensemble) ; les fiches des élus proviennent de sites officiels et leurs conditions "
    "de réutilisation ne sont pas précisées."
)

PER_RECORD_LICENCE_FR = (
    "Les licences varient d'un jeu de données à l'autre sur cette plateforme : la licence de "
    "chaque jeu figure dans ses champs de licence. Vérifiez-la avant toute réutilisation."
)

PROVINCIAL_ELECTIONS_FR = (
    "Les conditions varient selon l'organisme électoral ; voir les notes de licence par "
    "province dans limits."
)


def terms_not_stated_fr(publisher: str, url: str) -> str:
    """French `licences.terms_not_stated`."""
    return (
        f"Conditions non précisées par l'éditeur ({publisher}) : aucune licence ni condition "
        f"d'utilisation n'a été trouvée à {url}. Ne présumez pas une licence ouverte ; "
        "vérifiez auprès de l'éditeur avant toute redistribution."
    )


# English text (as licences.SOURCE_LICENCES holds it) -> French text.
_FRENCH: dict[str, str] = {
    licences.OGL_CANADA: OGL_CANADA_FR,
    licences.SOURCE_LICENCES["ab_wildfire"]: (
        OGL_ALBERTA_FR + " Mention : Alberta Wildfire, gouvernement de l'Alberta."
    ),
    licences.CANADA_CA_TERMS: CANADA_CA_TERMS_FR,
    licences.CIHI_TERMS: CIHI_TERMS_FR,
    licences.HOUSE_OF_COMMONS_TERMS: HOUSE_OF_COMMONS_TERMS_FR,
    licences.SENATE_TERMS: SENATE_TERMS_FR,
    licences.ELECTIONS_CANADA_TERMS: ELECTIONS_CANADA_TERMS_FR,
    licences.REPRESENT_TERMS: REPRESENT_TERMS_FR,
    licences.PER_RECORD_LICENCE: PER_RECORD_LICENCE_FR,
    licences.SOURCE_LICENCES["elections-provincial"]: PROVINCIAL_ELECTIONS_FR,
    licences.SOURCE_LICENCES["dfo-iwls"]: terms_not_stated_fr(
        "Pêches et Océans Canada, Service hydrographique du Canada",
        "https://api-iwls.dfo-mpo.gc.ca",
    ),
    licences.SOURCE_LICENCES["harvard-dataverse-who-runs-federal-candidates"]: (
        "Conditions du jeu de données Harvard Dataverse : voir la page du jeu pour sa licence "
        "(Dataverse applique CC0 1.0 par défaut, sauf si le déposant fixe d'autres conditions)."
    ),
    licences.SOURCE_LICENCES["borealis-winer-ferris-federal-elections"]: (
        "Conditions du jeu de données Borealis : voir la page du jeu pour sa licence et ses "
        "conditions d'utilisation."
    ),
}


def licence_for_lang(source: str, url: str, lang: str = "en") -> str | None:
    """`licences.licence_for(source, url)`, in French for lang="fr" when a translation exists."""
    english = licences.licence_for(source, url)
    if english is None or normalize_lang(lang) != "fr":
        return english
    french = _FRENCH.get(english)
    return french_spacing(french) if french else english


def to_french(english: str | None, lang: str = "en") -> str | None:
    """The French text for one English licence constant, for a module that passes its own."""
    if english is None or normalize_lang(lang) != "fr":
        return english
    french = _FRENCH.get(english)
    return french_spacing(french) if french else english
