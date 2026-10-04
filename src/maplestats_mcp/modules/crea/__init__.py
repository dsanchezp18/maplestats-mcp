"""The Canadian Real Estate Association (CREA): MLS® Home Price Index links.

CREA's statistics are not openly licensed. Its Terms of Use
(https://www.crea.ca/legal/) allow downloading the content for private,
non-commercial analysis, but forbid publishing or displaying it, in whole
or in part, without CREA's prior written consent, require CREA to be
attributed as the source in any display, and forbid commercial use. So
this module returns no CREA values and reads no CREA file: it returns
the links, the release timing, the attribution line, a summary of the
terms, and open measures to use instead.

Checked live 2026-10-03: the monthly zip sits at
https://www.crea.ca/files/mls-hpi-data/MLS_HPI_<Month>_<YYYY>.zip, named
for the release month (MLS_HPI_Sept_2026.zip, Last-Modified 14 Sep 2026,
was the file on the HPI tool page on 3 Oct). The month spelling varies
from file to file: Aug and Sept in 2026, January to May spelled in full,
June and July 2026 under neither spelling. The client tries the short
spelling, then the full one, with HEAD requests only, and falls back to
the HPI tool page when neither answers.
"""

MODULE_NAME = "crea"
MODULE_DESCRIPTION = (
    "The Canadian Real Estate Association (CREA), tools prefixed crea_: links only for "
    "the MLS® Home Price Index (the current monthly zip, confirmed by a HEAD request, "
    "and the HPI tool page), CREA's national statistics, quarterly forecasts and housing "
    "market snapshot pages, the release timing (monthly, around the 15th), the required "
    "attribution and a summary of CREA's terms. No CREA values are returned: the terms "
    "allow private, non-commercial analysis only, and publishing or displaying the "
    "content needs CREA's written consent. Open alternatives (different measures): "
    "StatCan New Housing Price Index and CHSP sale prices (wds_), CMHC starts (cmhc_)."
)
MODULE_DESCRIPTION_FR = (
    "L'Association canadienne de l'immeuble (ACI), outils préfixés crea_ : liens "
    "seulement pour l'Indice des prix des propriétés MLS® (le fichier zip mensuel en "
    "cours, vérifié par une requête HEAD, et la page de l'outil IPP), les pages des "
    "statistiques nationales, des prévisions trimestrielles et de l'aperçu du marché, le "
    "calendrier de diffusion (mensuel, vers le 15), la mention de source exigée et un "
    "résumé des conditions de l'ACI. Aucune valeur de l'ACI n'est renvoyée : les "
    "conditions permettent une analyse privée et non commerciale seulement, et toute "
    "publication ou présentation exige le consentement écrit de l'ACI. Solutions "
    "ouvertes (mesures différentes) : Indice des prix des logements neufs et prix de "
    "vente du PSLC de StatCan (wds_), mises en chantier de la SCHL (cmhc_)."
)
