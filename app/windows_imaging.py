# -*- coding: utf-8 -*-
"""Captura, ensamblado ISO Windows y utilidades ADK/WinPE."""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable, Optional

import disk_image
import disk_ops
import win_image_job

ProgressCB = Callable[[str, Optional[float]], None] | None

_ADK_SEARCH = (
    os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 "Windows Kits", "10", "Assessment and Deployment Kit"),
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                 "Windows Kits", "10", "Assessment and Deployment Kit"),
)


def _report(cb: ProgressCB, stage: str, fraction: float | None = None) -> None:
    if cb:
        try:
            cb(stage, fraction)
        except Exception:
            pass


def detect_adk() -> dict[str, str] | None:
    """Devuelve rutas ADK si están instaladas."""
    if sys.platform != "win32":
        return None
    for base in _ADK_SEARCH:
        if not os.path.isdir(base):
            continue
        oscdimg = None
        for arch in ("x64", "amd64", "arm64"):
            candidate = os.path.join(
                base, "Deployment Tools", arch, "Oscdimg", "oscdimg.exe",
            )
            if os.path.isfile(candidate):
                oscdimg = candidate
                break
        if not oscdimg:
            for root, _dirs, files in os.walk(os.path.join(base, "Deployment Tools")):
                if "oscdimg.exe" in files:
                    oscdimg = os.path.join(root, "oscdimg.exe")
                    break
        copype = os.path.join(base, "Deployment Tools", "Copype.cmd")
        make_media = os.path.join(base, "Deployment Tools", "amd64", "MakeWinPEMedia.cmd")
        if not os.path.isfile(make_media):
            alt = os.path.join(base, "Deployment Tools", "x64", "MakeWinPEMedia.cmd")
            if os.path.isfile(alt):
                make_media = alt
        if oscdimg:
            return {
                "base": base,
                "oscdimg": oscdimg,
                "copype": copype if os.path.isfile(copype) else "",
                "make_winpe_media": make_media if os.path.isfile(make_media) else "",
            }
    return None


def estimate_wim_size(used_bytes: int) -> int:
    """Estimación conservadora del tamaño del WIM capturado."""
    if used_bytes <= 0:
        return 0
    return int(used_bytes * 0.75)


def generate_sysprep_script(dest_dir: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, "RunSysprep.cmd")
    content = (
        "@echo off\r\n"
        "echo Disk Health Report - Sysprep generalize\r\n"
        "echo Cierra todas las aplicaciones antes de continuar.\r\n"
        "pause\r\n"
        r"%WINDIR%\System32\Sysprep\sysprep.exe /oobe /generalize /shutdown\r\n"
    )
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(content)
    return path


def generate_capture_script(
    wim_path: str,
    source_drive: str = "C:",
    dest_dir: str | None = None,
) -> str:
    """Script DISM para ejecutar en WinPE."""
    if dest_dir is None:
        dest_dir = os.path.dirname(wim_path)
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, "Capture.cmd")
    src = source_drive.rstrip("\\")
    if not src.endswith(":"):
        src += ":"
    content = (
        "@echo off\r\n"
        "echo Disk Health Report - DISM Capture-Image\r\n"
        f"if not exist \"{dest_dir}\" mkdir \"{dest_dir}\"\r\n"
        "dism /Capture-Image "
        f"/CaptureDir:{src}\\ "
        f"/ImageFile:\"{wim_path}\" "
        "/Name:\"DiskHealthCustom\" "
        "/Compress:max "
        "/CheckIntegrity /Verify\r\n"
        "echo.\r\n"
        "echo Captura finalizada. Reinicia y vuelve a Windows.\r\n"
        "pause\r\n"
    )
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(content)
    return path


def write_capture_bundle(usb_root: str, wim_output: str) -> dict[str, str]:
    """Copia scripts de captura a la raíz del USB WinPE."""
    scripts: dict[str, str] = {}
    scripts["sysprep"] = generate_sysprep_script(usb_root)
    cap_dir = os.path.join(usb_root, "DiskHealthCapture")
    scripts["capture"] = generate_capture_script(wim_output, dest_dir=cap_dir)
    readme = os.path.join(usb_root, "LEEME_CAPTURA.txt")
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(
            "Disk Health Report - Captura de imagen\n\n"
            "1. En Windows: ejecute RunSysprep.cmd como administrador (o use el botón en la app).\n"
            "2. Arranque desde este USB (WinPE).\n"
            f"3. En WinPE ejecute: DiskHealthCapture\\Capture.cmd\n"
            f"4. El WIM se guardará en: {wim_output}\n"
            "5. Vuelva a Windows y use 'Ensamblar ISO' en la app.\n"
        )
    scripts["readme"] = readme
    return scripts


