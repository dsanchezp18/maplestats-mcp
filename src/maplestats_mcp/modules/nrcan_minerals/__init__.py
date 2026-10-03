"""Natural Resources Canada: annual mineral production statistics.

NRCan's Minerals and Metals Statistics Division publishes one CSV per
reference year (1990 to the latest preliminary estimate) with every
commodity by province and territory: quantity produced or shipped and
value of shipments. Checked live 2026-10-03; see client.py.
"""

MODULE_NAME = "nrcan_minerals"
MODULE_DESCRIPTION = (
    "Natural Resources Canada annual mineral production statistics, tools prefixed "
    "nrcan_minerals_: for each reference year from 1990 to the latest preliminary estimate, "
    "every metal, non-metal, aggregate and coal commodity (gold, copper, nickel, iron ore, "
    "potash, diamonds, uranium, lithium, sand and gravel...) by province and territory, "
    "with quantity produced or shipped and value of shipments, confidential and "
    "preliminary flags kept; and one commodity's series across years. English only: NRCan "
    "publishes these files in English. Monthly production since 2020 is Statistics "
    "Canada table 16-10-0022 (wds_)."
)
MODULE_DESCRIPTION_FR = (
    "Statistiques annuelles de la production minérale de Ressources naturelles Canada, "
    "outils préfixés nrcan_minerals_ : pour chaque année de référence de 1990 à "
    "l'estimation préliminaire la plus récente, chaque produit minéral (or, cuivre, nickel, "
    "minerai de fer, potasse, diamants, uranium, lithium, sable et gravier, charbon...) par "
    "province et territoire, quantité produite ou expédiée et valeur des expéditions, avec "
    "les indicateurs de confidentialité et de données provisoires; et la série d'un produit "
    "sur plusieurs années. En anglais seulement, comme les fichiers de RNCan. La production "
    "mensuelle depuis 2020 est le tableau 16-10-0022 de Statistique Canada (wds_)."
)
