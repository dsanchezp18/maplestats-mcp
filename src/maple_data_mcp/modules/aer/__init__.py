"""Alberta Energy Regulator (AER) statistical reports (www.aer.ca), a
different platform from open.alberta.ca's CKAN catalogue already
covered by `ckan_*` (portal="ab").

Confirmed live 2026-09-22: two real, undocumented quirks in how AER
serves these files, both handled here.

1. The ST1 well-licence daily `.TXT` files answer with an HTML page
   containing a client-side `<meta http-equiv="refresh">` pointing at
   `static.aer.ca`, not a real HTTP redirect -- a plain `httpx` request
   (even with `follow_redirects=True`) receives that meta-refresh HTML,
   not the file. This client goes straight to the `static.aer.ca` host
   for those files rather than the public `www.aer.ca` URL shown on the
   AER website.
2. The ST3 production-volume `.xlsx` files and the ST1 monthly/yearly
   `.zip` archives, by contrast, DO answer with a genuine HTTP 303 to
   the same `static.aer.ca` host -- `httpx` follows these transparently
   with `follow_redirects=True`. So the two file families need opposite
   handling on the same `www.aer.ca` origin: one is bypassed manually,
   the other is left to redirect-following.

A third finding worth recording even though it changed nothing here:
AER's own current "Statistical Reports" index (confirmed live by
reading all 4 pages of it, not guessed) shows ST39 is "Alberta
Mineable Oil Sands Plant Statistics" -- oil sands production/supply/
disposition/inventory -- not pipeline statistics, despite that being a
commonly repeated claim elsewhere. The closest real pipeline-related
statistical reports are ST96 (Pipeline Approval and Disposition Daily
List) and ST100 (Pipeline Construction Notification List), neither
pursued in this pass; this module does not claim pipeline coverage.

Content parsing stays link-resolution-only for ST3's `.xlsx` files
(confirmed existence via HEAD, not spreadsheet parsing), matching
`modules/cmhc/data_tables/`'s own precedent -- this project has no
pinned XLSX-parsing dependency, and adding one is a call for the
project maintainer, not a decision made inside a single module.
"""

MODULE_NAME = "aer"
MODULE_DESCRIPTION = (
    "Alberta Energy Regulator (AER) statistical reports (www.aer.ca): ST1 "
    "daily well-licence lists (raw report text) and monthly/yearly archive "
    "links, and ST3 monthly production-volume/price XLSX download links "
    "(butane, ethane, gas, NGL, oil, propane, sulphur, oil prices). "
    "Distinct from open.alberta.ca's CKAN catalogue already covered by "
    'ckan_* (portal="ab").'
)
MODULE_DESCRIPTION_FR = (
    "Rapports statistiques de l'Alberta Energy Regulator (AER, www.aer.ca) : "
    "listes quotidiennes ST1 des permis de puits (texte brut) et liens "
    "d'archives mensuelles/annuelles, ainsi que liens de téléchargement "
    "XLSX ST3 des volumes de production mensuels et des prix (butane, "
    "éthane, gaz, LGN, pétrole, propane, soufre, prix du pétrole). Distinct "
    'du catalogue CKAN d\'open.alberta.ca déjà couvert par ckan_* (portal="ab").'
)
