# -*- coding: utf-8 -*-
"""Disk Health Report - entrada principal."""

import argparse
import os
import sys

# Application modules live in ./app
_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, "app")
for _p in (_APP, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from disk_service import get_app_dir, get_reports_dir, resolve_report_day_dir
from report_builder import generar_reporte
from smart_parser import parsear_smartctl


def _wait_exit():
    stdin = sys.stdin
    if stdin is not None and stdin.isatty():
        input("\nPress Enter to exit / Presione Enter para salir...")


def procesar_volcado(raw_text: str, lang: str = "es") -> None:
    """Parsea un volcado smartctl y genera el reporte PDF (modo consola)."""
    if not raw_text or "SMART" not in raw_text:
        print("[X] Invalid S.M.A.R.T. data / Datos S.M.A.R.T. invalidos.")
        sys.exit(1)

    print("[+] Processing / Procesando...")
    report = parsear_smartctl(raw_text)
    output_dir = resolve_report_day_dir(get_reports_dir())

    try:
        pdf_path = generar_reporte(report, output_dir, lang)
    except RuntimeError as e:
        print(f"[X] {e}")
        sys.exit(1)

    print(f"\n[OK] Report generated / Reporte generado!")
    print(f"      PDF:  {pdf_path}")


def main_cli_sample(sample_path: str, lang: str = "es"):
    candidates = [sample_path]
    if not os.path.isabs(sample_path):
        base = get_app_dir()
        candidates.extend([
            os.path.join(os.getcwd(), sample_path),
            os.path.join(base, sample_path),
            os.path.join(base, "samples", os.path.basename(sample_path)),
            os.path.join(base, "..", sample_path),
        ])
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(os.path.join(meipass, sample_path))
            candidates.append(os.path.join(meipass, "samples", os.path.basename(sample_path)))
    resolved = next((p for p in candidates if os.path.exists(p)), None)
    if not resolved:
        print(f"[X] Sample not found / Muestra no encontrada: {sample_path}")
        sys.exit(1)
    with open(resolved, "r", encoding="utf-8", errors="replace") as f:
        procesar_volcado(f.read(), lang)


def main():
    parser = argparse.ArgumentParser(description="Disk Health Report")
    parser.add_argument("--sample", metavar="FILE", help="Use saved smartctl dump")
    parser.add_argument("--cli", action="store_true", help="Force console mode")
    parser.add_argument("--lang", choices=["es", "en"], default="es", help="Report language")
    args = parser.parse_args()

    if args.sample:
        print("=" * 60)
        print("  DISK HEALTH REPORT - SAMPLE MODE")
        print("=" * 60)
        main_cli_sample(args.sample, args.lang)
        _wait_exit()
        return

    if args.cli:
        from disk_health_report_cli import run_cli
        run_cli()
        return

    if getattr(sys, "frozen", False):
        from runtime_bootstrap import ensure_runtime_smartctl
        ensure_runtime_smartctl()

    if sys.platform == "win32":
        from disk_service import acquire_app_mutex, ensure_elevated
        acquire_app_mutex()
        ensure_elevated()

    from app_logging import install_crash_handler
    install_crash_handler()
    from gui_app import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()
