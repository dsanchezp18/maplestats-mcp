# Verification script for MapleData MCP - run this OUTSIDE the sandbox
# that built the project, on a machine with normal outbound HTTPS access.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File scripts\verify.ps1
# or, from the repo root:
#   .\scripts\verify.ps1

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$failures = @()

function Write-Step($msg) {
    Write-Host ""
    Write-Host "== $msg ==" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host "OK: $msg" -ForegroundColor Green
}

function Write-Fail($msg) {
    Write-Host "FAIL: $msg" -ForegroundColor Red
}

# Runs a native command (uv, docker, ...) and checks its real exit code -
# PowerShell's try/catch does NOT catch a non-zero exit from a native
# executable, only terminating errors, so $LASTEXITCODE is checked
# explicitly after every external command below.
function Invoke-Checked($label, [string]$exe, [string[]]$exeArgs) {
    Write-Step $label
    & $exe @exeArgs
    if ($LASTEXITCODE -eq 0) {
        Write-Ok $label
        return $true
    } else {
        Write-Fail "$label (exit code $LASTEXITCODE)"
        $script:failures += $label
        return $false
    }
}

# 1. Install dependencies
$null = Invoke-Checked "uv sync" "uv" @("sync")

# 2. Lint / type check (fast correctness gate before touching the network)
$null = Invoke-Checked "ruff check" "uv" @("run", "ruff", "check", "src", "tests")
$null = Invoke-Checked "pyright" "uv" @("run", "pyright")

# 3. Unit tests (all mocked - no network required)
$null = Invoke-Checked "pytest" "uv" @("run", "pytest")

# 4. Live smoke tests - these are intentionally separate from the mocked
#    unit tests because portal deployments differ in fields, language, and
#    anti-abuse behavior. Run every implemented source before release.
$liveSmokeScripts = @(
    "scripts/smoke_test.py",
    "scripts/smoke_test_boc.py",
    "scripts/smoke_test_ckan_federal.py",
    "scripts/smoke_test_ckan_ab.py",
    "scripts/smoke_test_ckan_bc.py",
    "scripts/smoke_test_ckan_on.py",
    "scripts/smoke_test_ckan_qc.py",
    "scripts/smoke_test_ckan_nt.py",
    "scripts/smoke_test_ckan_yt.py",
    "scripts/smoke_test_ckan_montreal.py",
    "scripts/smoke_test_ckan_toronto.py",
    "scripts/smoke_test_arcgis_mb.py",
    "scripts/smoke_test_arcgis_sk.py",
    "scripts/smoke_test_arcgis_pe.py",
    "scripts/smoke_test_ckan_regina.py",
    "scripts/smoke_test_arcgis_hamilton.py",
    "scripts/smoke_test_arcgis_london.py",
    "scripts/smoke_test_arcgis_kitchener.py",
    "scripts/smoke_test_arcgis_windsor.py",
    "scripts/smoke_test_arcgis_saskatoon.py",
    "scripts/smoke_test_arcgis_victoria.py",
    "scripts/smoke_test_arcgis_surrey.py",
    "scripts/smoke_test_arcgis_ottawa.py",
    "scripts/smoke_test_arcgis_halifax.py",
    "scripts/smoke_test_arcgis_mississauga.py",
    "scripts/smoke_test_arcgis_peel.py",
    "scripts/smoke_test_arcgis_durham.py",
    "scripts/smoke_test_arcgis_waterloo_region.py",
    "scripts/smoke_test_arcgis_metro_vancouver.py",
    "scripts/smoke_test_arcgis_york.py",
    "scripts/smoke_test_arcgis_markham.py",
    "scripts/smoke_test_arcgis_newmarket.py",
    "scripts/smoke_test_arcgis_aurora.py",
    "scripts/smoke_test_arcgis_medicine_hat.py",
    "scripts/smoke_test_arcgis_grande_prairie.py",
    "scripts/smoke_test_arcgis_grande_prairie_county.py",
    "scripts/smoke_test_arcgis_st_albert.py",
    "scripts/smoke_test_arcgis_lethbridge.py",
    "scripts/smoke_test_arcgis_airdrie.py",
    "scripts/smoke_test_arcgis_strathcona_county.py",
    "scripts/smoke_test_opendatasoft_vancouver.py",
    "scripts/smoke_test_ised_corporations.py",
    "scripts/smoke_test_ised_spectrum.py",
    "scripts/smoke_test_ised_cipo.py",
    "scripts/smoke_test_statcan_census_profile.py",
    "scripts/smoke_test_statcan_census_profile_archive.py",
    "scripts/smoke_test_statcan_daily.py",
    "scripts/smoke_test_statcan_reference.py",
    "scripts/smoke_test_statcan_census_profile_2016.py",
    "scripts/smoke_test_statcan_delta.py",
    "scripts/smoke_test_statcan_indicators.py",
    "scripts/smoke_test_statcan_surveys.py",
    "scripts/smoke_test_statcan_geo.py",
    "scripts/smoke_test_nrcan_nbac.py"
)
foreach ($smokeScript in $liveSmokeScripts) {
    $null = Invoke-Checked "live smoke test: $smokeScript" "uv" @("run", "python", $smokeScript)
}

# 5 & 6. Docker build + compose up + health check (optional - skipped if
#    Docker isn't installed; not tested in the sandbox that built this).
$dockerAvailable = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerAvailable) {
    $buildOk = Invoke-Checked "docker build" "docker" @("build", "-t", "maple-data-mcp:verify", ".")

    if ($buildOk) {
        Write-Step "docker compose up + health check"
        $env:MAPLE_REQUIRE_AUTH = "0"
        docker compose up -d --build
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "docker compose up (exit code $LASTEXITCODE)"
            $failures += "docker compose up"
        } else {
            Start-Sleep -Seconds 5
            try {
                $health = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 10
                if ($health.StatusCode -eq 200) {
                    Write-Ok "health check returned 200: $($health.Content)"
                } else {
                    Write-Fail "health check returned status $($health.StatusCode)"
                    $failures += "health check"
                }
            } catch {
                Write-Fail "health check request failed: $_"
                $failures += "health check"
            }
            docker compose down | Out-Null
        }
    }
} else {
    Write-Host ""
    Write-Host "SKIP: docker not installed - build/compose steps skipped" -ForegroundColor Yellow
}

# Summary
Write-Step "SUMMARY"
if ($failures.Count -eq 0) {
    Write-Host "All checks passed." -ForegroundColor Green
    exit 0
} else {
    Write-Host "Failed: $($failures -join ', ')" -ForegroundColor Red
    exit 1
}
