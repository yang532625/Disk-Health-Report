#Requires -Version 5.1

# Sync version.py -> packaging/inno/version.iss.inc

$ErrorActionPreference = "Stop"

$root = Split-Path $PSScriptRoot -Parent

$versionFile = Join-Path $root "version.py"

$content = Get-Content $versionFile -Raw

if ($content -match '__version__\s*=\s*["'']([^"'']+)["'']') {

    $ver = $Matches[1]

} else {

    Write-Error "Could not parse __version__ from version.py"

}

$issInc = Join-Path $root "packaging\inno\version.iss.inc"

$issContent = @"

#define MyAppVersion "$ver"

"@

[System.IO.File]::WriteAllText($issInc, $issContent.TrimEnd() + "`r`n", [System.Text.UTF8Encoding]::new($false))

Write-Host "[OK] Version synced: $ver"

