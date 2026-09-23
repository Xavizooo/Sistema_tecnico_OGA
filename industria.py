from __future__ import annotations

import math
import os
from io import BytesIO
import re
import tempfile
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import Blueprint, flash, jsonify, redirect, render_template, request, send_file, url_for
from openpyxl import Workbook, load_workbook

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "INDUSTRIA"
DATA_DIR.mkdir(parents=True, exist_ok=True)
_LOCK = threading.RLock()
_ROWS_CACHE: dict[str, tuple[int, int, list[dict[str, str]]]] = {}
_ALLOWED_UPLOADS = {".xlsx", ".xlsm"}

bp = Blueprint("industria", __name__)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _norm(value: Any) -> str:
    txt = unicodedata.normalize("NFKD", _text(value)).encode("ascii", "ignore").decode("ascii")
    txt = re.sub(r"[^A-Z0-9]+", " ", txt.upper()).strip()
    return re.sub(r"\s+", " ", txt)


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    code: str = ""
    kind: str = "text"  # text | number | textarea
    source_col: int | None = None


@dataclass(frozen=True)
class Section:
    slug: str
    title: str
    sheet: str
    filename: str
    fields: tuple[Field, ...]
    source_start_row: int
    description: str


SECTIONS: dict[str, Section] = {
    "puntos-origen": Section(
        slug="puntos-origen",
        title="Tipos de puntos de origen",
        sheet="TIPOS DE PUNTOS DE ORIGEN",
        filename="TIPOS_DE_PUNTOS_DE_ORIGEN.xlsx",
        source_start_row=2,
        description="Catálogo independiente de puntos de origen y puntos de destino.",
        fields=(
            Field("tipo_origen", "Puntos de origen", "PO_01", source_col=1),
            Field("tipo_destino", "Puntos de destino", "PO_02", source_col=4),
        ),
    ),
    "ciudades": Section(
        slug="ciudades",
        title="Ciudades",
        sheet="CIUDADES",
        filename="CIUDADES.xlsx",
        source_start_row=2,
        description="Datos ambientales y eléctricos de las ciudades utilizadas por los proyectos.",
        fields=(
            Field("pais", "País", source_col=1),
            Field("ciudad", "Ciudad", source_col=2),
            Field("altitud_m", "Altitud (m.s.n.m)", kind="number", source_col=3),
            Field("presion_bar", "Presión ATM (bar)", kind="number", source_col=4),
            Field("temperatura_c", "Temperatura promedio (°C)", kind="number", source_col=5),
            Field("frecuencia_hz", "Frecuencia (Hz)", kind="number", source_col=6),
            Field("humedad", "Humedad", kind="number", source_col=7),
        ),
    ),
    "materiales": Section(
        slug="materiales",
        title="Tipos de material",
        sheet="TIPOS DE MATERIALES",
        filename="TIPOS_DE_MATERIALES.xlsx",
        source_start_row=3,
        description="Propiedades de producto requeridas para la selección y comparación de soluciones.",
        fields=(
            Field("codigo", "Código", source_col=1, kind="number"),
            Field("nombre", "Nombre común", "MT-02", source_col=2),
            Field("densidad", "Densidad aparente (kg/l)", "MT-03", "number", 3),
            Field("tamano_micras", "Tamaño medio (micras)", "MT-04", "number", 4),
            Field("temperatura_producto", "Temperatura del producto (°C)", "MT-16", "number", 5),
            Field("fluidez", "Fluidez", "MT-05", source_col=6),
            Field("abrasividad", "Abrasividad", "MT-06", source_col=7),
            Field("humedad", "Humedad (%)", "MT-07", "number", 8),
            Field("grasa", "Contenido grasa", "M-08", "number", 9),
            Field("regularidad", "Regularidad partícula", "MT-13", source_col=10),
            Field("absorcion_aire", "Absorción de aire", "MT-14", source_col=11),
            Field("angulo_reposo", "Ángulo de reposo con horizontal", "MT-15", "number", 12),
            Field("higroscopico", "Higroscópico", "MT-09", source_col=13),
            Field("explosividad", "Explosividad", "MT-10", source_col=14),
            Field("corrosivo", "Corrosivo", "MT-11", source_col=15),
            Field("riesgo_biologico", "Riesgo biológico", "MT-12", source_col=16),
        ),
    ),
    "cb-matriz": Section(
        slug="cb-matriz",
        title="DATOS DE ENTRADA",
        sheet="CB_MATRIZ",
        filename="CB_MATRIZ.xlsx",
        source_start_row=2,
        description="Catálogos independientes para voltaje de potencia y materiales de entrada del sistema.",
        fields=(
            Field("voltaje", "Voltaje De Potencia", "CB_OD_A1", "number", 2),
            Field("material_contacto", "Material en contacto con producto", "CB_OD_A2", source_col=3),
            Field("material_estructura", "Material estructuras", "CB_OD_A3", source_col=4),
        ),
    ),
    "codigo-equipos": Section(
        slug="codigo-equipos",
        title="Código de equipos",
        sheet="EQUIPOS",
        filename="CODIGO_DE_EQUIPOS.xlsx",
        source_start_row=2,
        description="Catálogo de tipos de equipo y sus referencias para consulta rápida.",
        fields=(
            Field("tipo_equipo", "Tipo de Equipo", source_col=3),
            Field("referencia", "Referencias", source_col=4),
        ),
    ),
    "cs": Section(
        slug="cs",
        title="CS criterios de salida",
        sheet="CS-CRITERIOS DE SALIDA",
        filename="CS_CRITERIOS_DE_SALIDA.xlsx",
        source_start_row=5,
        description="Criterios de salida, opciones de equipos y búsqueda numérica por proximidad.",
        fields=(
            Field("codigo_cs", "Código CS", source_col=2),
            Field("criterio", "Criterio de salida", source_col=3),
            Field("nomenclatura", "Nomenclatura", source_col=5),
            Field("descripcion_transporte", "Descripción transporte", source_col=6),
            Field("diametro_tuberia", "Ø tubería de transporte", source_col=7),
            Field("tipo_acople", "Tipo de acople", source_col=8),
            Field("potencia_hp", "Potencia (hp)", kind="number", source_col=9),
            Field("caudal_cfm", "Caudal (CFM)", kind="number", source_col=10),
            Field("diferencial_psi", "Diferencial de presión (PSI)", kind="number", source_col=11),
            Field("tipo_bomba", "Tipo de bomba", source_col=12),
            Field("area_filtracion_m2", "Área de filtración (m²)", kind="number", source_col=13),
            Field("micraje_um", "Micraje área de filtración (µm)", kind="number", source_col=14),
            Field("consumo_aire_cfm", "Consumo de aire (CFM)", kind="number", source_col=15),
            Field("presion_alimentacion_psi", "Presión de alimentación (PSI)", kind="number", source_col=16),
            Field("equipo_slot", "Equipo", source_col=17),
            Field("tag", "TAG", source_col=18),
            Field("descripcion_equipo", "Descripción equipo", source_col=19),
            Field("referencia", "Referencia", source_col=20),
        ),
    ),
}

