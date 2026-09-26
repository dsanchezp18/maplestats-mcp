"""Constants for the Government of Canada Recalls and Safety Alerts site.

Confirmed live 2026-09-26:
- The open-data dump (linked from open.canada.ca dataset
  d38de914-c94c-429b-8ab1-8776c31643e3) is one JSON array per language,
  34,131 rows each, same NIDs in both, regenerated daily (Last-Modified
  around 02:19 UTC). The English file is about 15.7 MB and the French one
  about 20.8 MB; neither is served gzip-compressed.
- English keys: NID, Title, URL, Organization, Product, Issue,
  "What you should do", Category, "Recall class", "Last updated",
  Archived. French keys: NID, Titre, URL, Organization, Produit,
  Problème, "Ce que vous devriez faire", Catégorie, "Classe de rappel",
  "Dernière mise à jour", Archivé. Every value is a string or null.
- /{lang}/node/{nid} answers 302 to the recall's page in that language,
  and 404 for an unknown node.
- The old healthycanadians.gc.ca/recall-alert-rappel-avis/api/ JSON API
  still answers but stopped at October 2021 (newest recallId 76771), and
  the site's RSS feeds carry only the last few items, so neither is used.
"""

SITE = "https://recalls-rappels.canada.ca"
DUMP_URLS = {
    "en": SITE + "/sites/default/files/opendata-donneesouvertes/HCRSAMOpenData.json",
    "fr": SITE + "/sites/default/files/opendata-donneesouvertes/SCRSAMDonneesOuvertes.json",
}
NODE_URL = SITE + "/{lang}/node/{nid}"
DATASET_URL = "https://open.canada.ca/data/en/dataset/d38de914-c94c-429b-8ab1-8776c31643e3"

# Row keys per language dump, verified against the live files.
KEYS = {
    "en": {
        "title": "Title",
        "product": "Product",
        "issue": "Issue",
        "category": "Category",
        "recall_class": "Recall class",
        "last_updated": "Last updated",
        "archived": "Archived",
    },
    "fr": {
        "title": "Titre",
        "product": "Produit",
        "issue": "Problème",
        "category": "Catégorie",
        "recall_class": "Classe de rappel",
        "last_updated": "Dernière mise à jour",
        "archived": "Archivé",
    },
}

RATE_LIMIT_SOURCE = "recalls"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

DUMP_CACHE_TTL_SECONDS = 6 * 60 * 60
PAGE_CACHE_TTL_SECONDS = 6 * 60 * 60
DUMP_TIMEOUT_SECONDS = 90.0

LIMIT_DEFAULT = 25
LIMIT_MAX = 200
GROUPS_DEFAULT = 50
GROUPS_MAX = 500
TABLE_ROWS_MAX = 300
TEXT_MAX_CHARS = 8000

AGENCIES = ("health_canada", "cfia", "transport_canada")
PRODUCT_TYPES = ("food", "health_product", "consumer_product", "vehicle")

# The dump's Organization is a publishing unit, not always an agency:
# Health Canada appears as several branches. The nine values (and their
# French forms, paired by NID across the two files) were all seen live.
ORGANIZATION_AGENCY = {
    "TC": "transport_canada",
    "CFIA": "cfia",
    "ACIA": "cfia",
    "Medical devices": "health_canada",
    "Instruments médicaux": "health_canada",
    "Consumer product safety": "health_canada",
    "Sécurité des produits de consommation": "health_canada",
    "Drugs and health products": "health_canada",
    "Médicaments et produits de santé": "health_canada",
    "Communications and Public Affairs Branch": "health_canada",
    "Direction générale des communications et des affaires publiques": "health_canada",
    "Marketed health products": "health_canada",
    "Produits de santé commercialisés": "health_canada",
    "Controlled substances and cannabis": "health_canada",
    "Substances contrôlées et du cannabis": "health_canada",
    "HC": "health_canada",
    "SC": "health_canada",
}

# Product type, approximating the site's four top-level categories
# (Vehicles, Health products, Consumer products, Food), which the dump
# does not carry. Units that publish one kind of product fix the type;
# Health Canada's communications branch and "HC" rows are typed by their
# category leaves. Checked 2026-09-26 against the site's own facet counts
# for non-archived notices: vehicle 9,895 vs 9,889, health 6,283 vs
# 6,285, consumer 2,256 vs 2,244, food 1,263 vs 1,272. Cannabis is a
# consumer product on the site, not a health product.
ORGANIZATION_TYPE = {
    "TC": "vehicle",
    "CFIA": "food",
    "ACIA": "food",
    "Medical devices": "health_product",
    "Instruments médicaux": "health_product",
    "Drugs and health products": "health_product",
    "Médicaments et produits de santé": "health_product",
    "Marketed health products": "health_product",
    "Produits de santé commercialisés": "health_product",
    "Consumer product safety": "consumer_product",
    "Sécurité des produits de consommation": "consumer_product",
    "Controlled substances and cannabis": "consumer_product",
    "Substances contrôlées et du cannabis": "consumer_product",
}
FOOD_LEAVES = frozenset({"Food", "Aliments"})
CONSUMER_LEAVES = frozenset(
    {"Cannabis", "Medical cannabis", "Consumer products", "Produits de consommation"}
)
HEALTH_LEAVES = frozenset(
    {
        "Drugs",
        "Médicaments",
        "Natural health products",
        "Produits de santé naturels",
        "Medical devices",
        "Matériel médical, instruments médicaux et dispositifs médicaux",
        "Biologic or vaccine",
        "Vaccins et produits biologiques",
        "Health products",
        "Produits de santé",
        "Veterinary drugs",
        "Médicaments vétérinaires",
        "Radiopharmaceuticals",
        "Radiopharmaceutiques",
        "Homeopathic medicine",
        "Médicament homéopathique",
    }
)

# "Published by" on a recall page, in either language.
PUBLISHER_AGENCY = {
    "health canada": "health_canada",
    "santé canada": "health_canada",
    "canadian food inspection agency": "cfia",
    "agence canadienne d'inspection des aliments": "cfia",
    "transport canada": "transport_canada",
    "transports canada": "transport_canada",
}
