# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx[http2]>=0.27", "polars>=1.0", "shapely>=2.0"]
# ///
# ============================================================
# RentSafeTO apartment building scores by Toronto neighbourhood
# Author: Daniel Sanchez
# Purpose: Do Toronto neighbourhoods where more households rent have
#          lower-scoring apartment buildings? Places each RentSafeTO
#          building (latest evaluation since 2023) in one of the City's
#          140 neighbourhoods, then sets the neighbourhood's mean score
#          beside its 2016 renter share from the Neighbourhood Profiles.
#          Every input is a City of Toronto DataStore table on
#          open.toronto.ca, read through the CKAN API exactly as
#          MapleStats MCP reads it (ckan_datastore_search, portal
#          "toronto"; reproduce_code gives the single-page version).
# Inputs:  open.toronto.ca DataStore resources
#          244f7a02-da5c-425b-b55f-fbdd133dd732 (Apartment Building
#          Evaluations 2023 - current), 7d3ae06b-0217-4cc9-92ed-97adafca2f7b
#          (Neighbourhoods - historical 140), 7f8eee5e-85fb-415c-aef3-c3bd4998445f
#          (Neighbourhood Profiles 2016, 140-neighbourhood model)
# Outputs: data/raw/*.json (cached API pages), output/rentsafe_by_neighbourhood.csv
# Licence: Contains information licensed under the Open Government
#          Licence - Toronto (https://open.toronto.ca/open-data-licence/).
# Run:     uv run docs/examples/toronto/rentsafe_by_neighbourhood.py
# ============================================================

# %% 0. Setup

import json
import logging
from pathlib import Path

import httpx
import polars as pl
from shapely import STRtree
from shapely.geometry import Point, shape

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("rentsafe_by_neighbourhood")

HERE = Path(__file__).resolve().parent
RAW_DIR = HERE / "data" / "raw"
OUTPUT_DIR = HERE / "output"
RAW_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

API = "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/datastore_search"
EVALUATIONS = "244f7a02-da5c-425b-b55f-fbdd133dd732"
BOUNDARIES = "7d3ae06b-0217-4cc9-92ed-97adafca2f7b"
PROFILES = "7f8eee5e-85fb-415c-aef3-c3bd4998445f"
PAGE_ROWS = 1000
MIN_BUILDINGS = 5  # neighbourhoods with fewer evaluated buildings are left out of the ranking

# The profile labels are matched exactly, leading spaces included: the
# spaces mark "Renter" as a sub-item of the tenure total.
TENURE_TOTAL = "Total - Private households by tenure - 25% sample data"
RENTER = "  Renter"


def fetch_table(resource_id: str, params: dict[str, str], name: str) -> list[dict]:
    """Every row of one DataStore query, paged by 1,000 and cached in data/raw."""
    rows: list[dict] = []
    with httpx.Client(http2=True, timeout=120, follow_redirects=True) as client:
        while True:
            raw_path = RAW_DIR / f"{name}_{len(rows)}.json"
            if not raw_path.exists():
                query = {"resource_id": resource_id, "limit": PAGE_ROWS, "offset": len(rows)}
                response = client.get(API, params=query | params)
                response.raise_for_status()
                raw_path.write_bytes(response.content)
            result = json.loads(raw_path.read_text(encoding="utf-8"))["result"]
            rows.extend(result["records"])
            if not result["records"] or len(rows) >= result["total"]:
                return rows


# %% 1. Read inputs

evaluation_rows = fetch_table(
    EVALUATIONS,
    {
        "fields": "_id,RSN,SITE ADDRESS,WARDNAME,PROPERTY TYPE,CONFIRMED UNITS,"
        "EVALUATION COMPLETED ON,CURRENT BUILDING EVAL SCORE,LATITUDE,LONGITUDE",
        "sort": "_id",
    },
    "evaluations",
)
boundary_rows = fetch_table(
    BOUNDARIES, {"fields": "AREA_NAME,AREA_SHORT_CODE,geometry"}, "boundaries"
)
profile_rows = fetch_table(
    PROFILES,
    {"filters": json.dumps({"Characteristic": ["Neighbourhood Number", TENURE_TOTAL, RENTER]})},
    "profiles",
)
log.info(
    "Read %s evaluations, %s neighbourhoods, %s profile rows",
    len(evaluation_rows),
    len(boundary_rows),
    len(profile_rows),
)

# %% 2. Check inputs

assert len(boundary_rows) == 140, f"expected 140 neighbourhoods, got {len(boundary_rows)}"
assert len(profile_rows) == 3, f"expected 3 profile rows, got {len(profile_rows)}"
assert evaluation_rows, "the RentSafeTO table returned no rows"

# %% 3. Prepare data