NUMERIC_CS_FIELDS = {
    "potencia_hp": "Potencia (hp)",
    "caudal_cfm": "Caudal (CFM)",
    "diferencial_psi": "Diferencial de presión (PSI)",
    "area_filtracion_m2": "Área de filtración (m²)",
    "micraje_um": "Micraje área de filtración (µm)",
    "consumo_aire_cfm": "Consumo de aire (CFM)",
    "presion_alimentacion_psi": "Presión de alimentación (PSI)",
}

CS_FIELD_UNITS = {
    "potencia_hp": "hp",
    "caudal_cfm": "CFM",
    "diferencial_psi": "PSI",
    "area_filtracion_m2": "m²",
    "micraje_um": "µm",
    "consumo_aire_cfm": "CFM",
    "presion_alimentacion_psi": "PSI",
}


CB_INPUT_KEYS = {"voltaje", "material_contacto", "material_estructura"}
CB_LEGACY_HEADERS = {
    "voltaje": ("Voltaje De Potencia", "Voltaje de potencia (V)", "Voltaje de potencia"),
    "material_contacto": ("Material en contacto con producto",),
    "material_estructura": ("Material estructuras", "Material estructura"),
}
CB_EXPORT_NAMES = {
    "voltaje": "DATOS_ENTRADA_VOLTAJE_DE_POTENCIA.xlsx",
    "material_contacto": "DATOS_ENTRADA_MATERIAL_CONTACTO_PRODUCTO.xlsx",
    "material_estructura": "DATOS_ENTRADA_MATERIAL_ESTRUCTURAS.xlsx",
}


def _path(section: Section) -> Path:
    return DATA_DIR / section.filename


def _atomic_save(section: Section, rows: list[dict[str, str]]) -> None:
    path = _path(section)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = section.sheet[:31]
    ws.append([f.label for f in section.fields] + ["_OGA_ID"])
    for row in rows:
        ws.append([_text(row.get(f.key)) for f in section.fields] + [_text(row.get("id")) or uuid.uuid4().hex])
    ws.freeze_panes = "A2"
    for idx, field in enumerate(section.fields, 1):
        ws.column_dimensions[ws.cell(1, idx).column_letter].width = min(max(len(field.label) + 3, 15), 42)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}_", suffix=".xlsx", dir=path.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        wb.save(temp)
        check = load_workbook(temp, read_only=True, data_only=False)
        check.close()
        os.replace(temp, path)
        # La siguiente lectura debe reflejar inmediatamente el archivo guardado.
        _ROWS_CACHE.pop(section.slug, None)
    finally:
        temp.unlink(missing_ok=True)


def _ensure(section: Section) -> None:
    if not _path(section).exists():
        _atomic_save(section, [])


