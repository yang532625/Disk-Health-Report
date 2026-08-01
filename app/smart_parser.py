# -*- coding: utf-8 -*-
"""Parseo completo de la salida de smartctl -a."""

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from i18n import t

DataQuality = Literal["full", "partial", "minimal"]


CRITICAL_ATTR_IDS = [1, 3, 4, 5, 9, 10, 183, 184, 187, 188, 190, 193, 194, 197, 198, 199, 241, 242]

# Atributos de salud en tabla crítica (orden referencia CrystalDiskInfo / GSmartControl)
HEALTH_ATTR_IDS = [5, 197, 198, 187, 199, 10, 188, 183, 184]

# IDs virtuales >= 900 para atributos NVMe en el reporte PDF
NVME_ATTR_CRITICAL_WARNING = 901
NVME_ATTR_TEMPERATURE = 902
NVME_ATTR_AVAILABLE_SPARE = 903
NVME_ATTR_PERCENTAGE_USED = 904
NVME_ATTR_MEDIA_ERRORS = 905
NVME_ATTR_UNSAFE_SHUTDOWNS = 906
NVME_ATTR_ERROR_LOG = 907

ATTR_NAMES = {
    1: "Raw Read Error Rate",
    3: "Spin-Up Time",
    4: "Start-Stop Count",
    5: "Reallocated Sector Count",
    9: "Power-On Hours",
    10: "Spin Retry Count",
    183: "Runtime Bad Block",
    184: "End-to-End Error",
    188: "Command Timeout",
    190: "Airflow Temperature",
    193: "Load Cycle Count",
    194: "Temperature",
    197: "Current Pending Sector",
    198: "Offline Uncorrectable",
    187: "Reported Uncorrectable",
    199: "UDMA CRC Error Count",
    241: "Total LBAs Written",
    242: "Total LBAs Read",
}

ATTR_MEANINGS = {
    1: "Tasa de errores de lectura en bruto.",
    3: "Tiempo de arranque del plato.",
    4: "Ciclos de encendido/apagado mecánico.",
    5: "Sectores dañados reasignados a reserva.",
    9: "Horas totales de funcionamiento.",
    10: "Reintentos de arranque del motor.",
    183: "Bloques defectuosos detectados en tiempo de ejecución.",
    184: "Errores de extremo a extremo en la ruta de datos.",
    188: "Comandos abortados por tiempo de espera.",
    190: "Temperatura del flujo de aire interno.",
    193: "Ciclos de carga del cabezal (park/unpark).",
    194: "Temperatura interna del disco.",
    197: "Sectores pendientes de reasignación.",
    198: "Sectores no corregibles fuera de línea.",
    187: "Errores incorregibles reportados al host.",
    199: "Errores CRC en la interfaz SATA/cable.",
    241: "Total de sectores escritos acumulados.",
    242: "Total de sectores leídos acumulados.",
}


@dataclass
class SmartAttribute:
    attr_id: int
    name: str
    raw_value: str
    status: str  # OK, Nota, Alerta
    meaning: str


@dataclass
class DiskReport:
    modelo: str = "Desconocido"
    serial: str = "Desconocido"
    firmware: str = "Desconocido"
    interfaz: str = "Desconocida"
    capacidad: str = "Desconocida"
    capacidad_corta: str = "HDD"
    factor_forma: str = "No especificado"
    rotacion: str = "SSD"
    rotation_rate_raw: str = ""
    velocidad_interfaz: str = "No especificada"
    sectores: str = "No especificado"
    es_seagate: bool = False
    es_ssd: bool = False
    smart_passed: bool = True
    smart_status_text: str = "PASSED"
    sectores_reasignados: int = 0
    sectores_pendientes: int = 0
    horas: int = 0
    ciclos_encendido: int = 0
    datos_escritos_tb: Optional[float] = None
    datos_leidos_tb: Optional[float] = None
    temperatura_actual: Optional[int] = None
    temperatura_promedio: Optional[int] = None
    temperatura_maxima: Optional[int] = None
    atributos_criticos: list = field(default_factory=list)
    smartctl_version: str = "smartmontools"
    tiene_test_largo_reciente: bool = False
    linea_producto: str = ""
    es_nvme: bool = False
    porcentaje_uso: Optional[int] = None
    spare_disponible: Optional[int] = None
    errores_integridad: int = 0
    apagados_inseguros: int = 0
    spare_umbral: Optional[int] = None
    data_quality: DataQuality = "partial"
    ciclos_es_start_stop: bool = False
    sector_size_bytes: int = 512


def _search(pattern: str, text: str, group: int = 1, default: str = "") -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(group).strip() if match else default


def _parse_int(value: str) -> int:
    if not value:
        return 0
    match = re.search(r"^(\d+)", str(value).replace(",", ""))
    return int(match.group(1)) if match else 0


