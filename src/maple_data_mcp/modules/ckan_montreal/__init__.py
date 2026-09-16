"""City of Montreal open-data portal (donnees.montreal.ca), CKAN Action API 3.

Covers catalogue search, dataset detail, organizations, resources, tags,
groups, and licenses via the standard `/api/3/action/...` endpoints.
Confirmed live this session against a `package_list` count of 447 and a
`package_search` (empty query) `count` of 404 -- the two disagree because
`package_list` includes non-public/harvest-type entries `package_search`
excludes, checked directly rather than assumed equal the way a single
"~N datasets" figure might suggest.

This deployment differs from ckan_federal in ways that matter for how
this module is built, all verified live rather than assumed shared
(see client.py for the specifics and how each was checked):

1. It is effectively French-only. Every sampled package (50 of 404, plus
   an explicit `fq=language:EN` count of 0 against `fq=language:FR`'s 403)
   carries a flat `language: "FR"` field and NO `_translated` dict on any
   field, unlike ckan_federal's bilingual `title_translated`/
   `notes_translated`. `lang="en"` is accepted by every tool for interface
   consistency but is a documented no-op on the data itself.
2. Unlike the federal portal (which uses neither), this portal genuinely
   uses CKAN tags (1,174 distinct tag names live) and groups (12 live,
   each with real French descriptions and non-trivial `package_count`).
   ckan_montreal_list_tags/ckan_montreal_list_groups tools exist here
   because of that, matching ckan_federal's explicit choice not to define
   them.
3. `package_search`'s error behavior differs from federal's: an unknown
   `sort` field is silently ignored (HTTP 200, default sort applied)
   rather than rejected, and a syntactically malformed `fq` returns
   HTTP 409 with `__type: "Search Error"` rather than federal's HTTP 400
   `"Search Query Error"` -- shared/ckan.py's `action()` maps that 409 to
   UpstreamError (only 400/404 get a more specific type), which is the
   right typed-error outcome even though the status code differs from
   federal's.
"""

MODULE_NAME = "ckan_montreal"
MODULE_DESCRIPTION = (
    "City of Montreal open-data portal (donnees.montreal.ca): full-text "
    "dataset search, dataset detail with resources, publishing "
    "organizations, tags, groups, individual resource metadata, and "
    "licenses, via the standard CKAN Action API. Covers the municipal "
    "open-data catalogue (~404 datasets). Content is French-only in "
    "practice; all tools accept lang: en|fr for interface consistency "
    "but it does not translate the underlying (French) data."
)
MODULE_DESCRIPTION_FR = (
    "Portail de données ouvertes de la Ville de Montréal "
    "(donnees.montreal.ca) : recherche de jeux de données en texte "
    "intégral, détail des jeux de données avec ressources, organisations "
    "responsables, mots-clés, groupes, métadonnées des ressources "
    "individuelles et licences, via l'API Action CKAN standard. Couvre le "
    "catalogue municipal de données ouvertes (~404 jeux de données). Le "
    "contenu est en pratique uniquement en français; tous les outils "
    "acceptent lang : en|fr par souci de cohérence d'interface, mais cela "
    "ne traduit pas les données sous-jacentes (en français)."
)
