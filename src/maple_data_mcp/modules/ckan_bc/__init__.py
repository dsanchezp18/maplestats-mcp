"""BC Data Catalogue (catalogue.data.gov.bc.ca), CKAN Action API 3.

Covers catalogue search, dataset detail, organizations, resources,
licenses, tags, and groups via the standard `/api/3/action/...`
endpoints. Confirmed live this session against ~3,357 datasets (the
catalogue's actual `package_search` count with no filter, checked
directly rather than assumed) -- see client.py for field-level quirks
that differ from both generic CKAN documentation and from
modules/ckan_federal's own deployment-specific findings. Do not assume
this portal matches ckan_federal beyond the shared HTTP/envelope layer
in shared/ckan.py; several things genuinely differ (see client.py):

- Unlike ckan_federal, this portal DOES use CKAN tags (~7,087, confirmed
  live via tag_list) and groups (26 curated thematic collections,
  confirmed live via group_list) -- ckan_bc_list_tags/ckan_bc_list_groups/
  ckan_bc_get_group exist here specifically because federal's reason for
  omitting them (empty tag_list/group_list) does not hold on this portal.
- Unlike ckan_federal, this portal is English-only -- no `_translated`
  dict or `_fra`-suffixed field was found on any sampled package,
  resource, organization, or license record. `lang` is still accepted
  on every tool per this repo's convention, but has no effect here.
"""

MODULE_NAME = "ckan_bc"
MODULE_DESCRIPTION = (
    "BC Data Catalogue (catalogue.data.gov.bc.ca): full-text dataset "
    "search, dataset detail with resources, publishing organizations, "
    "individual resource metadata, licenses, tags, and groups, via the "
    "standard CKAN Action API. Covers the British Columbia provincial "
    "open-data catalogue (~3,357 datasets). English-only; all tools "
    "accept lang for interface consistency but it has no effect."
)
MODULE_DESCRIPTION_FR = (
    "Catalogue de données de la Colombie-Britannique "
    "(catalogue.data.gov.bc.ca) : recherche de jeux de données en "
    "texte intégral, détail des jeux de données avec "
    "ressources, organisations responsables, métadonnées des "
    "ressources individuelles, licences, mots-clés et groupes, via "
    "l'API Action CKAN standard. Couvre le catalogue provincial de "
    "données ouvertes de la Colombie-Britannique (~3 357 jeux de "
    "données). Uniquement en anglais; tous les outils acceptent "
    "lang par souci de cohérence, mais cela n'a aucun effet."
)
