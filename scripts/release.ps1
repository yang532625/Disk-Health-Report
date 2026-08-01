#Requires -Version 5.1
# Full release pipeline: optional version bump, build installer, smoke test.
param(
    [ValidateSet("patch", "minor", "none")]
    [string]$Bump = "none",
    [switch]$SkipSmoke,
    [switch]$SkipParser
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$env:PYTHONPATH = (Join-Path $root "app") + ";" + $root

if (-not $SkipParser) {
    Write-Host "[..] Running SMART parser regression tests..."
    Push-Location (Join-Path $root "tests")
    try {
        & py -3 test_smart_parser.py
        if ($LASTEXITCODE -ne 0) { Write-Error "SMART parser tests failed" }
    } finally {
        Pop-Location
    }
    Write-Host "[OK] Parser tests passed"
}

$versionFile = Join-Path $root "version.py"
$content = Get-Content $versionFile -Raw

if ($content -match '__version__\s*=\s*["''](\d+)\.(\d+)\.(\d+)["'']') {
    $major = [int]$Matches[1]; $minor = [int]$Matches[2]; $patch = [int]$Matches[3]
} else {
    Write-Error "Could not parse semver from version.py"
}

if ($Bump -eq "patch") {
    $patch++
    $newVer = "$major.$minor.$patch"
    $content = $content -replace '__version__\s*=\s*["''][^"'']+["'']', "__version__ = `"$newVer`""
    [System.IO.File]::WriteAllText($versionFile, $content.TrimEnd() + "`r`n", [System.Text.UTF8Encoding]::new($false))
    Write-Host "[OK] Bumped version to $newVer"
} elseif ($Bump -eq "minor") {
    $minor++; $patch = 0
    $newVer = "$major.$minor.$patch"
    $content = $content -replace '__version__\s*=\s*["''][^"'']+["'']', "__version__ = `"$newVer`""
    [System.IO.File]::WriteAllText($versionFile, $content.TrimEnd() + "`r`n", [System.Text.UTF8Encoding]::new($false))
    Write-Host "[OK] Bumped version to $newVer"
}

& cmd /c "`"$(Join-Path $root 'build_release.bat')`" nopause"
if ($LASTEXITCODE -ne 0) { Write-Error "build_release.bat failed" }

$finalContent = Get-Content $versionFile -Raw
if ($finalContent -match '__version__\s*=\s*["'']([^"'']+)["'']') { $ver = $Matches[1] }

Write-Host ""
Write-Host "============================================"
Write-Host " RELEASE $ver"
Write-Host "============================================"
Write-Host " Setup (distribute): $(Join-Path $root 'release\DiskHealthReport_Setup_x64.exe')"
Write-Host " App binary:         $(Join-Path $root 'release\DiskHealthReport.exe')"
Write-Host "============================================"

if (-not $SkipSmoke) {
    & "$PSScriptRoot\smoke_test.ps1"
}
