"""Office of the Parliamentary Budget Officer (PBO).

PBO has no open data portal, but its website reads a public JSON API
(https://99bank.pbo-dpb.ca/distribution/1/, also served as
rest-393962616e6b.pbo-dpb.ca), checked live 2026-09-26: /publications
(863 publications, 15 per page, filter by `types`), /publications/<id>
(the full record with the publication as PBOML, PBO's YAML markup, whose
table, html and kvlist slices carry the tables), /search?query= (scored
results across content types), /tags and /information-requests.

Terms: PBO materials may be used and reproduced for personal and
non-commercial use without permission, unaltered and with attribution;
commercial use needs permission.
"""

MODULE_NAME = "pbo"
MODULE_DESCRIPTION = (
    "Office of the Parliamentary Budget Officer (pbo-dpb.ca, tools prefixed pbo_): "
    "search PBO's 860+ publications (reports, notes, legislative costing notes, "
    "cost estimates of bills and motions, archived work since 2008) and read one "
    "with its tables: cost estimates over five years, economic and fiscal "
    "projections, Estimates analysis. Tables come from PBO's structured PBOML "
    "documents, present for costing notes since 2021 and most reports since "
    "2025; older items link to their PDF only. Use is personal and non-commercial, "
    "unaltered, with attribution to PBO."
)
MODULE_DESCRIPTION_FR = (
    "Bureau du directeur parlementaire du budget (pbo-dpb.ca, outils préfixés "
    "pbo_) : recherche parmi plus de 860 publications (rapports, notes, notes "
    "d'évaluation du coût de mesures législatives, estimations de coûts de projets "
    "de loi et de motions, archives depuis 2008) et lecture d'une publication avec "
    "ses tableaux, tirés des documents PBOML (notes d'évaluation depuis 2021, la "
    "plupart des rapports depuis 2025; les plus anciennes n'ont que le PDF). "
    "Utilisation personnelle et non commerciale, sans modification, avec mention "
    "du DPB."
)