def _parse_command_timeout(raw: str) -> tuple[int, int, int]:
    """Desempaqueta SMART 188 (Seagate): total / tardíos / fallidos (16 bits c/u)."""
    v = _parse_int(raw)
    if "/" in str(raw):
        parts = str(raw).split("/")
        if len(parts) >= 3:
            return _parse_int(parts[0]), _parse_int(parts[1]), _parse_int(parts[2])
    total = v & 0xFFFF
    late = (v >> 16) & 0xFFFF
    failed = (v >> 32) & 0xFFFF
    return total, late, failed


def _format_command_timeout(raw: str) -> str:
    total, late, failed = _parse_command_timeout(raw)
    return f"{total}/{late}/{failed}"


def _lba_to_tb(raw: str, sector_size: int = 512) -> Optional[float]:
    val = _parse_int(raw)
    if val <= 0:
        return None
    bytes_total = val * sector_size
    return round(bytes_total / (1024 ** 4), 1)


def _parse_smart_attributes(raw_text: str) -> dict:
    """Extrae atributos SMART de la tabla de smartctl."""
    attrs = {}
    in_table = False
    for linea in raw_text.split("\n"):
        if "ID# ATTRIBUTE_NAME" in linea:
            in_table = True
            continue
        if in_table:
            if not linea.strip() or linea.startswith("-"):
                continue
            if not re.match(r"^\s*\d+\s+\S", linea):
                if attrs:
                    break
                continue
            partes = linea.split()
            if len(partes) < 10:
                continue
            try:
                attr_id = int(partes[0])
            except ValueError:
                continue
            raw_val = " ".join(partes[9:]) if len(partes) > 9 else "0"
            attrs[attr_id] = {
                "name": partes[1].replace("_", " "),
                "raw": raw_val,
                "value": partes[3] if len(partes) > 3 else "0",
            }
    return attrs


def _evaluar_estado(attr_id: int, raw: str, es_seagate: bool, reasignados: int) -> str:
    raw_int = _parse_int(raw)

    if attr_id == 1 and es_seagate:
        return "Nota"
    if attr_id == 5:
        if raw_int == 0:
            return "OK"
        if raw_int <= 10:
            return "Nota"
        return "Alerta"
    if attr_id == 197:
        return "Alerta" if raw_int > 0 else "OK"
    if attr_id == 198:
        return "Alerta" if raw_int > 0 else "OK"
    if attr_id in (187, 199):
        return "Alerta" if raw_int > 0 else "OK"
    if attr_id == 183:
        if raw_int == 0:
            return "OK"
        if reasignados == 0 and raw_int < 100:
            return "Nota"
        return "Alerta"
    if attr_id in (190, 194):
        temp = raw_int
        if temp > 100000:
            temp = temp // 1000
        if temp < 45:
            return "OK"
        if temp <= 55:
            return "Nota"
        return "Alerta"
    if attr_id == 10:
        return "Alerta" if raw_int > 0 else "OK"
    if attr_id == 188:
        total, late, failed = _parse_command_timeout(raw)
        if total == 0 and late == 0 and failed == 0:
            return "OK"
        # Histórico de interfaz/cable; no marca el disco como fallido por sí solo.
        return "Nota"
    if attr_id == 184:
        return "Alerta" if raw_int > 0 else "OK"

    # Atributos informativos de uso: siempre OK si presentes
    if attr_id in (3, 4, 9, 193, 241, 242):
        return "OK"

    return "OK" if raw_int == 0 else "Nota"


def _meaning_for_attr(attr_id: int, raw: str, es_seagate: bool, reasignados: int) -> str:
    base = ATTR_MEANINGS.get(attr_id, "Atributo de monitoreo S.M.A.R.T.")
    if attr_id == 1 and es_seagate:
        return "Codificación interna de Seagate; no indica errores reales."
    if attr_id == 5 and _parse_int(raw) == 0:
        return "Sin sectores dañados reasignados."
    if attr_id == 183 and reasignados == 0 and _parse_int(raw) > 0:
        return f"Valor bajo; sin impacto ({reasignados} reasignados)."
    if attr_id == 197 and _parse_int(raw) == 0:
        return "Sin sectores pendientes de reasignación."
    if attr_id == 198 and _parse_int(raw) == 0:
        return "Sin sectores no corregibles."
    if attr_id == 187 and _parse_int(raw) == 0:
        return "Sin errores incorregibles reportados."
    if attr_id == 199 and _parse_int(raw) == 0:
        return "Sin errores de cable/interfaz SATA."
    if attr_id == 188:
        total, late, failed = _parse_command_timeout(raw)
        if total == 0 and late == 0 and failed == 0:
            return "Sin timeouts de comando (0/0/0)."
        return (
            f"Histórico de timeouts (total/tardíos/fallidos): {total}/{late}/{failed}. "
            "Suele relacionarse con cable, USB o controlador; no implica fallo del disco por sí solo."
        )
    return base


def _parse_link_speed_sata(raw_text: str, interfaz: str) -> str:
    """Velocidad de enlace SATA real (prioriza la velocidad 'current')."""
    sata_line = _search(r"SATA Version is:\s+(.+)", raw_text) or interfaz
    m = re.search(r"current:\s*([\d.]+\s*Gb/s)", sata_line, re.I)
    if m:
        return m.group(1).replace(" ", "")
    speeds = re.findall(r"([\d.]+)\s*Gb/s", sata_line, re.I)
    if speeds:
        return f"{max(float(s) for s in speeds):g} Gb/s"
    return "No especificada"


