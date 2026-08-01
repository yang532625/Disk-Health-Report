@echo off
REM Alias → primary release pipeline
cd /d "%~dp0\.."
call build_release.bat %*
