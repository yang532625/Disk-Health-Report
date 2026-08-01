#Requires -Version 5.1
# Smoke test after build - verifies release artifacts + version sync.

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

$appExe = Join-Path $root "release\DiskHealthReport.exe"
$setupExe = Join-Path $root "release\DiskHealthReport_Setup_x64.exe"
$versionPy = Join-Path $root "version.py"
$issInc = Join-Path $root "packaging\inno\version.iss.inc"
$configIss = Join-Path $root "packaging\inno\config.iss.inc"
$setupIss = Join-Path $root "packaging\inno\setup.iss"
$importPy = Join-Path $env:TEMP "dhr_smoke_import.py"

if (-not (Test-Path $appExe)) {
    Write-Error "release\DiskHealthReport.exe not found. Run build_release.bat first."
}
Write-Host ("[OK] App binary: {0} ({1} MB)" -f $appExe, [math]::Round((Get-Item $appExe).Length / 1MB, 1))

if (-not (Test-Path $setupExe)) {
    Write-Error "release\DiskHealthReport_Setup_x64.exe not found. Run build_release.bat."
}
Write-Host ("[OK] Installer:  {0} ({1} MB)" -f $setupExe, [math]::Round((Get-Item $setupExe).Length / 1MB, 1))

$verInfo = (Get-Item $setupExe).VersionInfo
Write-Host ("[OK] Setup ProductName: {0}" -f $verInfo.ProductName)
Write-Host ("[OK] Setup FileVersion:  {0}" -f $verInfo.FileVersion)

$verLine = (Get-Content $versionPy | Where-Object { $_ -match '__version__\s*=' } | Select-Object -First 1)
if (-not $verLine) { Write-Error "Could not parse version.py" }
if ($verLine -notmatch '([0-9]+\.[0-9]+\.[0-9]+)') {
    Write-Error "Could not extract version from version.py"
}
$ver = $Matches[1]
$iss = Get-Content $issInc -Raw
if ($iss -notmatch [regex]::Escape($ver)) {
    Write-Error ("version.iss.inc out of sync with version.py ({0})" -f $ver)
}
Write-Host ("[OK] Version synced: {0}" -f $ver)

foreach ($f in @($configIss, $setupIss)) {
    if (-not (Test-Path $f)) { Write-Error ("Missing {0}" -f $f) }
}
$setupText = Get-Content $setupIss -Raw
if ($setupText -notmatch 'MyAppBinary') {
    Write-Warning "setup.iss may not point at release binary - check Source paths"
}
if ($setupText -notmatch 'AppId=') {
    Write-Error "setup.iss missing AppId"
}
Write-Host "[OK] Inno scripts present"

$env:PYTHONPATH = (Join-Path $root "app") + ";" + $root
Set-Content -Path $importPy -Encoding ASCII -Value @(
    "import gui_app, disk_service, smart_parser"
    "from version import __version__"
    "print('imports_ok', __version__)"
)
& py -3 $importPy
$importEc = $LASTEXITCODE
Remove-Item $importPy -ErrorAction SilentlyContinue
if ($importEc -ne 0) { Write-Error "Python imports failed after reorg" }
Write-Host "[OK] Python package imports"

Write-Host ""
Write-Host "SMOKE PASSED - distribute release\DiskHealthReport_Setup_x64.exe"