def _parse_link_speed_nvme(raw_text: str) -> str:
    """Velocidad/ancho de enlace PCIe para NVMe, si smartctl lo reporta."""
    m = re.search(r"PCIe\s+(?:Gen)?\s*([\d.]+)\s*GT/s", raw_text, re.I)
    width = re.search(r"x(\d+)\s*(?:lanes|link)", raw_text, re.I)
    if m:
        speed = f"PCIe {m.group(1)} GT/s"
        if width:
            speed += f" x{width.group(1)}"
        return speed
    return "No especificada"


def _extract_spindle_rpm(text: str) -> Optional[int]:
    """Extrae RPM del spindle desde el texto de Rotation Rate de smartctl."""
    if not text:
        return None
    low = text.lower().strip()
    if "solid state" in low or low == "ssd":
        return None
    match = re.search(r"(\d+)\s*rpm", low)
    if match:
        rpm = int(match.group(1))
        return rpm if rpm > 0 else None
    match = re.match(r"^\s*(\d+)\s*$", text.strip())
    if match:
        rpm = int(match.group(1))
        return rpm if rpm >= 1000 else None
    return None


def format_rotation_rate(report: DiskReport, lang: str = "es") -> str:
    """Texto de Rotation Rate (RPM) para el reporte PDF."""
    raw = (report.rotation_rate_raw or report.rotacion or "").strip()
    raw_low = raw.lower()

    if report.es_nvme or report.es_ssd:
        if "solid state" in raw_low:
            return t("rotation_rate_solid_state", lang)
        return t("rotation_rate_ssd_na", lang)

    rpm = _extract_spindle_rpm(raw) or _extract_spindle_rpm(report.rotacion)
    if rpm:
        return f"{rpm} RPM"
    if raw and "ssd" not in raw_low and "solid state" not in raw_low:
        if re.search(r"rpm", raw, re.IGNORECASE):
            return re.sub(r"\brpm\b", "RPM", raw, flags=re.IGNORECASE)
        return raw
    return t("not_available", lang)


def _normalizar_rotacion(rotacion: str) -> str:
    """Texto limpio para el campo de rotación/tipo."""
    low = rotacion.lower().strip()
    if not low or "no especificada" in low:
        return "SSD"
    if "solid state" in low:
        return "SSD (sin partes móviles)"
    return rotacion


def _infer_sector_size(sectores: str) -> int:
    if not sectores:
        return 512
    if re.search(r"4096", sectores):
        return 4096
    match = re.search(r"(\d+)\s*bytes?\s*physical", sectores, re.I)
    if match and int(match.group(1)) >= 4096:
        return int(match.group(1))
    return 512


def _assess_data_quality_sata(report: DiskReport, attrs: dict) -> DataQuality:
    if not attrs and not report.smart_passed:
        return "minimal"
    health_present = sum(1 for aid in HEALTH_ATTR_IDS if aid in attrs)
    if health_present >= 5:
        return "full"
    if health_present >= 1 or report.horas > 0:
        return "partial"
    return "minimal"


def _assess_data_quality_nvme(report: DiskReport) -> DataQuality:
    if report.atributos_criticos and report.horas > 0:
        return "partial"
    if report.atributos_criticos:
        return "partial"
    return "minimal"


def _infer_factor_forma(modelo: str, rotacion: str) -> str:
    modelo_lower = modelo.lower()
    if "3.5" in modelo_lower or "skyhawk" in modelo_lower or "ironwolf" in modelo_lower:
        return '3.5"'
    if "2.5" in modelo_lower or "laptop" in modelo_lower:
        return '2.5"'
    if "ssd" in rotacion.lower() or rotacion.lower() == "solid state device":
        return "2.5\" / M.2"
    return '3.5"'


def _capacidad_corta(capacidad: str, es_ssd: bool = False) -> str:
    cap = capacidad.upper()
    prefix = "SSD" if es_ssd else "HDD"
    if "TB" in cap:
        match = re.search(r"([\d.]+)\s*TB", cap)
        if match:
            return f"{prefix} {match.group(1)}TB"
    if "GB" in cap:
        match = re.search(r"([\d.]+)\s*GB", cap)
        if match:
            return f"{prefix} {match.group(1)}GB"
    return prefix if es_ssd else "HDD"


def _is_nvme_smart(raw_text: str) -> bool:
    return "SMART/Health Information (NVMe" in raw_text or bool(
        re.search(r"NVMe Version:\s+", raw_text)
    )


def _parse_nvme_field(raw_text: str, label: str) -> str:
    pattern = rf"^{re.escape(label)}:\s+(.+)$"
    for line in raw_text.splitlines():
        m = re.match(pattern, line.strip())
        if m:
            return m.group(1).strip()
    return ""


