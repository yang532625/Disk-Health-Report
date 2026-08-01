@echo off
REM Builds only the app binary into release\DiskHealthReport.exe
REM For the full installer: run ..\build_release.bat from repo root
cd /d "%~dp0\.."
set PYTHON=py -3
set NOPAUSE=0
if /I "%~1"=="nopause" set NOPAUSE=1
if not exist "release" mkdir "release"
echo Building app binary only...
%PYTHON% -m pip install -r requirements.txt pillow -q
if exist "scripts\generate_icon.py" %PYTHON% scripts\generate_icon.py
if exist "scripts\fetch_smartmontools.ps1" powershell -NoProfile -ExecutionPolicy Bypass -File scripts\fetch_smartmontools.ps1
%PYTHON% -m PyInstaller --clean --noconfirm --distpath release --workpath build DiskHealthReport.spec
if errorlevel 1 (
  if "%NOPAUSE%"=="0" pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync_version.ps1 >nul 2>&1
echo OK: release\DiskHealthReport.exe
echo Next: build_release.bat
if "%NOPAUSE%"=="0" pause
