@echo off
REM Legacy alias → app binary only
cd /d "%~dp0\.."
call scripts\build_installer.bat %*
