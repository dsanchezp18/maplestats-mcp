# Hosting the server, and what to do about PUMF tabulation

Written 2026-09-29. Hosting prices and free-tier limits are from memory and
were not checked live; confirm them before choosing. Nothing here is
decided: the current leaning is to host without `statcan_pumf_tabulate`
(section 4), to be revisited.

## 1. Hosting options

The website (`site/`) is already on GitHub Pages (`pages.yml`). The MCP
server needs a host that runs a long-lived container; the repo already has
a `Dockerfile`, `docker-compose.yml`, `MAPLE_TRANSPORT=http` and `/health`.
Set `MAPLE_AUTH_TOKEN` and `MAPLE_REQUIRE_AUTH=1` on any public instance.

| Option | Cost | Always on? | Notes |
|---|---|---|---|
| Hugging Face Spaces (Docker) | free | sleeps after about 2 days idle | app port 8000; ephemeral disk; believed to give far more RAM and disk than Render free |
| Render free web service | free | sleeps after about 15 min, wake takes about 1 min | deploys from the `Dockerfile`; no persistent disk; about 512 MB RAM |
| Google Cloud Run | free at low traffic | scales to zero, cold starts of seconds | needs a billing account |
| Oracle Cloud Always Free VM | free | yes | only free option with a persistent disk; most setup (Docker plus Caddy) |
| Render Starter | about $7/month, disk about $0.25/GB/month | yes | |
| Fly.io small VM plus volume | about $2-5/month | yes | |
| Azure Container Apps | a few dollars a month plus Azure Files | one replica | the recipe already in the ROADMAP |

A sleeping host hurts MCP clients: they connect at startup and time out
after roughly 30-60 seconds, so a cold start looks like a broken server.
A free monitor (UptimeRobot, cron-job.org) pinging `/health` every 5-10
minutes keeps Render or Hugging Face awake, within Render's monthly free
hours.

Precedent: `mcp-statcan` (Aryan-Jhaveri, listed on the About page)
is hosted on Render at `https://mcp-statcan.onrender.com/mcp`, deployed
from a `render.yaml`. It leaves out its SQLite features on the shared
deployment, so nothing needs a disk.

## 2. Why PUMF tabulation is the hard part

`statcan_pumf_tabulate` (`pumf/tabulate.py`) downloads the whole ZIP
(30-534 MB), extracts the data file to the cache directory, and queries the
CSV with DuckDB. On a free host:

- The disk is ephemeral, so every restart or wake-up loses the file.
- The download outlives the 120 s tool timeout. `asyncio.shield` lets it
  finish in the background, but the first caller still gets an error.
- `_download` writes the archive and then the extracted file, so peak disk
  is the ZIP plus the uncompressed file.
- The cache holds raw CSV, which DuckDB reads as text on every query even
  though a query uses a few columns.

The codebook tools read ZIPs by HTTP range request and need no disk.

## 3. Ways to fix it

1. **Stream, do not stage.** Pipe the HTTP stream through `zlib` (ZIP
   header parsing already exists in `shared/remote_zip.py`) and never write
   the archive. Halves peak disk.
2. **Cache Parquet, not CSV.** Convert to zstd Parquet while streaming,
   slicing fixed-width files with the codebook positions. Expected to be
   several times smaller and faster, since queries read only the needed
   columns; the 1,000 bootstrap-weight files gain the most. The ratio is
   not measured yet.
3. **Prebuilt Parquet on free static hosting.** A scheduled GitHub Action
   converts each supported PUMF and publishes it to a Hugging Face Dataset
   or Cloudflare R2; the server queries it with DuckDB `httpfs` range
   reads. No download, no disk, works on any host. Needs the converter and
   a licence check (the Statistics Canada Open Licence is believed to allow
   redistribution with attribution; not verified).
4. **Friendlier first call.** Return "preparing this file, retry in about N
   minutes" instead of timing out.
5. **Size guard for hosted mode.** A `MAPLE_PUMF_MAX_MB` cap that refuses
   larger files with a "run locally" message.
6. **Persistent disk.** Render Starter plus disk, or a Fly volume. The
   first call per file is still slow.

## 4. The catch with fix 3, and the leaning

New PUMFs appear often, so a prebuilt set is never complete. Fix 3 would
need either a fixed, documented list of supported surveys refreshed on a
schedule, or automatic detection of new PUMFs through
`statcan_pumf_search`. Neither is free of maintenance, and each survey has
its own layout and variance method (`VarianceMethod` covers only Census
2021, EICS 2024 and CSWC 2024-2025).

Current leaning: host without `statcan_pumf_tabulate`. Search, ZIP listings
and codebooks keep working; microdata tabulation stays a local-install
feature, and the hosted server says so. Fixes 1, 2 and 4 remain worth doing
for local users regardless.

## 5. Open questions

- Compression ratio and StatCan download speed from a cloud host (test on
  one PUMF, for example LFS).
- Current free-tier limits: Hugging Face RAM and disk, Render hours.
- Whether hosted mode is worth the setup at all before it has users.