def _load(section: Section) -> list[dict[str, str]]:
    with _LOCK:
        _ensure(section)
        path = _path(section)
        stat = path.stat()
        cached = _ROWS_CACHE.get(section.slug)
        if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
            # Entregamos copias para que ediciones/merge nunca muten el cache.
            return [dict(row) for row in cached[2]]

        # DATOS DE ENTRADA se maneja como tres catálogos independientes dentro
        # del mismo CB_MATRIZ.xlsx. Cada fila almacenada pertenece a una sola
        # tabla. Al leer un archivo histórico (donde los tres valores compartían
        # fila con muchas columnas adicionales) se separan automáticamente sin
        # inventar datos y sin tocar el archivo hasta el siguiente guardado.
        if section.slug == "cb-matriz":
            wb = load_workbook(path, read_only=True, data_only=True)
            try:
                ws = wb[section.sheet] if section.sheet in wb.sheetnames else wb.active
                header_values = tuple(next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ()))
                header_map = {_norm(value): idx for idx, value in enumerate(header_values) if _text(value)}
                id_idx = header_map.get(_norm("_OGA_ID"))

                field_indices: dict[str, int | None] = {}
                for field in section.fields:
                    idx = None
                    for alias in CB_LEGACY_HEADERS.get(field.key, (field.label,)):
                        idx = header_map.get(_norm(alias))
                        if idx is not None:
                            break
                    field_indices[field.key] = idx

                rows: list[dict[str, str]] = []
                for values in ws.iter_rows(min_row=2, values_only=True):
                    values = tuple(values)
                    base_id = _text(values[id_idx]) if id_idx is not None and id_idx < len(values) else ""
                    found = []
                    for field in section.fields:
                        idx = field_indices.get(field.key)
                        value = _text(values[idx]) if idx is not None and idx < len(values) else ""
                        if value:
                            found.append((field.key, value))
                    for pos, (field_key, value) in enumerate(found):
                        row = {f.key: "" for f in section.fields}
                        row[field_key] = value
                        row["id"] = base_id if pos == 0 and base_id else uuid.uuid4().hex
                        rows.append(row)

                _ROWS_CACHE[section.slug] = (
                    stat.st_mtime_ns,
                    stat.st_size,
                    [dict(row) for row in rows],
                )
                return rows
            finally:
                wb.close()

        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.active
            rows: list[dict[str, str]] = []

            # Lee por encabezado cuando sea posible. Esto permite ampliar un
            # catalogo sin desplazar accidentalmente la columna _OGA_ID.
            # En CIUDADES, las versiones anteriores no tenian Humedad; en ese
            # caso el campo queda vacio y el ID existente se conserva intacto.
            header_values = tuple(next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ()))
            header_map = {_norm(value): idx for idx, value in enumerate(header_values) if _text(value)}
            id_idx = header_map.get(_norm("_OGA_ID"), len(section.fields))

            field_indices: dict[str, int | None] = {}
            for fallback_idx, field in enumerate(section.fields):
                header_idx = header_map.get(_norm(field.label))
                if header_idx is None and section.slug == "codigo-equipos" and field.key == "referencia":
                    # Compatibilidad con el archivo histórico, cuyo encabezado era "Referencia".
                    header_idx = header_map.get(_norm("Referencia"))
                if header_idx is None and section.slug == "puntos-origen":
                    # Compatibilidad con el catálogo histórico de seis columnas.
                    # Solo se conservan los nombres de origen/destino; cantidades y
                    # restricciones dejan de formar parte de este submódulo.
                    legacy_label = {
                        "tipo_origen": "Tipo de punto de origen",
                        "tipo_destino": "Tipo de punto de destino",
                    }.get(field.key)
                    if legacy_label:
                        header_idx = header_map.get(_norm(legacy_label))
                if header_idx is not None:
                    field_indices[field.key] = header_idx
                elif section.slug == "ciudades" and field.key == "humedad":
                    # Compatibilidad con CIUDADES.xlsx existente:
                    # antes la columna 7 era directamente _OGA_ID.
                    field_indices[field.key] = None
                else:
                    field_indices[field.key] = fallback_idx

            for values in ws.iter_rows(min_row=2, values_only=True):
                if not any(v not in (None, "") for v in values):
                    continue
                row: dict[str, str] = {}
                for field in section.fields:
                    idx = field_indices[field.key]
                    row[field.key] = _text(values[idx]) if idx is not None and idx < len(values) else ""
                row["id"] = _text(values[id_idx]) if id_idx < len(values) else ""
                if not row["id"]:
                    row["id"] = uuid.uuid4().hex
                rows.append(row)

            _ROWS_CACHE[section.slug] = (
                stat.st_mtime_ns,
                stat.st_size,
                [dict(row) for row in rows],
            )
            return rows
        finally:
            wb.close()


def _is_allowed_upload(filename: str) -> bool:
    return Path(Path(filename).name).suffix.lower() in _ALLOWED_UPLOADS


def _cb_field(section: Section, field_key: str) -> Field | None:
    if section.slug != "cb-matriz" or field_key not in CB_INPUT_KEYS:
        return None
    return next((field for field in section.fields if field.key == field_key), None)


def _parse_cb_single_field(section: Section, field_key: str, file_storage) -> list[str]:
    """Lee una lista independiente de DATOS DE ENTRADA desde Excel.

    Acepta tanto el CB_MATRIZ histórico como un archivo exportado por cualquiera
    de las tres tablas. Si el archivo tiene una sola columna sin encabezado
    reconocido, se toman todos los valores no vacíos de esa columna.
    """
    field = _cb_field(section, field_key)
    if field is None:
        raise ValueError("Tabla de DATOS DE ENTRADA no válida.")
    if not _is_allowed_upload(file_storage.filename or ""):
        raise ValueError("Solo se permiten archivos Excel .xlsx o .xlsm.")

    file_storage.stream.seek(0)
    wb = load_workbook(file_storage.stream, read_only=True, data_only=True)
    try:
        ws = wb[section.sheet] if section.sheet in wb.sheetnames else wb.active
        aliases = {_norm(alias) for alias in CB_LEGACY_HEADERS.get(field_key, (field.label,))}
        header_row = None
        value_col = None

        for row_num, values in enumerate(ws.iter_rows(min_row=1, max_row=12, values_only=True), start=1):
            for idx, value in enumerate(values):
                if _norm(value) in aliases:
                    header_row = row_num
                    value_col = idx
                    break
            if value_col is not None:
                break

        values_out: list[str] = []
        if value_col is not None:
            start_row = (header_row or 1) + 1
            for values in ws.iter_rows(min_row=start_row, values_only=True):
                values = tuple(values)
                value = _text(values[value_col]) if value_col < len(values) else ""
                if value:
                    values_out.append(value)
        elif ws.max_column == 1:
            # Plantilla mínima: una sola columna, con o sin encabezado.
            column_values = [_text(row[0]) for row in ws.iter_rows(values_only=True) if row]
            if column_values and _norm(column_values[0]) in aliases:
                column_values = column_values[1:]
            values_out = [value for value in column_values if value]
        else:
            raise ValueError(f"No encontré la columna '{field.label}' en el Excel.")

        return values_out
    finally:
        wb.close()