def create_winpe_usb(
    disk_number: int,
    adk: dict[str, str],
    progress_cb: ProgressCB = None,
) -> tuple[bool, str]:
    """Formatea USB y escribe WinPE (requiere ADK + copype)."""
    if sys.platform != "win32":
        return False, "not_windows"
    pd = disk_ops._get_disk_fresh(disk_number)
    if pd is None:
        return False, "no_disk"
    if pd["is_system"] or pd["is_boot"]:
        return False, "system_disk"

    copype = adk.get("copype") or ""
    make_media = adk.get("make_winpe_media") or ""
    if not copype or not make_media:
        return False, "adk_incomplete"

    _report(progress_cb, "winpe_preparing", 0.05)
    ok, info = disk_ops.format_disk(
        disk_number, "MBR", "FAT32", "WINPE_DH",
        quick=True,
    )
    if not ok:
        return False, info
    letter = str(info).strip().rstrip(":")
    if not letter:
        return False, "no_letter"
    usb_root = f"{letter}:\\"

    work = tempfile.mkdtemp(prefix="dh_winpe_")
    try:
        _report(progress_cb, "winpe_copype", 0.2)
        rc = subprocess.run(
            ["cmd", "/c", copype, "amd64", work],
            capture_output=True,
            text=True,
            timeout=600,
            **disk_ops._hidden_kwargs(),
        )
        if rc.returncode != 0:
            return False, "copype_failed"

        _report(progress_cb, "winpe_media", 0.5)
        rc = subprocess.run(
            ["cmd", "/c", make_media, "/UEFI", usb_root.rstrip("\\"), work],
            capture_output=True,
            text=True,
            timeout=3600,
            **disk_ops._hidden_kwargs(),
        )
        if rc.returncode != 0:
            return False, "make_winpe_failed"

        wim_out = os.path.join(usb_root, "DiskHealthCapture", "install.wim")
        write_capture_bundle(usb_root, wim_out)
        _report(progress_cb, "winpe_done", 1.0)
        return True, letter
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _minimal_autounattend(lang: str = "es-ES") -> str:
    return f'''<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
  <settings pass="windowsPE">
    <component name="Microsoft-Windows-International-Core-WinPE"
               processorArchitecture="amd64"
               publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <SetupUILanguage><UILanguage>{lang}</UILanguage></SetupUILanguage>
      <InputLocale>{lang}</InputLocale>
      <SystemLocale>{lang}</SystemLocale>
      <UILanguage>{lang}</UILanguage>
      <UserLocale>{lang}</UserLocale>
    </component>
  </settings>
  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-Shell-Setup"
               processorArchitecture="amd64"
               publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <OOBE><HideEULAPage>true</HideEULAPage></OOBE>
    </component>
  </settings>
</unattend>
'''


def _write_oem_scripts(staging: str, job: dict[str, Any]) -> None:
    """Scripts post-instalación desde inventario (winget import)."""
    oem = os.path.join(staging, "sources", "$OEM$", "$$", "Setup", "Scripts")
    os.makedirs(oem, exist_ok=True)
    winget_path = (job.get("inventory") or {}).get("winget_export")
    setup = os.path.join(oem, "SetupComplete.cmd")
    lines = ["@echo off", "REM Disk Health Report post-install"]
    if winget_path and os.path.isfile(winget_path):
        dest = os.path.join(oem, "winget_packages.json")
        shutil.copy2(winget_path, dest)
        lines.append(
            'where winget >nul 2>&1 && winget import -i "%~dp0winget_packages.json" '
            "--accept-package-agreements --accept-source-agreements"
        )
    with open(setup, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write("\r\n".join(lines) + "\r\n")


def inject_wim_into_iso(
    base_iso: str,
    custom_wim: str,
    output_iso: str,
    job: dict[str, Any] | None = None,
    progress_cb: ProgressCB = None,
) -> tuple[bool, str]:
    """Monta ISO base, reemplaza install.wim y genera ISO con oscdimg."""
    if sys.platform != "win32":
        return False, "not_windows"
    if not os.path.isfile(base_iso):
        return False, "iso_missing"
    if not os.path.isfile(custom_wim):
        return False, "wim_missing"

    adk = detect_adk()
    if not adk or not adk.get("oscdimg"):
        return False, "adk_missing"

    staging = tempfile.mkdtemp(prefix="dh_iso_staging_")
    try:
        _report(progress_cb, "iso_mounting", 0.05)
        letter = disk_image.mount_iso(base_iso)
        if not letter:
            return False, "iso_mount_failed"
        iso_root = f"{letter}:\\"
        try:
            _report(progress_cb, "iso_copying", 0.15)
            rc = subprocess.run(
                ["robocopy", iso_root, staging, "/E", "/NJH", "/NJS",
                 "/NFL", "/NDL", "/NP", "/R:1", "/W:1"],
                capture_output=True,
                text=True,
                timeout=3600 * 4,
                **disk_ops._hidden_kwargs(),
            )
            if rc.returncode >= 8:
                return False, "iso_copy_failed"
        finally:
            disk_image.dismount_iso(base_iso)

        sources = os.path.join(staging, "sources")
        os.makedirs(sources, exist_ok=True)
        dest_wim = os.path.join(sources, "install.wim")
        for name in ("install.wim", "install.esd"):
            p = os.path.join(sources, name)
            if os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        for pattern in ("install*.swm",):
            for p in glob.glob(os.path.join(sources, pattern)):
                try:
                    os.remove(p)
                except OSError:
                    pass

        _report(progress_cb, "iso_injecting_wim", 0.4)
        shutil.copy2(custom_wim, dest_wim)

        _report(progress_cb, "iso_unattend", 0.55)
        unattend = _minimal_autounattend()
        with open(os.path.join(staging, "autounattend.xml"), "w", encoding="utf-8") as fh:
            fh.write(unattend)
        if job:
            _write_oem_scripts(staging, job)

        os.makedirs(os.path.dirname(output_iso), exist_ok=True)
        _report(progress_cb, "iso_building", 0.7)
        oscdimg = adk["oscdimg"]
        etfs = os.path.join(os.path.dirname(oscdimg), "etfsboot.com")
        if os.path.isfile(etfs):
            boot_arg = f"-bootdata:2#p0,e,b{etfs}"
        else:
            boot_arg = "-bootdata:2#p0,e,b"
        cmd = [oscdimg, "-m", "-o", "-u2", "-udfver102", boot_arg, staging, output_iso]

        rc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600 * 4,
            **disk_ops._hidden_kwargs(),
        )
        if rc.returncode != 0 or not os.path.isfile(output_iso):
            return False, "oscdimg_failed"

        _report(progress_cb, "iso_done", 1.0)
        return True, output_iso
    finally:
        shutil.rmtree(staging, ignore_errors=True)