def _parse_tb_from_nvme_units(value: str) -> Optional[float]:
    if not value:
        return None
    match = re.search(r"\[([\d.]+)\s*TB\]", value, re.IGNORECASE)
    if match:
        return float(match.group(1))
    match = re.search(r"\[([\d.]+)\s*GB\]", value, re.IGNORECASE)
    if match:
        return round(float(match.group(1)) / 1024, 2)
    return None


def _parse_percent(value: str) -> Optional[int]:
    match = re.search(r"(\d+)\s*%", value)
    return int(match.group(1)) if match else None


def _parse_nvme_health(report: DiskReport, raw_text: str) -> None:
    """Rellena DiskReport desde el log SMART/Health de NVMe."""
    report.es_nvme = True
    report.es_ssd = True
    report.rotacion = "SSD (NVMe)"

    crit = _parse_nvme_field(raw_text, "Critical Warning")
    temp_raw = _parse_nvme_field(raw_text, "Temperature")
    spare = _parse_nvme_field(raw_text, "Available Spare")
    pct_used = _parse_nvme_field(raw_text, "Percentage Used")
    data_read = _parse_nvme_field(raw_text, "Data Units Read")
    data_written = _parse_nvme_field(raw_text, "Data Units Written")
    power_cycles = _parse_nvme_field(raw_text, "Power Cycles")
    power_hours = _parse_nvme_field(raw_text, "Power On Hours")
    unsafe = _parse_nvme_field(raw_text, "Unsafe Shutdowns")
    media_errors = _parse_nvme_field(raw_text, "Media and Data Integrity Errors")
    error_log = _parse_nvme_field(raw_text, "Error Information Log Entries")

    if power_hours:
        report.horas = _parse_int(power_hours.replace(",", ""))
    if power_cycles:
        report.ciclos_encendido = _parse_int(power_cycles.replace(",", ""))

    report.datos_leidos_tb = _parse_tb_from_nvme_units(data_read)
    report.datos_escritos_tb = _parse_tb_from_nvme_units(data_written)

    if temp_raw:
        temp_match = re.search(r"(\d+)", temp_raw)
        if temp_match:
            report.temperatura_actual = int(temp_match.group(1))
            report.temperatura_promedio = None
            report.temperatura_maxima = None

    report.porcentaje_uso = _parse_percent(pct_used)
    report.spare_disponible = _parse_percent(spare)
    report.spare_umbral = _parse_percent(_parse_nvme_field(raw_text, "Available Spare Threshold"))
    report.errores_integridad = _parse_int(media_errors.replace(",", ""))
    report.apagados_inseguros = _parse_int(unsafe.replace(",", ""))
    report.sectores_reasignados = 0
    report.sectores_pendientes = 0

    def add_nvme_attr(
        attr_id: int,
        name: str,
        value: str,
        status: str,
        meaning: str,
    ) -> None:
        report.atributos_criticos.append(
            SmartAttribute(
                attr_id=attr_id,
                name=name,
                raw_value=value,
                status=status,
                meaning=meaning,
            )
        )

    crit_val = crit or "0x00"
    crit_ok = crit_val in ("0x00", "0x0", "0")
    add_nvme_attr(
        NVME_ATTR_CRITICAL_WARNING,
        "Critical Warning",
        crit_val,
        "OK" if crit_ok else "Alerta",
        "Sin advertencias críticas del controlador NVMe."
        if crit_ok
        else "El controlador reporta una condición crítica de salud.",
    )

    media_val = _parse_int(media_errors.replace(",", "")) if media_errors else 0
    add_nvme_attr(
        NVME_ATTR_MEDIA_ERRORS,
        "Media and Data Integrity Errors",
        str(media_val),
        "OK" if media_val == 0 else "Alerta",
        "Sin errores de integridad de medios o datos."
        if media_val == 0
        else "Se detectaron errores de integridad en el medio de almacenamiento.",
    )

    pct = report.porcentaje_uso if report.porcentaje_uso is not None else 0
    pct_status = "OK" if pct < 50 else ("Nota" if pct < 80 else "Alerta")
    add_nvme_attr(
        NVME_ATTR_PERCENTAGE_USED,
        "Percentage Used (wear)",
        f"{pct}%",
        pct_status,
        "Desgaste del NAND dentro de parámetros normales."
        if pct < 50
        else ("Desgaste moderado; monitorear periódicamente." if pct < 80 else "Desgaste elevado del medio NAND."),
    )

    spare_pct = report.spare_disponible if report.spare_disponible is not None else 100
    spare_status = "OK" if spare_pct >= 20 else ("Nota" if spare_pct >= 10 else "Alerta")
    add_nvme_attr(
        NVME_ATTR_AVAILABLE_SPARE,
        "Available Spare",
        f"{spare_pct}%",
        spare_status,
        "Reserva de bloques de repuesto suficiente."
        if spare_pct >= 20
        else "Reserva de repuesto reducida; vigilar el estado del disco.",
    )

    if report.temperatura_actual is not None:
        t = report.temperatura_actual
        t_status = "OK" if t < 50 else ("Nota" if t <= 60 else "Alerta")
        add_nvme_attr(
            NVME_ATTR_TEMPERATURE,
            "Temperature",
            f"{t} °C",
            t_status,
            "Temperatura de operación dentro de rango normal."
            if t < 50
            else "Temperatura elevada; mejorar ventilación si es posible.",
        )

    unsafe_val = report.apagados_inseguros
    unsafe_status = "OK" if unsafe_val == 0 else ("Nota" if unsafe_val <= 20 else "Alerta")
    add_nvme_attr(
        NVME_ATTR_UNSAFE_SHUTDOWNS,
        "Unsafe Shutdowns",
        str(unsafe_val),
        unsafe_status,
        "Sin apagados inesperados registrados."
        if unsafe_val == 0
        else "Apagados sin sincronización; puede afectar la integridad a largo plazo.",
    )

    err_log_val = _parse_int(error_log.replace(",", "")) if error_log else 0
    add_nvme_attr(
        NVME_ATTR_ERROR_LOG,
        "Error Information Log Entries",
        str(err_log_val),
        "OK" if err_log_val == 0 else "Alerta",
        "Sin entradas en el registro de errores NVMe."
        if err_log_val == 0
        else "Hay entradas en el registro de errores del controlador.",
    )

    report.data_quality = _assess_data_quality_nvme(report)


