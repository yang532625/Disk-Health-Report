# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

pymupdf_datas, pymupdf_binaries, pymupdf_hidden = collect_all("pymupdf")

hiddenimports = (
    collect_submodules("reportlab")
    + collect_submodules("xhtml2pdf")
    + ["customtkinter", "PIL"]
    + pymupdf_hidden
    + ["pymupdf._extra"]
)

ctk_datas = collect_data_files("customtkinter")

_assets = os.path.join("packaging", "assets")
_smartctl_bin = os.path.join(_assets, "smartmontools", "bin")
_smartctl_datas = []
if os.path.isdir(_smartctl_bin):
    for name in ("smartctl.exe", "drivedb.h"):
        path = os.path.join(_smartctl_bin, name)
        if os.path.isfile(path):
            _smartctl_datas.append((path, os.path.join("smartmontools", "bin")))

_bundled_datas = []
for rel in ("app.ico", "LICENSE_smartmontools.txt"):
    path = os.path.join(_assets, rel)
    if os.path.isfile(path):
        _bundled_datas.append((path, "bundled"))

_rufus_dir = os.path.join(_assets, "rufus")
_rufus_datas = []
if os.path.isdir(_rufus_dir):
    for name in ("rufus.exe", "LICENSE.txt"):
        path = os.path.join(_rufus_dir, name)
        if os.path.isfile(path):
            _rufus_datas.append((path, "rufus"))

_mas_dir = os.path.join(_assets, "mas")
_mas_datas = []
if os.path.isdir(_mas_dir):
    path = os.path.join(_mas_dir, "MAS_AIO.cmd")
    if os.path.isfile(path):
        _mas_datas.append((path, "mas"))

_defender_dir = os.path.join(_assets, "defender_remover")
_defender_datas = []
if os.path.isdir(_defender_dir):
    for root, _dirs, files in os.walk(_defender_dir):
        for name in files:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, _defender_dir)
            dest = os.path.join("defender_remover", os.path.dirname(rel))
            if dest.endswith(os.sep) or dest.endswith("/"):
                dest = dest.rstrip(os.sep).rstrip("/")
            _defender_datas.append((path, dest))

_ventoy_dir = os.path.join(_assets, "ventoy")
_ventoy_datas = []
if os.path.isdir(_ventoy_dir):
    for root, _dirs, files in os.walk(_ventoy_dir):
        for name in files:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, _ventoy_dir)
            dest = os.path.join("ventoy", os.path.dirname(rel))
            if dest.endswith(os.sep) or dest.endswith("/"):
                dest = dest.rstrip(os.sep).rstrip("/")
            _ventoy_datas.append((path, dest))

_sample_datas = []
if os.path.isdir("samples"):
    for name in os.listdir("samples"):
        path = os.path.join("samples", name)
        if os.path.isfile(path):
            _sample_datas.append((path, "samples"))

_icon_path = os.path.join(_assets, "app.ico")
_rthook_pymupdf = os.path.join("packaging", "hooks", "rthook_pymupdf.py")
_runtime_hooks = [_rthook_pymupdf] if os.path.isfile(_rthook_pymupdf) else []

# App package modules (flat imports resolved via pathex)
_app_hidden = [
    "runtime_bootstrap",
    "bundled_assets",
    "ventoy_runner",
    "gui_app",
    "disk_service",
    "smart_parser",
    "report_builder",
    "app_logging",
    "version",
]

a = Analysis(
    ["disk_health_report.py"],
    pathex=["app", "."],
    binaries=pymupdf_binaries,
    datas=ctk_datas + _smartctl_datas + _bundled_datas + _sample_datas + _rufus_datas + _mas_datas + _defender_datas + _ventoy_datas + pymupdf_datas,
    hiddenimports=hiddenimports + _app_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=_runtime_hooks,
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DiskHealthReport",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=["mupdf*.dll", "*pymupdf*", "*_extra*"],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon_path if os.path.exists(_icon_path) else None,
)
