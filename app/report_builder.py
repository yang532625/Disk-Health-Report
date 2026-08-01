# -*- coding: utf-8 -*-
"""Generación de reporte HTML y exportación a PDF."""

import os
import re
from datetime import datetime

from xhtml2pdf import pisa

from i18n import format_date_long, format_datetime_short, format_status, get_attr_meaning, get_attr_name, t
from report_i18n import localize_identification
from smart_parser import (
    DiskReport,
    format_rotation_rate,
    generar_observaciones,
    generar_recomendacion,
    significado_nvme_attr,
)


def _parse_int_attr(value: str) -> int:
    match = re.search(r"(\d+)", str(value).replace(",", ""))
    return int(match.group(1)) if match else 0


def _status_color(status: str) -> str:
    if status in ("OK", t("status_ok", "en")):
        return "#28a745"
    if status in ("Nota", t("status_note", "en"), t("status_note", "es")):
        return "#fd7e14"
    return "#dc3545"


def _format_horas(horas: int, lang: str = "es") -> str:
    years = round(horas / 8760, 1)
    return t("hours_format", lang, hours=horas, years=years)


def _format_temperatura(report: DiskReport, lang: str = "es") -> str:
    if report.temperatura_actual is None:
        return t("not_available", lang)
    if report.es_nvme:
        return t("temp_format_nvme", lang, actual=report.temperatura_actual)
    actual = report.temperatura_actual
    promedio = report.temperatura_promedio or actual
    maxima = report.temperatura_maxima or actual
    return t("temp_format", lang, actual=actual, avg=promedio, max=maxima)


def _titulo_dispositivo(report: DiskReport, lang: str = "es") -> str:
    cap_short = report.capacidad_corta.replace("SSD", "").replace("HDD", "").strip() or report.capacidad
    if report.es_ssd:
        return t("report_title_ssd", lang, capacity=cap_short)
    return t("report_title_hdd", lang, capacity=report.capacidad_corta)


def _section_row_pair(label1: str, val1: str, label2: str, val2: str) -> str:
    return (
        f"<tr>"
        f"<td class=\"label\">{label1}</td><td class=\"value\">{val1}</td>"
        f"<td class=\"label\">{label2}</td><td class=\"value\">{val2}</td>"
        f"</tr>"
    )


def _section_row_single(label: str, val: str) -> str:
    return (
        f"<tr>"
        f"<td class=\"label\">{label}</td><td class=\"value\" colspan=\"3\">{val}</td>"
        f"</tr>"
    )


def _format_data_tb(amount: float | None, lang: str) -> str:
    if amount is None:
        return t("not_available", lang)
    return t("data_tb_approx", lang, amount=amount)


def _smart_summary(report: DiskReport, lang: str = "es") -> str:
    if report.es_nvme:
        if report.smart_passed:
            return t(
                "smart_passed_summary_nvme",
                lang,
                errors=report.errores_integridad,
                wear=report.porcentaje_uso or 0,
            )
        return t(
            "smart_failed_summary_nvme",
            lang,
            errors=report.errores_integridad,
            wear=report.porcentaje_uso or 0,
        )
    key = "smart_passed_summary" if report.smart_passed else "smart_failed_summary"
    if not report.es_nvme and report.data_quality == "full" and report.smart_passed:
        key = "smart_passed_summary_detailed"
    return t(key, lang, realloc=report.sectores_reasignados, pending=report.sectores_pendientes)


