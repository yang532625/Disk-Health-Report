@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM  Disk Health Report — PRIMARY RELEASE
REM  Builds app binary + Inno Setup installer into release\
REM ============================================================

cd /d "%~dp0"

set PYTHON=py -3
set NOPAUSE=0
if /I "%~1"=="nopause" set NOPAUSE=1

set ISCC=
where iscc >nul 2>&1
if not errorlevel 1 set ISCC=iscc
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"

if not defined ISCC (
    echo ERROR: Inno Setup 6 not found.
    echo Install from https://jrsoftware.org/isinfo.php
    if "%NOPAUSE%"=="0" pause
    exit /b 1
)

echo ============================================
echo  Disk Health Report - Release Installer
echo ============================================
echo.

if not exist "release" mkdir "release"

echo [1/4] Installing Python dependencies...
%PYTHON% -m pip install -r requirements.txt pillow -q
if errorlevel 1 goto :fail

echo [2/4] Preparing assets...
if exist "scripts\generate_icon.py" %PYTHON% scripts\generate_icon.py
if errorlevel 1 goto :fail
if exist "scripts\fetch_smartmontools.ps1" powershell -NoProfile -ExecutionPolicy Bypass -File scripts\fetch_smartmontools.ps1
if errorlevel 1 goto :fail
if not exist "packaging\assets\smartmontools\bin\smartctl.exe" (
    echo ERROR: smartctl.exe missing
    goto :fail
)

echo [3/4] Building DiskHealthReport.exe -^> release\ ...
%PYTHON% -m PyInstaller --clean --noconfirm --distpath release --workpath build DiskHealthReport.spec
if errorlevel 1 goto :fail
if not exist "release\DiskHealthReport.exe" (
    echo ERROR: release\DiskHealthReport.exe not found
    goto :fail
)

echo [4/4] Sync version + compile Inno Setup...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync_version.ps1
if errorlevel 1 goto :fail

del /F /Q "release\DiskHealthReport_Setup_x64.exe" 2>nul
"%ISCC%" "packaging\inno\setup.iss"
if errorlevel 1 goto :fail

for /f "delims=" %%V in ('%PYTHON% -c "from version import __version__; print(__version__)"') do set APPVER=%%V

echo.
echo ============================================
echo  RELEASE OK — v!APPVER!
echo ============================================
echo  DISTRIBUTE:
echo    release\DiskHealthReport_Setup_x64.exe
echo.
echo  App binary (packaged inside Setup):
echo    release\DiskHealthReport.exe
echo.
echo  Customize: packaging\inno\config.iss.inc
echo  Version:   version.py
echo ============================================
if "%NOPAUSE%"=="0" pause
exit /b 0

:fail
echo.
echo BUILD FAILED
if "%NOPAUSE%"=="0" pause
exit /b 1