def _detectar_linea_producto(modelo: str) -> str:
    modelo_lower = modelo.lower()
    if "skyhawk" in modelo_lower or modelo_lower.startswith("st2000vx"):
        return "skyhawk"
    if "ironwolf" in modelo_lower:
        return "ironwolf"
    if "barracuda" in modelo_lower:
        return "barracuda"
    if "wd" in modelo_lower or "western digital" in modelo_lower:
        return "wd"
    return ""


def parsear_smartctl(raw_text: str) -> DiskReport:
    """Convierte la salida completa de smartctl -a en un DiskReport."""
    report = DiskReport()

    version_match = re.search(r"smartctl (\d+\.\d+)", raw_text)
    if version_match:
        report.smartctl_version = f"smartctl (smartmontools {version_match.group(1)})"

    report.modelo = _search(r"Device Model:\s+(.+)", raw_text) or _search(
        r"Model Number:\s+(.+)", raw_text, default="Desconocido"
    )
    report.serial = _search(r"Serial Number:\s+(.+)", raw_text, default="Desconocido")
    report.firmware = _search(r"Firmware Version:\s+(.+)", raw_text, default="Desconocido")
    report.rotation_rate_raw = _search(r"Rotation Rate:\s+(.+)", raw_text) or _search(
        r"Rotation Speed:\s+(.+)", raw_text
    )

    is_nvme = _is_nvme_smart(raw_text)

    cap_match = re.search(r"Namespace 1 Size/Capacity:\s+.+?\[(.+?)\]", raw_text)
    if not cap_match:
        cap_match = re.search(r"Total NVM Capacity:\s+.+?\[(.+?)\]", raw_text)
    if not cap_match:
        cap_match = re.search(r"User Capacity:\s+.+?\[(.+?)\]", raw_text)
    if cap_match:
        report.capacidad = cap_match.group(1).strip()

    if is_nvme:
        report.es_nvme = True
        report.es_ssd = True
        nvme_ver = _search(r"NVMe Version:\s+(.+)", raw_text)
        report.interfaz = f"NVMe {nvme_ver}" if nvme_ver else "NVMe"
        report.rotacion = "SSD (NVMe)"
        report.velocidad_interfaz = _parse_link_speed_nvme(raw_text)
        report.factor_forma = "M.2 / NVMe"
        logical = _search(r"Namespace 1 Formatted LBA Size:\s+(\d+)", raw_text)
        if logical:
            report.sectores = f"{logical}B lógico"
    else:
        sata = _search(r"SATA Version is:\s+(.+)", raw_text)
        if sata:
            report.interfaz = sata
        else:
            transport = _search(r"Transport protocol:\s+(.+)", raw_text)
            report.interfaz = transport or "ATA/SATA"

        rotacion = report.rotation_rate_raw or _search(r"Rotation Rate:\s+(.+)", raw_text) or _search(
            r"Rotation Speed:\s+(.+)", raw_text
        )
        if rotacion:
            report.es_ssd = "ssd" in rotacion.lower() or "solid state" in rotacion.lower()
            report.rotacion = _normalizar_rotacion(rotacion) if report.es_ssd else rotacion
        else:
            report.rotacion = "SSD"
            report.es_ssd = True

        report.velocidad_interfaz = _parse_link_speed_sata(raw_text, report.interfaz)

        sectores = _search(r"Sector Sizes:\s+(.+)", raw_text)
        if sectores:
            report.sectores = sectores
        else:
            logical = _search(r"Sector Size:\s+(\d+)", raw_text)
            if logical:
                report.sectores = f"{logical}B lógico"

        report.factor_forma = _search(r"Form Factor:\s+(.+)", raw_text) or _infer_factor_forma(
            report.modelo, report.rotacion
        )

    report.capacidad_corta = _capacidad_corta(report.capacidad, report.es_ssd)

    report.es_seagate = "seagate" in report.modelo.lower() or report.modelo.upper().startswith("ST")
    report.linea_producto = _detectar_linea_producto(report.modelo)

    health = _search(
        r"SMART overall-health self-assessment test result:\s+(\w+)", raw_text, default="PASSED"
    )
    report.smart_status_text = health.upper()
    report.smart_passed = health.upper() == "PASSED"

    if re.search(r"Self-test execution status:\s+\(\s*0\s*\)", raw_text):
        report.tiene_test_largo_reciente = True
    if re.search(r"# 1\s+Extended offline\s+Completed", raw_text, re.IGNORECASE):
        report.tiene_test_largo_reciente = True
    if re.search(r"No Self-tests Logged", raw_text, re.IGNORECASE):
        report.tiene_test_largo_reciente = False

    if is_nvme:
        _parse_nvme_health(report, raw_text)
        return report

    attrs = _parse_smart_attributes(raw_text)
    report.sector_size_bytes = _infer_sector_size(report.sectores)

    if 5 in attrs:
        report.sectores_reasignados = _parse_int(attrs[5]["raw"])
    if 197 in attrs:
        report.sectores_pendientes = _parse_int(attrs[197]["raw"])
    if 9 in attrs:
        report.horas = _parse_int(attrs[9]["raw"])
    if 12 in attrs:
        report.ciclos_encendido = _parse_int(attrs[12]["raw"])
    elif 4 in attrs:
        report.ciclos_encendido = _parse_int(attrs[4]["raw"])
        report.ciclos_es_start_stop = True
    else:
        for linea in raw_text.split("\n"):
            if re.search(r"^\s*12\s+Power_Cycle_Count", linea):
                partes = linea.split()
                if len(partes) >= 10:
                    report.ciclos_encendido = _parse_int(partes[9])
                break

    sector = report.sector_size_bytes
    if 241 in attrs:
        report.datos_escritos_tb = _lba_to_tb(attrs[241]["raw"], sector)
    if 242 in attrs:
        report.datos_leidos_tb = _lba_to_tb(attrs[242]["raw"], sector)

    temp_attr = attrs.get(194) or attrs.get(190)
    if temp_attr:
        raw_full = temp_attr["raw"]
        temp_match = re.search(r"^(\d+)", raw_full)
        temp_raw = _parse_int(temp_match.group(1)) if temp_match else 0
        minmax = re.search(r"Min/Max\s+(\d+)/(\d+)", raw_full)
        if temp_raw > 1000:
            report.temperatura_actual = temp_raw // 1000
        else:
            report.temperatura_actual = temp_raw
        if minmax:
            t_min = int(minmax.group(1))
            t_max = int(minmax.group(2))
            report.temperatura_promedio = (t_min + t_max) // 2
            report.temperatura_maxima = t_max
        else:
            report.temperatura_promedio = report.temperatura_actual
            report.temperatura_maxima = report.temperatura_actual

    for attr_id in HEALTH_ATTR_IDS:
        if attr_id not in attrs:
            continue
        attr_data = attrs[attr_id]
        name = ATTR_NAMES.get(attr_id, attr_data["name"])
        raw_val = attr_data["raw"]
        status = _evaluar_estado(attr_id, raw_val, report.es_seagate, report.sectores_reasignados)
        meaning = _meaning_for_attr(attr_id, raw_val, report.es_seagate, report.sectores_reasignados)

        display_val = raw_val
        if attr_id in (190, 194):
            t_val = _parse_int(raw_val)
            if t_val > 1000:
                t_val = t_val // 1000
            display_val = f"{t_val} °C"
        elif attr_id == 188:
            display_val = _format_command_timeout(raw_val)

        report.atributos_criticos.append(
            SmartAttribute(
                attr_id=attr_id,
                name=f"{name} ({attr_id:02d})",
                raw_value=display_val,
                status=status,
                meaning=meaning,
            )
        )

    report.data_quality = _assess_data_quality_sata(report, attrs)
    return report


