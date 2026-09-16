"""Quebec Open Data portal (donneesquebec.ca), CKAN Action API 3.

Covers catalogue search, dataset detail, organizations, resources,
licenses, groups, and tags via the `/recherche/api/3/action/...`
endpoints. Confirmed live this session against ~1,610 datasets (the
catalogue's actual `package_search` count with no filter, checked
directly) -- see client.py for field-level quirks that differ from
both generic CKAN documentation and the federal ckan_federal module.

Two findings shape this module and set it apart from ckan_federal:

1. This portal is effectively French-monolingual. Confirmed live: no
   sampled package/organization/resource record carries a
   `<field>_translated` dict or an `_fra`-suffixed field anywhere --
   `title`/`notes`/etc. are flat strings with no bilingual-extension
   infrastructure at all. A `language` facet check found only two
   values across all 1,610 datasets, "FR" (1,601) and "FR_EN" (9); the
   "FR_EN" tag is descriptive metadata about a dataset's own content,
   not a signal that a second set of translated fields exists for it.
   Every tool here still accepts `lang` for interface consistency with
   every other CKAN module in this codebase, but `lang="en"` is a
   documented no-op -- it returns the same French content `lang="fr"`
   would, per client.py's docstring.
2. Unlike the federal portal (which uses neither), this portal makes
   real use of both CKAN tags (4,402 live, free-text and uncontrolled --
   confirmed via `tag_list`) and CKAN groups (12 live, a small, stable,
   curated set of thematic categories -- confirmed via
   `group_list(all_fields=true)`). `ckan_qc_list_tags` and
   `ckan_qc_list_groups` exist here as a direct result of that
   confirmed live data, unlike ckan_federal where both were omitted for
   the opposite reason.
"""

MODULE_NAME = "ckan_qc"
MODULE_DESCRIPTION = (
    "Quebec Open Data portal (donneesquebec.ca): full-text dataset "
    "search, dataset detail with resources, publishing organizations, "
    "individual resource metadata, licenses, thematic groups, and "
    "free-text tags, via the standard CKAN Action API. Covers the "
    "Quebec provincial open-data catalogue (~1,600 datasets). This "
    "portal is effectively French-only -- lang is accepted on every "
    "tool for interface consistency but lang='en' is a documented "
    "no-op (see client.py)."
)
MODULE_DESCRIPTION_FR = (
    "Portail de données ouvertes du Québec (donneesquebec.ca) : "
    "recherche de jeux de données en texte intégral, détail des "
    "jeux de données avec ressources, organisations responsables, "
    "métadonnées des ressources individuelles, licences, groupes "
    "thématiques et mots-clés libres, via l'API Action CKAN standard. "
    "Couvre le catalogue provincial québécois de données ouvertes "
    "(~1 600 jeux de données)."
)
