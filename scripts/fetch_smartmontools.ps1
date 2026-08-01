#Requires -Version 5.1
<#
.SYNOPSIS
    Downloads and extracts smartmontools binaries for bundling in the installer.
#>
param(
    [string]$DestDir = "$PSScriptRoot\..\packaging\assets\smartmontools\bin",
    [string]$Version = "7.5",
    [string]$InstallerName = "smartmontools-7.5.win32-setup.exe"
)

$ErrorActionPreference = "Stop"

$smartctlPath = Join-Path $DestDir "smartctl.exe"
if (Test-Path $smartctlPath) {
    Write-Host "[OK] smartmontools already present: $smartctlPath"
    exit 0
}

$downloadUrl = "https://downloads.sourceforge.net/project/smartmontools/smartmontools/$Version/$InstallerName"
$tempRoot = Join-Path $env:TEMP "smartmontools-fetch"
$installerPath = Join-Path $tempRoot $InstallerName
$installDir = Join-Path $tempRoot "install"

Write-Host "[+] Downloading smartmontools $Version from SourceForge..."
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

$minSize = 500000
if ((Test-Path $installerPath) -and (Get-Item $installerPath).Length -lt $minSize) {
    Remove-Item $installerPath -Force
}

if (-not (Test-Path $installerPath)) {
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & curl.exe -L -o $installerPath $downloadUrl
    } else {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $downloadUrl -OutFile $installerPath -UserAgent "Mozilla/5.0" -MaximumRedirection 10
    }
}

if (-not (Test-Path $installerPath) -or (Get-Item $installerPath).Length -lt $minSize) {
    Write-Error "Download failed or file too small. Expected >500KB from: $downloadUrl"
}

Write-Host "[+] Running silent install to temp folder..."
if (Test-Path $installDir) {
    Remove-Item $installDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $installDir | Out-Null

$installArgs = "/S /D=$installDir"
$proc = Start-Process -FilePath $installerPath -ArgumentList $installArgs -Wait -PassThru -NoNewWindow
Start-Sleep -Seconds 2

$sourceBins = @(
    (Join-Path $installDir "bin"),
    (Join-Path $installDir "smartmontools\bin"),
    "C:\Program Files\smartmontools\bin",
    "C:\Program Files (x86)\smartmontools\bin"
)

$copied = $false
foreach ($src in $sourceBins) {
    $candidate = Join-Path $src "smartctl.exe"
    if (Test-Path $candidate) {
        Write-Host "[+] Copying from $src"
        Copy-Item -Path (Join-Path $src "*") -Destination $DestDir -Recurse -Force
        $copied = $true
        break
    }
}

if (-not (Test-Path $smartctlPath)) {
    Write-Error @"
smartctl.exe not found after install.
Please manually copy smartmontools\bin\* to:
  $DestDir
Download from: https://sourceforge.net/projects/smartmontools/files/
"@
}

Write-Host "[OK] smartmontools ready at $DestDir"
Get-ChildItem $DestDir | ForEach-Object { Write-Host "     $($_.Name)" }
