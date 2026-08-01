# Disk Health Report

Windows app for S.M.A.R.T. disk health reports, imaging tools, and disk utilities.

## Folder layout

```
DIsk Health/
  app/                 Application Python modules
  packaging/           Build assets + Inno Setup scripts
    assets/            Icons, smartctl, bundled tools
    inno/              Installer scripts (customize here)
  scripts/             Build helpers + secondary bats
  samples/             Offline SMART sample dumps
  tests/               Unit tests
  docs/                Build documentation
  release/             OUTPUT — Setup.exe + app binary
  disk_health_report.py   Entry point
  version.py              Release version
  build_release.bat       Primary build (app + installer)
  DiskHealthReport.spec   PyInstaller spec
  requirements.txt
```

## Build the installer

```bat
build_release.bat
```

Distribute:

```
release\DiskHealthReport_Setup_x64.exe
```

That is a real Inno Setup installer (Program Files, Start Menu, uninstaller, EN/ES, in-place upgrades).

## Customize

| What | File |
|------|------|
| Version | `version.py` |
| Name / paths / URLs | `packaging\inno\config.iss.inc` |
| Wizard / components | `packaging\inno\setup.iss` |

See `docs\BUILD.md` for details.