# Scores and dates are text in the DataStore (one score is "81.1"); a
# building evaluated twice since 2023 keeps its latest evaluation only.

buildings = (
    pl.DataFrame(evaluation_rows, infer_schema_length=None)
    .select(
        pl.col("RSN").alias("rsn"),
        pl.col("SITE ADDRESS").alias("address"),
        pl.col("WARDNAME").alias("ward_name"),
        pl.col("PROPERTY TYPE").alias("property_type"),
        pl.col("CONFIRMED UNITS").cast(pl.Int64, strict=False).alias("units"),
        pl.col("EVALUATION COMPLETED ON").str.slice(0, 10).alias("evaluated_on"),
        pl.col("CURRENT BUILDING EVAL SCORE").cast(pl.Float64, strict=False).alias("score"),
        pl.col("LATITUDE").cast(pl.Float64, strict=False).alias("latitude"),
        pl.col("LONGITUDE").cast(pl.Float64, strict=False).alias("longitude"),
    )
    .sort("evaluated_on")
    .unique(subset="rsn", keep="last")
    .filter(pl.col("score").is_not_null())
)

# Point-in-polygon against the 140 historical boundaries (WGS84, as the
# DataStore serves them); the STRtree only narrows the candidates. A
# building the table gives no coordinates for cannot be placed.

polygons = [shape(json.loads(row["geometry"])) for row in boundary_rows]
tree = STRtree(polygons)
codes = []
for longitude, latitude in buildings.select("longitude", "latitude").iter_rows():
    if longitude is None or latitude is None:
        codes.append(None)
        continue
    point = Point(longitude, latitude)
    hits = [i for i in tree.query(point) if polygons[i].contains(point)]
    codes.append(boundary_rows[hits[0]]["AREA_SHORT_CODE"] if hits else None)
buildings = buildings.with_columns(
    pl.Series("neighbourhood_number", codes).cast(pl.Int64, strict=False)
)
no_coordinates = buildings.filter(
    pl.col("latitude").is_null() | pl.col("longitude").is_null()
).height
unplaced = buildings.filter(pl.col("neighbourhood_number").is_null()).height

# The profile table is wide (one column per neighbourhood); long format puts
# one neighbourhood per row, with values like "9,870" made numeric.

profiles_long = (
    pl.DataFrame(profile_rows, infer_schema_length=None)
    .drop("_id", "Category", "Topic", "Data Source", "City of Toronto")
    .unpivot(index="Characteristic", variable_name="neighbourhood", value_name="value")
    .with_columns(pl.col("value").str.replace_all(",", "").cast(pl.Float64, strict=False))
    .pivot(on="Characteristic", index="neighbourhood", values="value")
    .select(
        "neighbourhood",
        pl.col("Neighbourhood Number").cast(pl.Int64).alias("neighbourhood_number"),
        (pl.col(RENTER) / pl.col(TENURE_TOTAL)).alias("renter_share_2016"),
    )
)

# %% 4. Calculate estimates

by_neighbourhood = (
    buildings.filter(pl.col("neighbourhood_number").is_not_null())
    .group_by("neighbourhood_number")
    .agg(
        pl.len().alias("buildings"),
        pl.col("units").sum().alias("units"),
        pl.col("score").mean().round(2).alias("mean_score"),
        pl.col("score").median().alias("median_score"),
        pl.col("score").min().alias("lowest_score"),
    )
    .join(profiles_long, on="neighbourhood_number", how="left", validate="1:1")
    .sort("mean_score")
)
ranked = by_neighbourhood.filter(pl.col("buildings") >= MIN_BUILDINGS)
spearman = ranked.select(pl.corr("renter_share_2016", "mean_score", method="spearman")).item()

# %% 5. Check results

assert by_neighbourhood["neighbourhood"].null_count() == 0, "a neighbourhood number has no profile"
assert buildings.height - unplaced == by_neighbourhood["buildings"].sum(), "buildings were lost"
outside = unplaced - no_coordinates
assert outside <= 0.01 * buildings.height, f"{outside} buildings fell outside every boundary"

# %% 6. Write outputs

output_path = OUTPUT_DIR / "rentsafe_by_neighbourhood.csv"
by_neighbourhood.write_csv(output_path)
log.info(
    "%s buildings in %s neighbourhoods (%s not placed, %s of them without coordinates); %s "
    "neighbourhoods with %s+ buildings; Spearman rank correlation of renter share and mean "
    "score: %.2f",
    buildings.height,
    by_neighbourhood.height,
    unplaced,
    no_coordinates,
    ranked.height,
    MIN_BUILDINGS,
    spearman,
)
log.info("Lowest mean scores:\n%s", ranked.head(5))
log.info("Highest mean scores:\n%s", ranked.tail(5))
log.info("Wrote %s", output_path)
