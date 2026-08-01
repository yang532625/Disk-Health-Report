Disk Health Report — Build & Installer Guide
============================================

PRIMARY DISTRIBUTION
--------------------
From the repo root run:

    build_release.bat

Output (share THIS file):

    release\DiskHealthReport_Setup_x64.exe

Real Windows installer (Inno Setup 6):
  - Program Files
  - Start Menu + optional Desktop icon
  - Optional samples / startup
  - English + Spanish
  - Uninstall via Windows Settings
  - In-place upgrades (newer Setup over old install)

PROJECT LAYOUT
--------------
  app/           Python application code
  packaging/     Assets + Inno scripts
  scripts/       Build helpers
  samples/       Demo SMART dumps
  tests/         Unit tests
  release/       Built exe + Setup (output)
  docs/          This guide

CUSTOMIZE FUTURE RELEASES
-------------------------
1. version.py              → __version__ = "x.y.z"
2. packaging/inno/config.iss.inc  → branding, output name, install folder
3. packaging/inno/setup.iss       → components, tasks, messages
4. build_release.bat

OPTIONAL: app binary only
-------------------------
    scripts\build_installer.bat
  → release\DiskHealthReport.exe

REQUIREMENTS
------------
  - Python 3.10+
  - Inno Setup 6  https://jrsoftware.org/isinfo.php
  - Internet on first build (smartmontools download)

END USERS
---------
1. Run DiskHealthReport_Setup_x64.exe
2. Accept UAC (needed for S.M.A.R.T.)
3. Launch from Start Menu

Reports:   Documents\DiskHealthReport\
Runtime:   %LOCALAPPDATA%\DiskHealthReport\runtime\
