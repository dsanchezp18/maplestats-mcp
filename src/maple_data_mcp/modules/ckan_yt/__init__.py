"""Yukon open-data portal (open.yukon.ca), CKAN Action API 3.

Covers catalogue search, dataset detail, organizations, resources,
licenses, tags, and groups via the standard `/api/3/action/...`
endpoints. Confirmed live this session against 3,841 datasets (the
catalogue's actual `package_search` count with no filter, checked
directly rather than assumed) -- a much smaller, territorial-government
catalogue than the federal portal's ~48,000. `site_read` 400s on this
deployment (confirmed live), so connectivity is checked with
`package_list`/`package_search` instead, per the task brief.

Unlike the federal portal (modules/ckan_federal/), two real differences
were confirmed live here rather than assumed shared:

1. This portal genuinely uses CKAN tags (914, confirmed via `tag_list`)
   and groups (17 subject-category groups, confirmed via `group_list`)
   -- every sampled package carries populated `tags`/`groups` arrays.
   See client.py/schemas.py for the resulting `ckan_yt_list_tags`/
   `ckan_yt_list_groups` tools, which federal deliberately omits.
2. This portal is English-only at the CKAN-data level -- confirmed live
   that no package/organization/resource/license record anywhere
   carries a `_translated` or `_fra`-suffixed field (scanned several
   real records of each type). The site's own UI wrapper does offer
   `/en/`- and `/fr/`-prefixed chrome (confirmed both 200, with a
   genuinely different `<html lang>` attribute), but a dataset's own
   title/notes text stays in English under either prefix. `lang` is
   still accepted on every tool, per this repo's convention, but has no
   effect on the data itself -- only on which landing-page chrome
   variant `landing_page_url` points to. See client.py for detail.

The HTTP/rate-limit/error/envelope layer is reused as-is from
shared/ckan.py: package_show/organization_show/resource_show 404s and
package_search's malformed-sort 400 both came back in the identical
`{"help","success","result"}`/`{"error":{"__type",...}}` shape already
handled there, confirmed live rather than assumed from the federal
portal's behavior.
"""

MODULE_NAME = "ckan_yt"
MODULE_DESCRIPTION = (
    "Yukon Open Data portal (open.yukon.ca): full-text dataset search, "
    "dataset detail with resources, publishing organizations, individual "
    "resource metadata, licenses, tags, and subject-category groups, via "
    "the standard CKAN Action API. Covers the Yukon territorial "
    "open-data catalogue (~3,841 datasets). All tools accept lang: "
    "en|fr, though this portal's dataset content is English-only -- lang "
    "only changes which landing-page chrome variant is linked."
)
MODULE_DESCRIPTION_FR = (
    "Portail de données ouvertes du Yukon (open.yukon.ca) : recherche de "
    "jeux de données en texte intégral, détail des jeux de données avec "
    "ressources, organisations responsables, métadonnées des ressources "
    "individuelles, licences, mots-clés et groupes thématiques, via "
    "l'API Action CKAN standard. Couvre le catalogue territorial du "
    "Yukon (environ 3 841 jeux de données). Tous les outils acceptent "
    "lang : en|fr, mais le contenu des jeux de données de ce portail est "
    "uniquement en anglais -- lang ne change que la variante d'habillage "
    "de la page d'accueil liée."
)
