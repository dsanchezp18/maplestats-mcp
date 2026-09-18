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
    "scripts/smoke_test_ckan_toronto.py"
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
