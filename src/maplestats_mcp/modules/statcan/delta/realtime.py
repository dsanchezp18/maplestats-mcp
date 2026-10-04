"""The 19 real-time (vintage) tables that StatCan pairs with regular tables.

A real-time table keeps every revision of a data point as a vintage (the
release date) dimension, released about a week after the official release
of its regular table. The list is the page
https://www.statcan.gc.ca/en/developers/real-time-data-tables (Table 1),
read on 2026-10-02; every title and product id below was checked against
WDS `getCubeMetadata` the same day. Three of the 19 real-time ids
(16100118, 16100119, 20100019) are listed on that page but WDS answered
CUBE_NOT_AVAILABLE for them, so `wds_available` is False and their titles
come from the page (English only). Six carry "inactive" in their WDS
title and end in 2025-12.

StatCan's own real-time viewer service (/rtdat-oadtr-service/) is never
called; the tables are read through WDS like any other cube.
"""

from __future__ import annotations

from maplestats_mcp.modules.statcan.delta import constants
from maplestats_mcp.modules.statcan.delta.archive_schemas import RealTimeTable, RealTimeTableList
from maplestats_mcp.modules.statcan.lang import say
from maplestats_mcp.shared.envelope import make_provenance

PAGE_URL = "https://www.statcan.gc.ca/en/developers/real-time-data-tables"