def generar_html(report: DiskReport, lang: str = "es") -> str:
    """Genera el HTML completo del reporte técnico."""
    titulo = _titulo_dispositivo(report, lang)
    fecha_larga = format_date_long(lang)
    observaciones = generar_observaciones(report, lang)
    recomendacion = generar_recomendacion(report, lang)

    status_bg = "#e8f5e9" if report.smart_passed else "#fdecea"
    status_border = "#28a745" if report.smart_passed else "#dc3545"
    status_text_color = "#28a745" if report.smart_passed else "#dc3545"
    status_label = t("result_passed", lang) if report.smart_passed else t("result_failed", lang)
    result_prefix = t("result_label", lang)

    quality_banner = ""
    if report.data_quality == "minimal":
        quality_banner = f"""
    <div class="quality-banner" style="border: 2px solid #dc3545; background-color: #fdecea; padding: 6px 10px; margin: 4px 0 6px 0; font-size: 8.5pt; color: #721c24;">
        {t('data_quality_minimal', lang)}
    </div>"""
    elif report.data_quality == "partial":
        quality_banner = f"""
    <div class="quality-banner" style="border: 1px solid #fd7e14; background-color: #fff8f0; padding: 6px 10px; margin: 4px 0 6px 0; font-size: 8.5pt; color: #856404;">
        {t('data_quality_partial', lang)}
    </div>"""

    attr_rows = ""
    for i, attr in enumerate(report.atributos_criticos):
        bg = "#f8fbff" if i % 2 == 1 else "#ffffff"
        status_display = format_status(attr.status, lang)
        color = _status_color(attr.status)
        if attr.attr_id >= 900:
            attr_label = attr.name
            meaning = significado_nvme_attr(attr, lang)
        else:
            attr_label = f"{get_attr_name(attr.attr_id, lang)} ({attr.attr_id:02d})"
            meaning = get_attr_meaning(attr.attr_id, lang)
        if attr.attr_id == 1 and report.es_seagate:
            meaning = (
                "Codificación interna de Seagate; no indica errores reales."
                if lang == "es"
                else "Seagate internal encoding; does not indicate real errors."
            )
        elif attr.attr_id == 5 and report.sectores_reasignados == 0:
            meaning = (
                "Sin sectores dañados reasignados."
                if lang == "es"
                else "No damaged reallocated sectors."
            )
        elif attr.attr_id == 183 and report.sectores_reasignados == 0:
            meaning = (
                f"Valor bajo; sin impacto ({report.sectores_reasignados} reasignados)."
                if lang == "es"
                else f"Low value; no impact ({report.sectores_reasignados} reallocated)."
            )
        elif attr.attr_id == 197 and report.sectores_pendientes == 0:
            meaning = (
                "Sin sectores pendientes de reasignación."
                if lang == "es"
                else "No sectors pending reallocation."
            )
        elif attr.attr_id == 198:
            meaning = (
                "Sin sectores no corregibles."
                if lang == "es"
                else "No uncorrectable sectors."
            )
        elif attr.attr_id == 187 and _parse_int_attr(attr.raw_value) == 0:
            meaning = (
                "Sin errores incorregibles reportados."
                if lang == "es"
                else "No reported uncorrectable errors."
            )
        elif attr.attr_id == 199 and _parse_int_attr(attr.raw_value) == 0:
            meaning = (
                "Sin errores de cable/interfaz SATA."
                if lang == "es"
                else "No SATA cable/interface CRC errors."
            )
        attr_rows += f"""
        <tr style="background-color: {bg};">
            <td class="attr-cell">{attr_label}</td>
            <td class="attr-cell">{attr.raw_value}</td>
            <td class="attr-cell" style="color: {color}; font-weight: bold;">{status_display}</td>
            <td class="attr-cell attr-meaning">{meaning}</td>
        </tr>"""

    ident = localize_identification(report, lang)
    ident_rows = "\n".join(
        [
            _section_row_pair(
                t("label_model", lang),
                ident["modelo"],
                t("label_interface", lang),
                ident["interfaz"],
            ),
            _section_row_pair(
                t("label_capacity", lang),
                ident["capacidad"],
                t("label_serial", lang),
                ident["serial"],
            ),
            _section_row_pair(
                t("label_speed", lang),
                ident["velocidad_interfaz"],
                t("label_rotation_rate", lang),
                format_rotation_rate(report, lang),
            ),
            _section_row_pair(
                t("label_firmware", lang),
                ident["firmware"],
                t("label_form_factor", lang),
                ident["factor_forma"],
            ),
            _section_row_single(t("label_sectors", lang), ident["sectores"]),
        ]
    )

    usage_rows = "\n".join(
        [
            _section_row_pair(
                t("label_power_hours", lang),
                _format_horas(report.horas, lang),
                t("label_power_cycles", lang),
                f"{report.ciclos_encendido:,}",
            ),
            _section_row_pair(
                t("label_data_written", lang),
                _format_data_tb(report.datos_escritos_tb, lang),
                t("label_data_read", lang),
                _format_data_tb(report.datos_leidos_tb, lang),
            ),
            _section_row_single(
                t("label_temperature", lang),
                _format_temperatura(report, lang),
            ),
        ]
    )

    html = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="UTF-8">
    <title>{titulo}</title>
    <style>
        @page {{
            size: A4;
            margin: 1.4cm 1.4cm;
        }}
        body {{
            font-family: Helvetica, Arial, sans-serif;
            color: #2c3e50;
            font-size: 9.5pt;
            line-height: 1.35;
        }}
        h1 {{
            color: #0056b3;
            font-size: 16pt;
            margin: 0 0 2px 0;
            font-weight: bold;
        }}
        .subtitle {{
            color: #64748b;
            font-size: 9pt;
            margin-bottom: 10px;
        }}
        h2 {{
            color: #0056b3;
            font-size: 11pt;
            font-weight: bold;
            margin: 10px 0 5px 0;
            border-bottom: none;
        }}
        .section-table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 4px;
            font-size: 9pt;
            table-layout: fixed;
            page-break-inside: avoid;
        }}
        .section-table td {{
            padding: 4px 7px;
            border-bottom: 1px solid #e2e8f0;
            vertical-align: top;
        }}
        .section-table .label {{
            background-color: #f1f5f9;
            color: #475569;
            font-weight: bold;
            width: 22%;
        }}
        .section-table .value {{
            background-color: #ffffff;
            width: 28%;
            word-wrap: break-word;
            word-break: break-word;
        }}
        .status-box {{
            border: 2px solid {status_border};
            background-color: {status_bg};
            padding: 8px 12px;
            margin: 4px 0 6px 0;
            text-align: center;
            page-break-inside: avoid;
        }}
        .status-box .result {{
            color: {status_text_color};
            font-size: 11pt;
            font-weight: bold;
        }}
        .status-desc {{
            font-size: 9pt;
            color: #333333;
            margin-top: 4px;
            margin-bottom: 4px;
        }}
        .attr-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 8.5pt;
            margin-bottom: 4px;
            table-layout: fixed;
            page-break-inside: avoid;
        }}
        .attr-table th {{
            background-color: #0056b3;
            color: #ffffff;
            padding: 5px 7px;
            text-align: left;
            font-weight: bold;
        }}
        .attr-cell {{
            padding: 4px 7px;
            border-bottom: 1px solid #e2e8f0;
            vertical-align: top;
        }}
        .attr-meaning {{
            font-size: 8pt;
        }}
        .observaciones {{
            font-size: 9pt;
            text-align: justify;
            color: #333333;
            margin-bottom: 4px;
            line-height: 1.35;
        }}
        .recomendacion-box {{
            border: 2px solid #a8cce4;
            background-color: #f4f8fb;
            padding: 8px 10px;
            font-size: 9pt;
            color: #222222;
            margin-bottom: 8px;
            line-height: 1.35;
            page-break-inside: avoid;
        }}
        .tested-by {{
            margin-top: 10px;
            padding: 8px 12px;
            text-align: center;
            font-size: 11pt;
            font-weight: bold;
            letter-spacing: 0.5px;
            color: #0056b3;
            background-color: #eef4fb;
            border: 1px solid #a8cce4;
            page-break-inside: avoid;
        }}
        .footer {{
            margin-top: 8px;
            font-size: 8pt;
            color: #64748b;
            border-top: 1px solid #e2e8f0;
            padding-top: 6px;
            text-align: center;
        }}
        .quality-banner {{
            page-break-inside: avoid;
        }}
        .block-smart {{
            page-break-inside: avoid;
        }}
    </style>
