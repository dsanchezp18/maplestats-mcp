"""Indigenous Services Canada and CIRNAC: First Nation profiles and drinking water advisories.

Three publications, checked live 2026-10-26 (see client.py):

- First Nation Profiles (fnp-ppn.aadnc-aandc.gc.ca), CIRNAC's server-rendered
  pages per band number: official name, address, tribal council, reserves,
  governance, geography and the monthly registered population.
- ISC's open.canada.ca dataset "Population Registered under the Indian Act by
  Gender and Residence: Data Series from 2023" (OGL - Canada), one CSV with
  every registry group by year; it is the list the search reads.
- ISC's drinking water advisory pages on sac-isc.gc.ca: the JSON file behind
  the long-term advisory map (current and lifted) and the HTML tables of
  short-term advisories south of 60.
"""

MODULE_NAME = "isc"
MODULE_DESCRIPTION = (
    "Indigenous Services Canada and Crown-Indigenous Relations and Northern Affairs Canada, "
    "tools prefixed isc_: find a First Nation by name, number or province (646 registry "
    "groups, with registered population under the Indian Act by year); a First Nation's "
    "profile (official name, address, tribal council, reserves with hectares, governance "
    "with chief and council and election system, geographic zone); registered population "
    "by sex and residence, monthly from the First Nation Profiles and yearly from 2023; "
    "long-term drinking water advisories on public systems, current and lifted since 2015, "
    "with corrective measures and project phase; and short-term advisories south of 60, "
    "excluding British Columbia. English and French."
)
MODULE_DESCRIPTION_FR = (
    "Services aux Autochtones Canada et Relations Couronne-Autochtones et Affaires du Nord "
    "Canada, outils préfixés isc_ : trouver une Première Nation par nom, numéro ou province "
    "(646 groupes du registre, avec la population inscrite en vertu de la Loi sur les "
    "Indiens par année) ; le profil d'une Première Nation (nom officiel, adresse, conseil "
    "tribal, réserves et superficie en hectares, administration avec chef et conseil et "
    "système électoral, zone géographique) ; la population inscrite par sexe et lieu de "
    "résidence, mensuelle d'après les Profils des Premières Nations et annuelle depuis "
    "2023 ; les avis à long terme concernant la qualité de l'eau potable des réseaux "
    "publics, en vigueur et levés depuis 2015, avec les mesures correctives et l'étape du "
    "projet ; et les avis à court terme au sud du 60e parallèle, sauf en "
    "Colombie-Britannique. En français et en anglais."
)