def significado_nvme_attr(attr: SmartAttribute, lang: str = "es") -> str:
    """Texto bilingüe del significado de atributos NVMe en el reporte."""
    val = _parse_int(attr.raw_value.replace("%", ""))
    if attr.attr_id == NVME_ATTR_CRITICAL_WARNING:
        ok = attr.raw_value in ("0x00", "0x0", "0")
        if lang == "en":
            return "No critical NVMe controller warnings." if ok else "The controller reports a critical health condition."
        return "Sin advertencias críticas del controlador NVMe." if ok else "El controlador reporta una condición crítica de salud."
    if attr.attr_id == NVME_ATTR_MEDIA_ERRORS:
        if lang == "en":
            return "No media or data integrity errors." if val == 0 else "Media integrity errors were detected."
        return "Sin errores de integridad de medios o datos." if val == 0 else "Se detectaron errores de integridad en el medio."
    if attr.attr_id == NVME_ATTR_PERCENTAGE_USED:
        if lang == "en":
            if val < 50:
                return "NAND wear within normal parameters."
            if val < 80:
                return "Moderate wear; monitor periodically."
            return "High NAND wear on the storage medium."
        if val < 50:
            return "Desgaste del NAND dentro de parámetros normales."
        if val < 80:
            return "Desgaste moderado; monitorear periódicamente."
        return "Desgaste elevado del medio NAND."
    if attr.attr_id == NVME_ATTR_AVAILABLE_SPARE:
        if lang == "en":
            return "Sufficient spare block reserve." if val >= 20 else "Reduced spare reserve; monitor drive health."
        return "Reserva de bloques de repuesto suficiente." if val >= 20 else "Reserva de repuesto reducida; vigilar el estado del disco."
    if attr.attr_id == NVME_ATTR_TEMPERATURE:
        if lang == "en":
            return "Operating temperature within normal range." if val < 50 else "Elevated temperature; improve cooling if possible."
        return "Temperatura de operación dentro de rango normal." if val < 50 else "Temperatura elevada; mejorar ventilación si es posible."
    if attr.attr_id == NVME_ATTR_UNSAFE_SHUTDOWNS:
        if lang == "en":
            return "No unsafe shutdowns recorded." if val == 0 else "Unsafe shutdowns recorded; avoid abrupt power loss."
        return "Sin apagados inesperados registrados." if val == 0 else "Apagados sin sincronización; evite cortes de energía bruscos."
    if attr.attr_id == NVME_ATTR_ERROR_LOG:
        if lang == "en":
            return "No entries in the NVMe error log." if val == 0 else "Entries found in the controller error log."
        return "Sin entradas en el registro de errores NVMe." if val == 0 else "Hay entradas en el registro de errores del controlador."
    return attr.meaning