def _parse_source(section: Section, file_storage) -> list[dict[str, str]]:
    if not _is_allowed_upload(file_storage.filename or ""):
        raise ValueError("Solo se permiten archivos Excel .xlsx o .xlsm.")
    file_storage.stream.seek(0)
    wb = load_workbook(file_storage.stream, read_only=True, data_only=True)
    try:
        exact_sheet = section.sheet in wb.sheetnames
        ws = wb[section.sheet] if exact_sheet else wb.active

        if exact_sheet:
            # Código de equipos y Puntos de origen/destino admiten tanto sus
            # archivos históricos como el nuevo formato simplificado. La detección
            # por encabezados evita confundir columnas antiguas con campos vigentes.
            if section.slug in {"codigo-equipos", "puntos-origen"}:
                aliases = {_norm(f.label): f.key for f in section.fields}
                if section.slug == "codigo-equipos":
                    aliases[_norm("Referencia")] = "referencia"
                else:
                    aliases[_norm("Tipo de punto de origen")] = "tipo_origen"
                    aliases[_norm("Tipo de punto de destino")] = "tipo_destino"

                mapping: dict[int, str] = {}
                header_row = 0
                for row_num, values in enumerate(ws.iter_rows(min_row=1, max_row=12, values_only=True), start=1):
                    candidate: dict[int, str] = {}
                    for idx, value in enumerate(values):
                        key = aliases.get(_norm(value))
                        if key:
                            candidate[idx] = key
                    if len(set(candidate.values())) >= len(section.fields):
                        mapping = candidate
                        header_row = row_num
                        break
                if mapping:
                    rows: list[dict[str, str]] = []
                    for values in ws.iter_rows(min_row=header_row + 1, values_only=True):
                        values = tuple(values)
                        row = {f.key: "" for f in section.fields}
                        for idx, key in mapping.items():
                            row[key] = _text(values[idx]) if idx < len(values) else ""
                        if any(row.values()):
                            row["id"] = uuid.uuid4().hex
                            rows.append(row)
                    return rows

            rows: list[dict[str, str]] = []
            for values in ws.iter_rows(min_row=section.source_start_row, values_only=True):
                values = tuple(values)
                row = {}
                for field in section.fields:
                    idx = (field.source_col - 1) if field.source_col else None
                    # Un CIUDADES.xlsx de una version anterior tiene _OGA_ID
                    # en la columna 7. No debe importarse ese identificador
                    # como si fuera Humedad.
                    if (
                        section.slug == "ciudades"
                        and field.key == "humedad"
                        and idx is not None
                        and idx < len(values)
                        and _norm(ws.cell(row=1, column=idx + 1).value) == _norm("_OGA_ID")
                    ):
                        row[field.key] = ""
                    else:
                        row[field.key] = _text(values[idx]) if idx is not None and idx < len(values) else ""
                if any(row.values()):
                    row["id"] = uuid.uuid4().hex
                    rows.append(row)
            return rows

        aliases = {_norm(f.label): f.key for f in section.fields}
        if section.slug == "codigo-equipos":
            aliases[_norm("Referencia")] = "referencia"
        elif section.slug == "puntos-origen":
            aliases[_norm("Tipo de punto de origen")] = "tipo_origen"
            aliases[_norm("Tipo de punto de destino")] = "tipo_destino"
        mapping: dict[int, str] = {}
        rows: list[dict[str, str]] = []
        header_found = False
        for row_num, values in enumerate(ws.iter_rows(values_only=True), start=1):
            values = tuple(values)
            if not header_found:
                if row_num > 12:
                    break
                candidate: dict[int, str] = {}
                for idx, value in enumerate(values):
                    key = aliases.get(_norm(value))
                    if key:
                        candidate[idx] = key
                if len(candidate) >= max(1, min(3, len(section.fields))):
                    mapping = candidate
                    header_found = True
                continue
            row = {f.key: "" for f in section.fields}
            for idx, key in mapping.items():
                row[key] = _text(values[idx]) if idx < len(values) else ""
            if any(row.values()):
                row["id"] = uuid.uuid4().hex
                rows.append(row)
        if not header_found:
            raise ValueError(f"No encontré la hoja '{section.sheet}' ni encabezados compatibles.")
        return rows
    finally:
        wb.close()


def _row_key(section: Section, row: dict[str, str]) -> tuple[str, ...]:
    if section.slug == "ciudades":
        return (_norm(row.get("pais")), _norm(row.get("ciudad")))
    if section.slug == "materiales":
        return (_norm(row.get("codigo")) or _norm(row.get("nombre")),)
    if section.slug == "puntos-origen":
        return (_norm(row.get("tipo_origen")), _norm(row.get("tipo_destino")))
    if section.slug == "cb-matriz":
        for field in section.fields:
            value = _norm(row.get(field.key))
            if value:
                return (field.key, value)
        return ("", "")
    if section.slug == "codigo-equipos":
        return (_norm(row.get("tipo_equipo")), _norm(row.get("referencia")))
    if section.slug == "cs":
        return (_norm(row.get("codigo_cs")), _norm(row.get("criterio")), _norm(row.get("tag")), _norm(row.get("referencia")))
    return tuple(_norm(row.get(f.key)) for f in section.fields[:2])