</head>
<body>

    <h1>{titulo}</h1>
    <div class="subtitle">{t('report_subtitle', lang, date=fecha_larga)}</div>

    <h2>{t('section_identification', lang)}</h2>
    <table class="section-table">
        {ident_rows}
    </table>

    <div class="block-smart">
    <h2>{t('section_smart_status', lang)}</h2>
    {quality_banner}
    <div class="status-box">
        <div class="result">{result_prefix} {status_label}</div>
    </div>
    <div class="status-desc">{_smart_summary(report, lang)}</div>

    <h2>{t('section_critical_attrs', lang)}</h2>
    <table class="attr-table">
        <thead>
            <tr>
                <th>{t('col_attribute', lang)}</th>
                <th>{t('col_value', lang)}</th>
                <th>{t('col_status', lang)}</th>
                <th>{t('col_meaning', lang)}</th>
            </tr>
        </thead>
        <tbody>
            {attr_rows}
        </tbody>
    </table>
    </div>

    <h2>{t('section_usage', lang)}</h2>
    <table class="section-table">
        {usage_rows}
    </table>

    <h2>{t('section_observations', lang)}</h2>
    <div class="observaciones">{observaciones}</div>

    <h2>{t('section_recommendation', lang)}</h2>
    <div class="recomendacion-box">{recomendacion}</div>

    <div class="tested-by">{t('tested_by', lang)}</div>

    <div class="footer">
        {t('footer', lang, version=report.smartctl_version, datetime=format_datetime_short())}
    </div>

</body>
</html>"""
    return html


def exportar_pdf(html: str, output_path: str) -> bool:
    """Convierte HTML a PDF usando xhtml2pdf."""
    with open(output_path, "wb") as pdf_file:
        result = pisa.CreatePDF(html.encode("utf-8"), dest=pdf_file, encoding="utf-8")
    return not result.err


def build_report_paths(report: DiskReport, output_dir: str, lang: str = "es") -> tuple[str, str]:
    """Genera rutas de salida PDF/HTML sin escribir archivos."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    serial_safe = re.sub(r"[^\w\-]", "_", report.serial) if report.serial else "disk"
    prefix = t("report_filename_prefix", lang)
    base_name = f"{prefix}_{serial_safe}_{timestamp}"
    html_path = os.path.join(output_dir, f"{base_name}.html")
    pdf_path = os.path.join(output_dir, f"{base_name}.pdf")
    return pdf_path, html_path


def generar_reporte(report: DiskReport, output_dir: str = ".", lang: str = "es") -> tuple[str, str]:
    """
    Genera HTML y PDF del reporte.
    Retorna (ruta_pdf, ruta_html).
    """
    html = generar_html(report, lang)
    pdf_path, html_path = build_report_paths(report, output_dir, lang)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    if not exportar_pdf(html, pdf_path):
        raise RuntimeError(t("pdf_error", lang))

    return pdf_path, html_path