def generar_observaciones(report: DiskReport, lang: str = "es") -> str:
    """Genera el párrafo de observaciones dinámico."""
    partes = []

    if report.linea_producto == "skyhawk":
        if lang == "en":
            partes.append(
                f"The {report.modelo} belongs to the Seagate SkyHawk line, designed for "
                "24/7 video surveillance recording, which explains a high number of "
                "accumulated power-on hours."
            )
        else:
            partes.append(
                f"El {report.modelo} pertenece a la línea Seagate SkyHawk, diseñada para "
                "grabación de videovigilancia 24/7, lo que explica un elevado número de horas "
                "de encendido acumuladas."
            )
    elif report.linea_producto == "ironwolf":
        if lang == "en":
            partes.append(
                f"The {report.modelo} belongs to the Seagate IronWolf line, oriented toward "
                "NAS and network storage with continuous operation."
            )
        else:
            partes.append(
                f"El {report.modelo} pertenece a la línea Seagate IronWolf, orientada a NAS "
                "y almacenamiento en red con operación continua."
            )
    else:
        if report.es_nvme:
            partes.append(
                f"NVMe SSD ({report.modelo}) with {report.horas:,} power-on hours "
                f"and {report.porcentaje_uso or 0}% NAND wear."
                if lang == "en"
                else f"SSD NVMe ({report.modelo}) con {report.horas:,} horas de encendido "
                f"y {report.porcentaje_uso or 0}% de desgaste NAND."
            )
        else:
            partes.append(
                f"Drive from the {report.modelo} product line."
                if lang == "en"
                else f"Disco de la línea {report.modelo}."
            )

    if report.es_nvme and report.spare_disponible is not None and report.spare_umbral is not None:
        if report.spare_disponible <= report.spare_umbral:
            partes.append(
                f"Available spare ({report.spare_disponible}%) is at or below the threshold ({report.spare_umbral}%)."
                if lang == "en"
                else f"La reserva disponible ({report.spare_disponible}%) está en o por debajo del umbral ({report.spare_umbral}%)."
            )

    if report.ciclos_es_start_stop:
        partes.append(
            "Power cycles estimated from Start-Stop Count (attribute 4); may differ from Power Cycle Count."
            if lang == "en"
            else "Los ciclos de encendido se estiman desde Start-Stop Count (atributo 4); pueden diferir del Power Cycle Count."
        )

    if report.es_nvme and report.apagados_inseguros > 0:
        partes.append(
            f"{report.apagados_inseguros} unsafe shutdown(s) recorded; avoid abrupt power loss when possible."
            if lang == "en"
            else f"Se registraron {report.apagados_inseguros} apagados inseguros; evite cortes de energía bruscos."
        )

    if report.horas > 20000:
        years = round(report.horas / 8760, 1)
        if lang == "en":
            partes.append(
                f"With {report.horas:,} hours of operation (~{years} years of continuous use), "
                "accumulated wear is significant although critical indicators remain stable."
            )
        else:
            partes.append(
                f"Con {report.horas:,} horas de funcionamiento (~{years} años de operación continua), "
                "el desgaste acumulado es significativo aunque los indicadores críticos permanezcan estables."
            )

    if report.es_seagate:
        partes.append(
            "Elevated Raw Read Error Rate values on Seagate drives correspond to "
            "their internal factory encoding and do not represent real read errors."
            if lang == "en"
            else "Los valores raw elevados de Raw Read Error Rate en discos Seagate corresponden "
            "a su codificación interna de fábrica y no representan errores de lectura reales."
        )

    if report.sectores_reasignados == 0 and report.sectores_pendientes == 0:
        if report.es_nvme and report.errores_integridad == 0:
            partes.append(
                "No media integrity errors or critical NVMe warnings at the time of diagnosis."
                if lang == "en"
                else "Sin errores de integridad de medios ni advertencias críticas NVMe en el momento del diagnóstico."
            )
        elif not report.es_nvme:
            partes.append(
                "No reallocated or pending sectors recorded at the time of diagnosis."
                if lang == "en"
                else "No se registran sectores reasignados ni pendientes en el momento del diagnóstico."
            )

    if not report.tiene_test_largo_reciente:
        partes.append(
            "A long self-test (smartctl -t long) is recommended as additional "
            "verification for any in-depth audit."
            if lang == "en"
            else "Se recomienda ejecutar un test largo (smartctl -t long) como verificación "
            "adicional ante cualquier auditoría profunda."
        )

    return " ".join(partes)