def _merge(section: Section, existing: list[dict[str, str]], incoming: list[dict[str, str]]) -> tuple[list[dict[str, str]], int, int]:
    index = {_row_key(section, r): r for r in existing if any(_row_key(section, r))}
    added = updated = 0
    for src in incoming:
        key = _row_key(section, src)
        target = index.get(key) if any(key) else None
        if target is None:
            existing.append(src)
            if any(key):
                index[key] = src
            added += 1
        else:
            changed = False
            for field in section.fields:
                value = _text(src.get(field.key))
                if value and value != target.get(field.key, ""):
                    target[field.key] = value
                    changed = True
            if changed:
                updated += 1
    return existing, added, updated


def _simple_numeric(value: Any) -> float | None:
    raw = _text(value)
    if not raw:
        return None

    # Las celdas del maestro pueden contener instrucciones (por ejemplo,
    # "EJEMPLO 8,4 hp") que NO son datos del catálogo. Se ignoran para
    # evitar resultados falsos en el search de proximidad.
    normalized = _norm(raw)
    if any(marker in normalized for marker in (
        "NO APLICA",
        "EJEMPLO",
        "NUMERO COMPUESTO",
        "MAXIMO",
    )):
        return None

    # Acepta valores reales con o sin unidad: 8.4, 8,4, 380 CFM, 48 m²,
    # 5 µm, 5 um, 5 micras, etc. Debe ser toda la celda, no una frase.
    txt = re.sub(r"\s+", "", raw)
    m = re.fullmatch(
        r"(-?\d+(?:[\.,]\d+)?)(?:hp|cfm|psi|m2|m²|µm|μm|um|micra|micras)?",
        txt,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    try:
        number = float(m.group(1).replace(",", "."))
        return number if math.isfinite(number) else None
    except ValueError:
        return None


def _proximity_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    return {
        field: sum(1 for row in rows if _simple_numeric(row.get(field)) is not None)
        for field in NUMERIC_CS_FIELDS
    }


def _proximity(rows: list[dict[str, str]], field: str, target: float) -> dict[str, Any]:
    """Return the numeric window immediately around the value typed by the user.

    The center of the window is always the searched value. If that value exists in
    the catalogue, ``exact`` is true. The neighbours are always *distinct* values:
    the greatest catalogue value strictly below the target and the smallest value
    strictly above it. Example: catalogue [10, 20, 50], target 20 -> 10 | 20 | 50.
    """
    candidates: list[tuple[float, dict[str, str]]] = []
    for row in rows:
        number = _simple_numeric(row.get(field))
        if number is not None:
            candidates.append((number, row))

    if not candidates:
        return {
            "target": target,
            "count": 0,
            "distinct_count": 0,
            "lower": None,
            "upper": None,
            "exact": False,
            "exact_match": None,
        }

    candidates.sort(key=lambda item: item[0])
    tolerance = max(1e-9, abs(target) * 1e-9)

    lower_items = [item for item in candidates if item[0] < target - tolerance]
    upper_items = [item for item in candidates if item[0] > target + tolerance]
    exact_items = [item for item in candidates if math.isclose(item[0], target, rel_tol=1e-9, abs_tol=tolerance)]

    lo = max(lower_items, key=lambda item: item[0]) if lower_items else None
    hi = min(upper_items, key=lambda item: item[0]) if upper_items else None
    exact_item = exact_items[0] if exact_items else None

    def pack(item):
        if not item:
            return None
        number, row = item
        return {
            "value": number,
            "distance": abs(number - target),
            "row": row,
        }

    distinct_values = {number for number, _ in candidates}
    return {
        "target": target,
        "count": len(candidates),
        "distinct_count": len(distinct_values),
        "lower": pack(lo),
        "upper": pack(hi),
        "exact": bool(exact_item),
        "exact_match": pack(exact_item),
    }


def register_industria_routes(bp) -> None:
    @bp.route("/industria", methods=["GET"], endpoint="industria_index")
    def industria_index():
        counts = {slug: len(_load(section)) for slug, section in SECTIONS.items()}
        return render_template(
            "industria/index.html",
            sections=SECTIONS,
            counts=counts,
            industria_page=True,
            meta={},
        )

    @bp.route("/industria/<slug>", methods=["GET"], endpoint="industria_section")
    def industria_section(slug: str):
        section = SECTIONS.get(slug)
        if not section:
            return redirect(url_for("industria.industria_index"))

        if slug == "cb-matriz":
            all_rows = _load(section)
            input_tables = []
            for field in section.fields:
                table_rows = [row for row in all_rows if _text(row.get(field.key))]
                input_tables.append({"field": field, "rows": table_rows})
            return render_template(
                "industria/datos_entrada.html",
                section=section,
                input_tables=input_tables,
                total_rows=len(all_rows),
                industria_page=True,
                meta={},
            )

        all_rows = _load(section)
        rows = list(all_rows)
        q = request.args.get("q", "").strip()

        proximity_counts = _proximity_counts(all_rows) if slug == "cs" else {}
        available_numeric_fields = (
            {key: label for key, label in NUMERIC_CS_FIELDS.items() if proximity_counts.get(key, 0) > 0}
            if slug == "cs"
            else {}
        )

        proximity_field = ""
        proximity_value = ""
        proximity_active = False
        proximity_exact = False
        proximity_exact_ids: set[str] = set()

        if slug == "cs":
            proximity_field = request.args.get("prox_criterio", "").strip()
            proximity_value = request.args.get("prox_valor", "").strip()
            if proximity_field and proximity_value:
                if proximity_field in available_numeric_fields:
                    try:
                        target = float(proximity_value.replace(",", "."))
                        if not math.isfinite(target):
                            raise ValueError
                        result = _proximity(all_rows, proximity_field, target)
                        keep_values: list[float] = []
                        if result.get("lower"):
                            keep_values.append(float(result["lower"]["value"]))
                        if result.get("exact_match"):
                            keep_values.append(float(result["exact_match"]["value"]))
                        if result.get("upper"):
                            keep_values.append(float(result["upper"]["value"]))

                        tolerance = max(1e-9, abs(target) * 1e-9)
                        filtered_rows: list[dict[str, str]] = []
                        for row in all_rows:
                            number = _simple_numeric(row.get(proximity_field))
                            if number is None:
                                continue
                            if any(math.isclose(number, value, rel_tol=1e-9, abs_tol=tolerance) for value in keep_values):
                                filtered_rows.append(row)
                            if math.isclose(number, target, rel_tol=1e-9, abs_tol=tolerance):
                                proximity_exact_ids.add(_text(row.get("id")))

                        rows = sorted(
                            filtered_rows,
                            key=lambda row: (_simple_numeric(row.get(proximity_field)) is None, _simple_numeric(row.get(proximity_field)) or 0.0),
                        )
                        proximity_active = True
                        proximity_exact = bool(proximity_exact_ids)
                    except ValueError:
                        flash("Ingresa un valor numerico valido para la busqueda de proximidad.", "error")
                else:
                    flash("El criterio seleccionado no tiene valores numericos disponibles.", "error")

        if q:
            nq = _norm(q)
            rows = [r for r in rows if nq in _norm(" ".join(_text(r.get(f.key)) for f in section.fields))]

        # Código de equipos contiene miles de registros. Se pagina para mantener
        # la tabla ágil sin cambiar el comportamiento de los demás catálogos.
        total_rows = len(rows)
        pagination_enabled = slug == "codigo-equipos"
        page_size = 150 if pagination_enabled else max(total_rows, 1)
        try:
            page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            page = 1
        total_pages = max(1, math.ceil(total_rows / page_size)) if pagination_enabled else 1
        if page > total_pages:
            page = total_pages
        if pagination_enabled:
            start = (page - 1) * page_size
            rows = rows[start:start + page_size]

        template = "industria/cs.html" if slug == "cs" else "industria/section.html"
        return render_template(
            template,
            section=section,
            rows=rows,
            q=q,
            numeric_fields=available_numeric_fields,
            proximity_counts=proximity_counts,
            proximity_field=proximity_field,
            proximity_value=proximity_value,
            proximity_active=proximity_active,
            proximity_exact=proximity_exact,
            proximity_exact_ids=proximity_exact_ids,
            total_rows=total_rows,
            pagination_enabled=pagination_enabled,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            industria_page=True,
            meta={},
        )

    @bp.route(
        "/industria/cb-matriz/<field_key>/guardar",
        methods=["POST"],
        endpoint="industria_cb_save",
    )
    def industria_cb_save(field_key: str):
        section = SECTIONS["cb-matriz"]
        field = _cb_field(section, field_key)
        if field is None:
            return redirect(url_for("industria.industria_section", slug="cb-matriz"))
        value = _text(request.form.get("value"))
        if not value:
            flash("Completa el valor antes de guardar.", "error")
            return redirect(url_for("industria.industria_section", slug="cb-matriz"))

        with _LOCK:
            rows = _load(section)
            if any(_norm(row.get(field_key)) == _norm(value) for row in rows if _text(row.get(field_key))):
                flash(f"El valor ya existe en {field.label}.", "error")
            else:
                new_row = {f.key: "" for f in section.fields}
                new_row[field_key] = value
                new_row["id"] = uuid.uuid4().hex
                rows.append(new_row)
                _atomic_save(section, rows)
                flash("Registro agregado correctamente.", "success")
        return redirect(url_for("industria.industria_section", slug="cb-matriz"))

    @bp.route(
        "/industria/cb-matriz/<field_key>/<row_id>/editar",
        methods=["POST"],
        endpoint="industria_cb_edit",
    )
    def industria_cb_edit(field_key: str, row_id: str):
        section = SECTIONS["cb-matriz"]
        field = _cb_field(section, field_key)
        if field is None:
            return redirect(url_for("industria.industria_section", slug="cb-matriz"))
        value = _text(request.form.get("value"))
        if not value:
            flash("El valor no puede quedar vacío.", "error")
            return redirect(url_for("industria.industria_section", slug="cb-matriz"))

        with _LOCK:
            rows = _load(section)
            target = next((row for row in rows if row.get("id") == row_id and _text(row.get(field_key))), None)
            if target is None:
                flash("No se encontró el registro.", "error")
            elif any(
                row.get("id") != row_id and _norm(row.get(field_key)) == _norm(value)
                for row in rows
                if _text(row.get(field_key))
            ):
                flash(f"El valor ya existe en {field.label}.", "error")
            else:
                for item_field in section.fields:
                    target[item_field.key] = ""
                target[field_key] = value
                _atomic_save(section, rows)
                flash("Registro actualizado.", "success")
        return redirect(url_for("industria.industria_section", slug="cb-matriz"))

    @bp.route(
        "/industria/cb-matriz/<field_key>/<row_id>/eliminar",
        methods=["POST"],
        endpoint="industria_cb_delete",
    )
    def industria_cb_delete(field_key: str, row_id: str):
        section = SECTIONS["cb-matriz"]
        field = _cb_field(section, field_key)
        if field is None:
            return redirect(url_for("industria.industria_section", slug="cb-matriz"))

        with _LOCK:
            rows = _load(section)
            new_rows = [
                row for row in rows
                if not (row.get("id") == row_id and _text(row.get(field_key)))
            ]
            if len(new_rows) == len(rows):
                flash("No se encontró el registro.", "error")
            else:
                _atomic_save(section, new_rows)
                flash("Registro eliminado.", "success")
        return redirect(url_for("industria.industria_section", slug="cb-matriz"))

    @bp.route(
        "/industria/cb-matriz/<field_key>/subida-masiva",
        methods=["POST"],
        endpoint="industria_cb_bulk",
    )
    def industria_cb_bulk(field_key: str):
        section = SECTIONS["cb-matriz"]
        field = _cb_field(section, field_key)
        if field is None:
            return redirect(url_for("industria.industria_section", slug="cb-matriz"))
        archivo = request.files.get("archivo")
        mode = request.form.get("mode", "replace")
        if not archivo or not archivo.filename:
            flash("Selecciona un archivo Excel.", "error")
            return redirect(url_for("industria.industria_section", slug="cb-matriz"))

        try:
            incoming_values = _parse_cb_single_field(section, field_key, archivo)
            if not incoming_values:
                raise ValueError(f"No se encontraron valores para {field.label}.")

            unique_values: list[str] = []
            seen: set[str] = set()
            for value in incoming_values:
                key = _norm(value)
                if key and key not in seen:
                    seen.add(key)
                    unique_values.append(value)

            with _LOCK:
                rows = _load(section)
                if mode == "merge":
                    existing = {_norm(row.get(field_key)) for row in rows if _text(row.get(field_key))}
                    added = 0
                    for value in unique_values:
                        if _norm(value) in existing:
                            continue
                        new_row = {f.key: "" for f in section.fields}
                        new_row[field_key] = value
                        new_row["id"] = uuid.uuid4().hex
                        rows.append(new_row)
                        existing.add(_norm(value))
                        added += 1
                    _atomic_save(section, rows)
                    flash(f"Carga completada: se agregaron {added} registro(s) a {field.label}.", "success")
                else:
                    rows = [row for row in rows if not _text(row.get(field_key))]
                    for value in unique_values:
                        new_row = {f.key: "" for f in section.fields}
                        new_row[field_key] = value
                        new_row["id"] = uuid.uuid4().hex
                        rows.append(new_row)
                    _atomic_save(section, rows)
                    flash(f"{field.label}: {len(unique_values)} registros cargados.", "success")
        except Exception as exc:
            flash(f"No fue posible importar {field.label}: {exc}", "error")

        return redirect(url_for("industria.industria_section", slug="cb-matriz"))

    @bp.route(
        "/industria/cb-matriz/<field_key>/exportar-excel",
        methods=["GET"],
        endpoint="industria_cb_export",
    )
    def industria_cb_export(field_key: str):
        section = SECTIONS["cb-matriz"]
        field = _cb_field(section, field_key)
        if field is None:
            return redirect(url_for("industria.industria_section", slug="cb-matriz"))

        rows = [row for row in _load(section) if _text(row.get(field_key))]
        output = BytesIO()
        wb = Workbook()
        ws = wb.active
        ws.title = field.label[:31]
        ws.append([field.label])
        for row in rows:
            ws.append([_text(row.get(field_key))])
        ws.freeze_panes = "A2"
        ws.column_dimensions["A"].width = min(max(len(field.label) + 4, 24), 48)
        wb.save(output)
        wb.close()
        output.seek(0)
        return send_file(
            output,
            as_attachment=True,
            download_name=CB_EXPORT_NAMES[field_key],
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @bp.route("/industria/<slug>/guardar", methods=["POST"], endpoint="industria_save")
    def industria_save(slug: str):
        section = SECTIONS.get(slug)
        if not section:
            return redirect(url_for("industria.industria_index"))
        new_row = {f.key: _text(request.form.get(f.key)) for f in section.fields}
        if not any(new_row.values()):
            flash("Completa al menos un campo antes de guardar.", "error")
            return redirect(url_for("industria.industria_section", slug=slug))
        new_row["id"] = uuid.uuid4().hex
        with _LOCK:
            rows = _load(section)
            rows.append(new_row)
            _atomic_save(section, rows)
        flash("Registro agregado correctamente.", "success")
        return redirect(url_for("industria.industria_section", slug=slug))

    @bp.route("/industria/<slug>/<row_id>/editar", methods=["POST"], endpoint="industria_edit")
    def industria_edit(slug: str, row_id: str):
        section = SECTIONS.get(slug)
        if not section:
            return redirect(url_for("industria.industria_index"))
        with _LOCK:
            rows = _load(section)
            target = next((r for r in rows if r.get("id") == row_id), None)
            if target is None:
                flash("No se encontró el registro.", "error")
            else:
                for field in section.fields:
                    target[field.key] = _text(request.form.get(field.key))
                _atomic_save(section, rows)
                flash("Registro actualizado.", "success")
        return redirect(url_for("industria.industria_section", slug=slug))

    @bp.route("/industria/<slug>/<row_id>/eliminar", methods=["POST"], endpoint="industria_delete")
    def industria_delete(slug: str, row_id: str):
        section = SECTIONS.get(slug)
        if not section:
            return redirect(url_for("industria.industria_index"))
        with _LOCK:
            rows = _load(section)
            new_rows = [r for r in rows if r.get("id") != row_id]
            if len(rows) == len(new_rows):
                flash("No se encontró el registro.", "error")
            else:
                _atomic_save(section, new_rows)
                flash("Registro eliminado.", "success")
        return redirect(url_for("industria.industria_section", slug=slug))

    @bp.route(
        "/industria/<slug>/<row_id>/<field_key>/editar-campo",
        methods=["POST"],
        endpoint="industria_field_edit",
    )
    def industria_field_edit(slug: str, row_id: str, field_key: str):
        section = SECTIONS.get(slug)
        allowed_fields = {"tipo_origen", "tipo_destino"}
        if not section or slug != "puntos-origen" or field_key not in allowed_fields:
            return redirect(url_for("industria.industria_index"))

        value = _text(request.form.get("value"))
        with _LOCK:
            rows = _load(section)
            target = next((r for r in rows if r.get("id") == row_id), None)
            if target is None:
                flash("No se encontró el registro.", "error")
            else:
                target[field_key] = value
                _atomic_save(section, rows)
                label = "Punto de origen" if field_key == "tipo_origen" else "Punto de destino"
                flash(f"{label} actualizado.", "success")
        return redirect(url_for("industria.industria_section", slug=slug))

    @bp.route(
        "/industria/<slug>/<row_id>/<field_key>/eliminar-campo",
        methods=["POST"],
        endpoint="industria_field_delete",
    )
    def industria_field_delete(slug: str, row_id: str, field_key: str):
        section = SECTIONS.get(slug)
        allowed_fields = {"tipo_origen", "tipo_destino"}
        if not section or slug != "puntos-origen" or field_key not in allowed_fields:
            return redirect(url_for("industria.industria_index"))

        with _LOCK:
            rows = _load(section)
            target = next((r for r in rows if r.get("id") == row_id), None)
            if target is None:
                flash("No se encontró el registro.", "error")
            else:
                target[field_key] = ""
                # Si al borrar una de las dos columnas la fila queda totalmente
                # vacía, retiramos la fila completa para no dejar registros huérfanos.
                if not _text(target.get("tipo_origen")) and not _text(target.get("tipo_destino")):
                    rows = [r for r in rows if r.get("id") != row_id]
                _atomic_save(section, rows)
                label = "Punto de origen" if field_key == "tipo_origen" else "Punto de destino"
                flash(f"{label} eliminado.", "success")
        return redirect(url_for("industria.industria_section", slug=slug))

    @bp.route("/industria/<slug>/subida-masiva", methods=["POST"], endpoint="industria_bulk")
    def industria_bulk(slug: str):
        section = SECTIONS.get(slug)
        if not section:
            return redirect(url_for("industria.industria_index"))
        archivo = request.files.get("archivo")
        mode = request.form.get("mode", "replace")
        if not archivo or not archivo.filename:
            flash("Selecciona un archivo Excel.", "error")
            return redirect(url_for("industria.industria_section", slug=slug))
        try:
            incoming = _parse_source(section, archivo)
            if not incoming:
                raise ValueError(f"La hoja {section.sheet} no contiene registros para importar.")
            with _LOCK:
                if mode == "merge":
                    rows, added, updated = _merge(section, _load(section), incoming)
                    _atomic_save(section, rows)
                    flash(f"Carga completada: {added} registros agregados y {updated} actualizados.", "success")
                else:
                    _atomic_save(section, incoming)
                    flash(f"Catálogo reemplazado correctamente: {len(incoming)} registros cargados.", "success")
        except Exception as exc:
            flash(f"No fue posible importar {section.title}: {exc}", "error")
        return redirect(url_for("industria.industria_section", slug=slug))

    @bp.route("/industria/<slug>/exportar-excel", methods=["GET"], endpoint="industria_export_excel")
    def industria_export_excel(slug: str):
        section = SECTIONS.get(slug)
        if not section:
            return redirect(url_for("industria.industria_index"))

        # Descarga siempre el catalogo completo que respalda el submodulo.
        # No depende de busquedas, proximidad ni paginacion de la pantalla.
        # Los catálogos simplificados se exportan exactamente como se ven en
        # pantalla, sin columnas históricas ni el identificador interno _OGA_ID.
        if slug in {"codigo-equipos", "puntos-origen"}:
            rows = _load(section)
            output = BytesIO()
            wb = Workbook()
            ws = wb.active
            ws.title = section.sheet[:31]
            ws.append([field.label for field in section.fields])
            for row in rows:
                ws.append([_text(row.get(field.key)) for field in section.fields])
            ws.freeze_panes = "A2"
            for idx, field in enumerate(section.fields, 1):
                ws.column_dimensions[ws.cell(1, idx).column_letter].width = min(max(len(field.label) + 3, 18), 42)
            wb.save(output)
            wb.close()
            output.seek(0)
            return send_file(
                output,
                as_attachment=True,
                download_name=section.filename,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        with _LOCK:
            _ensure(section)
            path = _path(section)

        return send_file(
            path,
            as_attachment=True,
            download_name=section.filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            conditional=True,
        )

    @bp.route("/industria/cs/proximidad", methods=["GET"], endpoint="industria_cs_proximity")
    def industria_cs_proximity():
        field = request.args.get("criterio", "")
        raw_value = request.args.get("valor", "")
        if field not in NUMERIC_CS_FIELDS:
            return jsonify({"ok": False, "error": "Criterio numérico no válido."}), 400
        try:
            target = float(raw_value.replace(",", "."))
            if not math.isfinite(target):
                raise ValueError
        except (ValueError, AttributeError):
            return jsonify({"ok": False, "error": "Ingresa un valor numérico válido."}), 400
        result = _proximity(_load(SECTIONS["cs"]), field, target)
        result.update({
            "ok": True,
            "criterion": field,
            "criterion_label": NUMERIC_CS_FIELDS[field],
            "unit": CS_FIELD_UNITS.get(field, ""),
        })
        return jsonify(result)


register_industria_routes(bp)