# (real-time product id, EN title, FR title, regular product id, EN title,
# FR title, listed by WDS).
_TABLES: tuple[tuple[int, str, str | None, int, str, str | None, bool], ...] = (
    (
        12100165,
        "Historical (real-time) releases of merchandise imports and exports, customs and balance of payments basis for all countries, by seasonal adjustment and North American Product Classification System (NAPCS)",
        "Diffusions historiques (temps réel) des importations et exportations de marchandises, base douanière et balance des paiements pour tous les pays, par désaisonnalisation et le Système de classification des produits de l'Amérique du Nord (SCPAN)",
        12100163,
        "International merchandise trade by commodity, monthly",
        "Commerce international de marchandises par classification des produits, mensuel",
        True,
    ),
    (
        16100014,
        "Historical (real-time) releases of real manufacturing sales, orders, inventory owned and inventory to sales ratio, 2017 dollars, seasonally adjusted, inactive",
        "Diffusions historiques (temps réel) de valeur réelle des ventes, des commandes, des stocks possédés et le ratio des stocks aux ventes des industries manufacturières, en dollars de 2017, désaisonnalisées, inactif",
        16100013,
        "Real manufacturing sales, orders, inventory owned and inventory to sales ratio, 2017 dollars, seasonally adjusted",
        "Valeur réelle des ventes, des commandes, des stocks possédés et le ratio des stocks aux ventes des industries manufacturières, en dollars de 2017, désaisonnalisées",
        True,
    ),
    (
        16100015,
        "Historical (real-time) releases manufacturing capacity utilization rates, inactive",
        "Diffusions historiques (temps réel) des taux d’utilisation de la capacité de fabrication, inactif",
        16100012,
        "Manufacturing capacity utilization rates, by North American Industry Classification System (NAICS)",
        "Taux d'utilisation de la capacité de fabrication, selon le Système de classification des industries de l'Amérique du Nord (SCIAN)",
        True,
    ),
    (
        16100118,
        "Historical (real-time) releases of manufacturers' sales, inventories, orders and inventory to sales ratios, by North American Industry Classification System (NAICS), Canada",
        None,
        16100047,
        "Manufacturers' sales, inventories, orders and inventory to sales ratios, by industry (dollars unless otherwise noted)",
        "Stocks, ventes, commandes et rapport des stocks sur les ventes pour les industries manufacturières, selon l'industrie (dollars sauf indication contraire)",
        False,
    ),
    (
        16100119,
        "Historical (real-time) releases of manufacturing sales, by North American Industry Classification System (NAICS) and province",
        None,
        16100048,
        "Manufacturing sales by industry and province, monthly (dollars unless otherwise noted)",
        "Ventes pour les industries manufacturières selon l'industrie et province, données mensuelles (dollars sauf indication contraire)",
        False,
    ),
    (
        20100005,
        "Historical (real-time) releases of wholesale sales, price and volume, seasonally adjusted, inactive",
        "Diffusions historiques (temps réel) des ventes de grossistes, prix et volume, désaisonnalisées, inactif",
        20100003,
        "Wholesale sales, price and volume, by industry, seasonally adjusted",
        "Ventes de grossistes, prix et volume, selon l'industrie, désaisonnalisées",
        True,
    ),
    (
        20100019,
        "Historical (real-time) releases of wholesale trade, sales",
        None,
        20100074,
        "Wholesale trade, sales",
        "Commerce de gros, ventes",
        False,
    ),
    (
        20100020,
        "Historical (real-time) releases of wholesale trade, inventories, inactive",
        "Diffusions historiques (temps réel) du commerce de gros, stocks, inactif",
        20100076,
        "Wholesale trade, inventories",
        "Commerce de gros, stocks",
        True,
    ),
    (
        18100259,
        "Historical (real-time) releases of Consumer Price Index (CPI) statistics, measures of core inflation - Bank of Canada definitions",
        "Diffusions historiques (temps réel) des statistiques de l'Indice des prix à la consommation (IPC), mesures de l'inflation fondamentale - définitions de la Banque du Canada",
        18100256,
        "Consumer Price Index (CPI) statistics, measures of core inflation and other related statistics - Bank of Canada definitions",
        "Statistiques de l'Indice des prix à la consommation (IPC), mesures de l'inflation fondamentale et autres statistiques connexes - définitions de la Banque du Canada",
        True,
    ),
    (
        20100081,
        "Historical (real-time) releases of monthly retail trade, sales, inactive",
        "Diffusions historiques (temps réel) du commerce de détail mensuel, ventes, inactif",
        20100056,
        "Monthly retail trade sales by province and territory",
        "Ventes mensuelles du commerce de détail par province et territoire",
        True,
    ),
    (
        20100082,
        "Historical (real-time) releases of monthly retail sales, price, and volume, inactive",
        "Diffusions historiques (temps réel) des ventes au détail mensuelles, prix et volume, inactif",
        20100067,
        "Monthly retail sales, price, and volume, seasonally adjusted",
        "Ventes mensuelles au détail, prix et volume, désaisonnalisées",
        True,
    ),
    (
        14100331,
        "Historical (real-time) releases of employment and average weekly earnings (including overtime) for all employees by industry, monthly, seasonally adjusted",
        "Diffusions historiques (temps réel) de l'emploi et la rémunération hebdomadaire moyenne (incluant temps supplémentaire) pour l'ensemble des salariés selon l'industrie, données mensuelles désaisonnalisées",
        14100220,
        "Employment and average weekly earnings (including overtime) for all employees by industry, monthly, seasonally adjusted, Canada",
        "Emploi et rémunération hebdomadaire moyenne (incluant le temps supplémentaire) pour l'ensemble des salariés selon l'industrie, données mensuelles désaisonnalisées, Canada",
        True,
    ),
    (
        14100332,
        "Historical (real-time) releases of employment and average weekly earnings (including overtime) for all employees by province and territory, monthly, seasonally adjusted",
        "Diffusions historiques (temps réel) de l'emploi et la rémunération hebdomadaire moyenne (incluant temps supplémentaire) pour l'ensemble des salariés selon la province et le territoire, données mensuelles désaisonnalisées",
        14100223,
        "Employment and average weekly earnings (including overtime) for all employees by province and territory, monthly, seasonally adjusted",
        "Emploi et rémunération hebdomadaire moyenne (incluant le temps supplémentaire) pour l'ensemble des salariés selon la province et le territoire, données mensuelles, désaisonnalisées",
        True,
    ),
    (
        36100491,
        "Historical (real-time) releases of gross domestic product (GDP) at basic prices, by industry, monthly",
        "Diffusions historiques (temps réel) du produit intérieur brut (PIB) aux prix de base, par industries, mensuel",
        36100434,
        "Gross domestic product (GDP) at basic prices, by industry, monthly",
        "Produit intérieur brut (PIB) aux prix de base, par industries, mensuel",
        True,
    ),
    (
        36100042,
        "Historical (real-time) releases of balance of international payments, current account, seasonally adjusted, quarterly",
        "Diffusions historiques (temps réel) de la balance des paiements internationaux, compte courant, désaisonnalisé, trimestriel",
        36100018,
        "Balance of international payments, current account, seasonally adjusted, quarterly",
        "Balance des paiements internationaux, compte courant, désaisonnalisé, trimestriel",
        True,
    ),
    (
        36100430,
        "Vintages of releases of gross domestic product, income-based",
        "Versions de diffusions du produit intérieur brut, en termes de revenus",
        36100103,
        "Gross domestic product, income-based, quarterly",
        "Produit intérieur brut, en termes de revenus, trimestriel",
        True,
    ),
    (
        36100431,
        "Vintages of releases of gross domestic product, expenditure-based",
        "Versions de diffusions du produit intérieur brut, en termes de dépenses",
        36100104,
        "Gross domestic product, expenditure-based, Canada, quarterly",
        "Produit intérieur brut, en termes de dépenses, Canada, trimestriel",
        True,
    ),
    (
        34100278,
        "Historical (real time) releases of capital and repair expenditures, non-residential tangible assets, by industry and geography",
        "Diffusions historiques (temps réel) des dépenses en immobilisation et réparations, actifs corporels non résidentiels, par industrie selon la géographie",
        34100035,
        "Capital and repair expenditures, non-residential tangible assets, by industry and geography",
        "Dépenses en immobilisation et réparations, actifs corporels non résidentiels, par industrie selon la géographie",
        True,
    ),
    (
        34100279,
        "Historical (real time) releases of capital and repair expenditures, non-residential tangible assets, by industry, Canada",
        "Diffusions historiques (temps réel) des dépenses en immobilisations et réparations, actifs corporels non résidentiels, selon l'industrie, Canada",
        34100036,
        "Capital and repair expenditures, non-residential tangible assets by industry",
        "Dépenses en immobilisation et réparations, actifs corporels non résidentiels par industrie",
        True,
    ),
)