def generar_recomendacion(report: DiskReport, lang: str = "es") -> str:
    """Genera el texto de recomendación según el estado del disco."""
    if report.data_quality == "minimal":
        if lang == "en":
            return (
                "<b>Insufficient data for a reliable recommendation.</b> S.M.A.R.T. information "
                "was limited or unavailable. Run smartctl as administrator or try another interface "
                "before using this drive for important storage."
            )
        return (
            "<b>Datos insuficientes para una recomendación fiable.</b> La información S.M.A.R.T. "
            "fue limitada o no disponible. Ejecute smartctl como administrador o pruebe otra "
            "interfaz antes de usar este disco para almacenamiento importante."
        )

    if report.data_quality == "partial":
        caution_es = (
            "<b>Interprete con cautela.</b> Los datos S.M.A.R.T. son parciales "
            "(común en NVMe o discos externos). "
        )
        caution_en = (
            "<b>Interpret with caution.</b> S.M.A.R.T. data is partial "
            "(common on NVMe or external drives). "
        )
        caution = caution_en if lang == "en" else caution_es
    else:
        caution = ""

    if not report.smart_passed:
        if lang == "en":
            return caution + (
                "<b>Not suitable for reliable use.</b> The S.M.A.R.T. self-diagnostic reported "
                "FAILED. It is not recommended to store important data on this unit. "
                "Back up any existing information immediately and consider replacing the drive."
            )
        return caution + (
            "<b>No apto para uso confiable.</b> El auto-diagnóstico S.M.A.R.T. reportó "
            "FALLIDO. No se recomienda almacenar datos importantes en esta unidad. "
            "Realice copia de seguridad inmediata de cualquier información existente "
            "y considere el reemplazo del disco."
        )

    if report.sectores_reasignados > 0 or report.sectores_pendientes > 0:
        if lang == "en":
            return caution + (
                f"<b>Attention required.</b> {report.sectores_reasignados} reallocated and "
                f"{report.sectores_pendientes} pending sectors detected after {report.horas:,} hours "
                "of use. The drive may only be used for temporary testing or non-critical "
                "storage under strict S.M.A.R.T. monitoring."
            )
        return caution + (
            f"<b>Atención requerida.</b> Se detectaron {report.sectores_reasignados} sectores "
            f"reasignados y {report.sectores_pendientes} pendientes tras {report.horas:,} horas "
            "de uso. El disco puede utilizarse únicamente para pruebas temporales o "
            "almacenamiento no crítico bajo estricta supervisión S.M.A.R.T."
        )

    if lang == "en":
        health = f"Good health status (0 reallocated sectors after {report.horas:,} hours)"
        if report.horas >= 20000:
            return caution + (
                f"<b>Suitable for secondary storage.</b> {health}, but due to accumulated "
                "usage time it is recommended for non-critical or backed-up data, with "
                "periodic S.M.A.R.T. monitoring. As with any used drive: always keep a backup."
            )
        return caution + (
            f"<b>Suitable for primary or secondary use.</b> {health}. The component has "
            "an optimal remaining lifecycle for standard bulk storage operations."
        )

    estado = f"Buen estado de salud (0 sectores reasignados tras {report.horas:,} horas)"
    if report.horas >= 20000:
        return caution + (
            f"<b>Apto para uso como almacenamiento secundario.</b> {estado}, pero por su "
            "tiempo acumulado de uso se recomienda utilizarlo para datos no críticos o "
            "respaldados, y monitorear el S.M.A.R.T. periódicamente. Como con cualquier "
            "unidad usada: mantener siempre copia de seguridad de la información."
        )
    return caution + (
        f"<b>Apto para uso principal o secundario.</b> {estado}. El componente cuenta con "
        "un ciclo de vida remanente óptimo para operaciones estándar de almacenamiento masivo."
    )