def _table_number(product_id: int) -> str:
    text = str(product_id)
    return f"{text[:2]}-{text[2:4]}-{text[4:]}"


def _note(title: str, available: bool, lang: str) -> str | None:
    if not available:
        return say(
            "Listed on StatCan's real-time page, but WDS getCubeMetadata answered "
            "CUBE_NOT_AVAILABLE on 2026-10-02.",
            "Figure sur la page des tableaux en temps réel de Statistique Canada, mais "
            "getCubeMetadata de WDS a répondu CUBE_NOT_AVAILABLE le 2026-10-02 ; titre "
            "disponible en anglais seulement.",
            lang,
        )
    if title.endswith(", inactive"):
        return say(
            "WDS titles this table inactive; its data end in 2025-12.",
            "WDS indique que ce tableau est inactif ; ses données se terminent en 2025-12.",
            lang,
        )
    return None


def list_real_time_tables(query: str | None = None, lang: str = "en") -> RealTimeTableList:
    """The paired tables, optionally filtered by a word in either title or a product id."""
    needle = query.casefold().strip() if query else None
    tables = [
        RealTimeTable(
            real_time_product_id=rt_id,
            real_time_table=_table_number(rt_id),
            real_time_title_en=rt_en,
            real_time_title_fr=rt_fr,
            regular_product_id=reg_id,
            regular_table=_table_number(reg_id),
            regular_title_en=reg_en,
            regular_title_fr=reg_fr,
            wds_available=available,
            note=_note(rt_en, available, lang),
        )
        for rt_id, rt_en, rt_fr, reg_id, reg_en, reg_fr, available in _TABLES
        if needle is None
        or needle in f"{rt_en} {rt_fr or ''} {reg_en} {reg_fr or ''} {rt_id} {reg_id}".casefold()
    ]
    return RealTimeTableList(
        count=len(tables),
        tables=tables,
        notes=[
            say(
                "Each real-time table adds a vintage (release date) dimension to its regular table; "
                "it is released about a week after the regular table. Use wds_get_cube_metadata for "
                "the real-time product id's dimensions, then wds_get_data_from_cube_coord or "
                "wds_get_full_table_download for the data.",
                "Chaque tableau en temps réel ajoute à son tableau régulier une dimension de "
                "version (date de diffusion) ; il est diffusé environ une semaine après le tableau "
                "régulier. Utilisez wds_get_cube_metadata pour les dimensions du tableau en temps "
                "réel, puis wds_get_data_from_cube_coord ou wds_get_full_table_download pour "
                "les données.",
                lang,
            ),
            say(
                "The regular table always shows the latest revision; the revision history lives only "
                "in the real-time table.",
                "Le tableau régulier présente toujours la dernière révision ; l'historique des "
                "révisions se trouve seulement dans le tableau en temps réel.",
                lang,
            ),
            say(
                "The three real-time ids with wds_available False are not served by WDS, so their "
                "history cannot be fetched here.",
                "Les trois tableaux en temps réel marqués wds_available False ne sont pas offerts "
                "par WDS ; leur historique ne peut donc pas être obtenu ici, et leur titre n'existe "
                "qu'en anglais.",
                lang,
            ),
        ],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=PAGE_URL,
            cached=True,
            schema_name="statcan_delta.RealTimeTableList",
            freshness=say(
                "Static list read from StatCan's real-time page and WDS on 2026-10-02.",
                "Liste fixe tirée de la page des tableaux en temps réel de Statistique Canada et "
                "de WDS le 2026-10-02.",
                lang,
            ),
            coverage=say(
                "All 19 real-time tables the page lists.",
                "Les 19 tableaux en temps réel figurant sur la page.",
                lang,
            ),
            lang=lang,
        ),
    )
