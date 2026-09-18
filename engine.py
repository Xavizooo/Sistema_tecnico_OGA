from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
import math
import os
import re

from openpyxl import load_workbook

from storage import (
    MASTER_FILE, CONFIG_FILE, HOLIDAYS_FILE, get_work_dir,
    clean_code, normalize_text, safe_float, read_rows, write_rows
)

MASTER_REQUIRED = [
    "CODIGO", "NOMBRE", "U", "ULT.COSTO", "REPUESTO", "TIPO DE REPUESTO",
    "FRECUENCIA DE CAMBIO", "REPUESTO DERIVADO", "DESCRIPCION DE LOS REPUESTOS ASOCIADOS",
    "TIPO", "NOTA", "DESCRIPCION DE LA NOTA", "REGLA"
]

_MASTER_CACHE = {"mtime": None, "rows": [], "map": {}, "rules": {}}

FIXED_RULES = {
    "1": "PERFIL / TRAMOS DE 6 m — Longitud de la descripción + 10 mm por pieza; consolidar, convertir a metros y redondear hacia arriba a tramos comerciales de 6 m.",
    "2": "REDONDOS — Longitud de la descripción + 5 mm por pieza; consolidar en metros y conservar el desglose de cortes en la nota.",
    "3": "CANTIDAD ÷ 2 — Sumar la cantidad total requerida y dividirla entre 2.",
    "4": "LÁMINA 4 × 8 FT — Sumar el área de las piezas y dividirla entre 2,97 m².",
    "5": "LÁMINA 5 × 10 FT — Sumar el área de las piezas y dividirla entre 4,645 m².",
    "6": "LÁMINA 5 × 20 FT — Sumar el área de las piezas y dividirla entre 9,290 m².",
    "7": "LÁMINA 1 × 3 m — Sumar el área de las piezas y dividirla entre 3,00 m².",
    "8": "MATERIAL LINEAL — Longitud de la descripción + 10 mm por pieza y consolidación en metros, sin asumir una longitud comercial fija.",
}

# Divisores de área/longitud usados para consolidar por lote en rq_proposal().
SHEET_RULE_DIVISORS = {"4": 2.97, "5": 4.645, "6": 9.290, "7": 3.00}
PROFILE_RULE_DIVISOR = {"1": 6.0}
METER_UNITS = {"M", "MT", "MTS", "METRO", "METROS"}


def _norm_header(v):
    return normalize_text(v).replace("  ", " ").strip()


def _strip_header(v):
    return _norm_header(v).replace(" ", "")


def _canon_master_header(v):
    n = _norm_header(v)
    aliases = {
        "REPUESTO ": "REPUESTO",
        "TIPO DE REPUESTO ": "TIPO DE REPUESTO",
        "FRECUENCIA DE CAMBIO ": "FRECUENCIA DE CAMBIO",
        "REPUESTO DERIVADO  ": "REPUESTO DERIVADO",
        "TIPO ": "TIPO",
        "NOTA ": "NOTA",
        "REGLA ": "REGLA",
    }
    return aliases.get(n, n)


def invalidate_master_cache():
    _MASTER_CACHE["mtime"] = None


def load_master(force=False):
    if not MASTER_FILE.exists():
        return [], {}, {}
    mtime = MASTER_FILE.stat().st_mtime_ns
    if not force and _MASTER_CACHE["mtime"] == mtime:
        return _MASTER_CACHE["rows"], _MASTER_CACHE["map"], _MASTER_CACHE["rules"]

    wb = load_workbook(MASTER_FILE, data_only=True, read_only=True)
    ws = wb.active
    headers = [_canon_master_header(c.value) for c in ws[1]][:13]
    rows = []
    for excel_row, r in enumerate(ws.iter_rows(min_row=2, min_col=1, max_col=13, values_only=True), start=2):
        code = clean_code(r[0] if len(r) else "")
        if not code:
            # main master table ends when code column becomes blank
            continue
        rec = {}
        for i, h in enumerate(headers):
            rec[h] = r[i] if i < len(r) else ""
        rec["CODIGO"] = code
        rec["NOMBRE"] = str(rec.get("NOMBRE") or "").strip()
        rec["U"] = str(rec.get("U") or "").strip()
        # La vista siempre normaliza la nomenclatura nueva, incluso si se carga un maestro antiguo.
        tr = normalize_text(rec.get("TIPO DE REPUESTO"))
        rec["TIPO DE REPUESTO"] = ({"CRITICO": "CR", "CRÍTICO": "CR", "IMPORTANTE": "IM", "BAJA ROTACION": "BR", "BAJA ROTACIÓN": "BR"}.get(tr, tr or "NO"))
        fr = normalize_text(rec.get("FRECUENCIA DE CAMBIO"))
        rec["FRECUENCIA DE CAMBIO"] = ({"FRECUENTE": "FA", "OCACIONAL": "FM", "OCASIONAL": "FM", "POCO FRECUENTE": "FB", "FRECUENCIA ALTA": "FA", "FRECUENCIA MEDIA": "FM", "FRECUENCIA BAJA": "FB"}.get(fr, fr or "NO"))
        rec["REGLA"] = clean_code(rec.get("REGLA")) if normalize_text(rec.get("REGLA")) not in {"", "NO"} else "NO"
        if rec["REGLA"] == "NO":
            # La columna REGLA vino vacia: intenta deducirla del formato
            # comercial escrito en el propio NOMBRE (ver infer_rule_from_name).
            inferred = infer_rule_from_name(rec.get("NOMBRE"), rec.get("U"))
            if inferred:
                rec["REGLA"] = inferred
                rec["REGLA_ORIGEN"] = "INFERIDA DE NOMBRE"
        rec["UBICACION"] = excel_row
        rows.append(rec)

    rules = FIXED_RULES.copy()
    wb.close()

    mp = {r["CODIGO"]: r for r in rows}
    _MASTER_CACHE.update({"mtime": mtime, "rows": rows, "map": mp, "rules": rules})
    return rows, mp, rules


def validate_master_file(path: Path):
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb.active
    headers = [_canon_master_header(c.value) for c in ws[1]][:13]
    wb.close()
    missing = [h for h in MASTER_REQUIRED if h not in headers]
    return missing


def append_master_code(values: dict):
    wb = load_workbook(MASTER_FILE)
    ws = wb.active
    # find first empty row in code column after data begins
    row = 2
    while ws.cell(row, 1).value not in (None, ""):
        row += 1
    ordered = MASTER_REQUIRED
    for col, h in enumerate(ordered, 1):
        ws.cell(row, col).value = values.get(h, "")
        if row > 2:
            src = ws.cell(row - 1, col)
            dst = ws.cell(row, col)
            if src.has_style:
                from copy import copy
                dst._style = copy(src._style)
                dst.number_format = src.number_format
                dst.alignment = copy(src.alignment)
                dst.font = copy(src.font)
                dst.fill = copy(src.fill)
                dst.border = copy(src.border)
    wb.save(MASTER_FILE)
    invalidate_master_cache()


def read_matrix(path: Path):
    ext = path.suffix.lower()
    if ext == ".xls":
        try:
            import xlrd
        except ImportError as e:
            raise RuntimeError("No fue posible leer el archivo .XLS porque falta la librería xlrd. Ejecute el programa con F5 para que el entorno se prepare automáticamente.") from e
        book = xlrd.open_workbook(str(path))
        sh = book.sheet_by_index(0)
        return [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb.active
    matrix = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return matrix


def find_header_row(matrix, required_aliases: dict, max_scan=80):
    for ridx, row in enumerate(matrix[:max_scan]):
        norm = [_norm_header(v) for v in row]
        mapping = {}
        for key, aliases in required_aliases.items():
            for i, val in enumerate(norm):
                if val in {_norm_header(a) for a in aliases}:
                    mapping[key] = i
                    break
        if set(required_aliases).issubset(mapping):
            return ridx, mapping
    return None, {}


def parse_inventor(path: Path):
    matrix = read_matrix(path)
    aliases = {
        "item": ["ITEM"],
        "filename": ["FILENAME", "FILE NAME"],
        "part": ["PART NUMBER", "PART_NUMBER"],
        "description": ["DESCRIPTION", "DESCRIPCION"],
        "stock": ["STOCK NUMBER", "STOCK_NUMBER"],
        "qty": ["ITEM QTY", "ITEM_QTY"],
    }
    hrow, m = find_header_row(matrix, aliases)
    if hrow is None:
        raise ValueError("La lista de Inventor debe contener: ITEM, FILENAME, PART NUMBER, DESCRIPTION, STOCK NUMBER e ITEM QTY.")
    out = []
    for row in matrix[hrow + 1:]:
        if not any(v not in (None, "") for v in row):
            continue
        code = clean_code(row[m["stock"]] if m["stock"] < len(row) else "")
        if not code:
            continue
        out.append({
            "ITEM": row[m["item"]] if m["item"] < len(row) else "",
            "FILENAME": row[m["filename"]] if m["filename"] < len(row) else "",
            "PART NUMBER": row[m["part"]] if m["part"] < len(row) else "",
            "DESCRIPTION": str(row[m["description"]] or "") if m["description"] < len(row) else "",
            "STOCK NUMBER": code,
            "ITEM QTY": safe_float(row[m["qty"]] if m["qty"] < len(row) else 0),
        })
    return out


def parse_b1(path: Path):
    matrix = read_matrix(path)
    aliases = {
        "code": ["CODIGO", "CÓDIGO"],
        "name": ["NOMBRE"],
        "unit": ["UD", "U", "UNIDAD"],
        "stock": ["EXISTENCIA", "EXISTENCIAS", "EXIST"],
    }
    hrow, m = find_header_row(matrix, aliases)
    if hrow is None:
        raise ValueError("No se encontraron las columnas CODIGO, NOMBRE, UD y EXISTENCIA en el archivo B1.")
    grouped = {}
    order = []
    for row in matrix[hrow + 1:]:
        code = clean_code(row[m["code"]] if m["code"] < len(row) else "")
        # B1 solo admite códigos Factory formados exclusivamente por números.
        # Esto elimina encabezados repetidos, nombres de empresa, títulos y cualquier símbolo/letra.
        if not re.fullmatch(r"\d+", code):
            continue
        name = str(row[m["name"]] or "").strip() if m["name"] < len(row) else ""
        unit = str(row[m["unit"]] or "").strip() if m["unit"] < len(row) else ""
        stock = safe_float(row[m["stock"]] if m["stock"] < len(row) else 0)
        if code not in grouped:
            grouped[code] = {"CODIGO": code, "NOMBRE": name, "UD": unit, "EXISTENCIA": 0.0}
            order.append(code)
        grouped[code]["EXISTENCIA"] += stock
        if not grouped[code]["NOMBRE"] and name:
            grouped[code]["NOMBRE"] = name
        if not grouped[code]["UD"] and unit:
            grouped[code]["UD"] = unit
    return [grouped[c] for c in order]


def parse_code_qty(path: Path):
    matrix = read_matrix(path)
    aliases = {
        "code": ["CODIGO", "CÓDIGO", "CODIGO FACTORY", "CODIGO_FACTORY", "STOCK NUMBER", "STOCK_NUMBER"],
        "qty": ["CANTIDAD", "QTY", "ITEM QTY", "ITEM_QTY", "EXISTENCIA"],
    }
    hrow, m = find_header_row(matrix, aliases)
    if hrow is None:
        raise ValueError("No se detectaron las columnas de Código y Cantidad.")
    out = []
    for row in matrix[hrow + 1:]:
        code = clean_code(row[m["code"]] if m["code"] < len(row) else "")
        if not code:
            continue
        out.append({"CODIGO": code, "CANTIDAD": safe_float(row[m["qty"]] if m["qty"] < len(row) else 0)})
    return out


def parse_lge_excel(path: Path):
    """Lee el listado superior de equipos exportado desde Inventor.

    Columnas esperadas: PART NUMBER, DESCRIPTION, STOCK NUMBER, ITEM QTY.
    El código del equipo se toma de STOCK NUMBER; si está vacío, usa PART NUMBER.
    Códigos alfanuméricos son válidos aquí porque son identificadores de equipo, no códigos Factory.
    """
    matrix = read_matrix(path)
    aliases = {
        "part": ["PART NUMBER", "PART_NUMBER"],
        "description": ["DESCRIPTION", "DESCRIPCION"],
        "stock": ["STOCK NUMBER", "STOCK_NUMBER"],
        "qty": ["ITEM QTY", "ITEM_QTY", "QTY", "CANTIDAD"],
    }
    hrow, m = find_header_row(matrix, aliases)
    if hrow is None:
        raise ValueError("El listado de equipos debe contener: PART NUMBER, DESCRIPTION, STOCK NUMBER e ITEM QTY.")

    grouped = {}
    order = []
    for row in matrix[hrow + 1:]:
        if not any(v not in (None, "") for v in row):
            continue
        part = clean_code(row[m["part"]] if m["part"] < len(row) else "")
        stock = clean_code(row[m["stock"]] if m["stock"] < len(row) else "")
        code = stock or part
        desc = str(row[m["description"]] or "").strip() if m["description"] < len(row) else ""
        qty = safe_float(row[m["qty"]] if m["qty"] < len(row) else 0, 0)
        if not code or qty <= 0:
            continue
        key = (code, desc)
        if key not in grouped:
            grouped[key] = {
                "CODIGO": code,
                "CANTIDAD": 0.0,
                "DESCRIPCION": desc,
                "PART NUMBER": part,
                "ARCHIVO": "",
            }
            order.append(key)
        grouped[key]["CANTIDAD"] += qty
    return [grouped[k] for k in order]

def extract_length_mm(desc: str, material_name: str = ""):
    """Obtiene la longitud de corte expresada en milímetros.

    Inventor no usa una sola escritura: en los archivos reales aparecen
    ``L=125``, ``L-100,0 mm``, ``L: 2.5 m`` y variantes equivalentes. Cuando
    no se indica unidad se interpreta milímetro, que es la convención de las
    descripciones de fabricación del proyecto.

    Los redondos de nylon antiguos son una excepción conocida: su longitud
    quedó al final como ``Ø3 X 40`` o ``CREMA-17 mm``. Ese formato solo se
    acepta si la referencia maestra realmente es un REDONDO, para no tomar
    por error las dimensiones de sección de un tubo o perfil.
    """
    s = str(desc or "").upper().replace(",", ".").strip()

    def to_mm(value, unit):
        number = float(value)
        unit = str(unit or "MM").upper()
        if unit == "M":
            return number * 1000.0
        if unit == "CM":
            return number * 10.0
        return number

    patterns = [
        r"\bL(?:ARGO|ONGITUD)?\s*(?:[-:=]\s*|\s+)(\d+(?:\.\d+)?)\s*(MM|CM|M)?\b",
        r"\b(\d+(?:\.\d+)?)\s*MM\s*(?:LARGO|LONG)\b",
    ]
    for p in patterns:
        m = re.search(p, s)
        if m:
            unit = m.group(2) if m.lastindex and m.lastindex >= 2 else "MM"
            return to_mm(m.group(1), unit)

    if "REDONDO" in normalize_text(material_name):
        legacy_patterns = [
            r"\bX\s*(\d+(?:\.\d+)?)\s*(MM|CM|M)?\s*$",
            r"-\s*(\d+(?:\.\d+)?)\s*(MM|CM|M)\s*$",
        ]
        for p in legacy_patterns:
            m = re.search(p, s)
            if m:
                return to_mm(m.group(1), m.group(2))
    return None


def extract_dims_mm(desc: str):
    s = str(desc or "").upper().replace(",", ".").replace("×", "X")
    candidates = re.findall(r"(\d+(?:\.\d+)?)\s*(?:MM)?\s*X\s*(\d+(?:\.\d+)?)\s*(?:MM)?", s)
    if not candidates:
        return None
    # Use the pair with the largest area; this avoids choosing small section sizes when a sheet part also has L x W.
    pairs = [(float(a), float(b)) for a, b in candidates]
    return max(pairs, key=lambda t: t[0] * t[1])


# ---------------------------------------------------------------------------
# Identificacion automatica de lote de material (a partir de NOMBRE)
#
# No requiere ninguna columna nueva en el Excel maestro. Se usa unicamente
# para agrupar, en rq_proposal(), codigos DISTINTOS que en la practica se
# compran del mismo lote de lamina/perfil (mismo material + acabado +
# espesor + formato comercial). Si no logra identificar espesor Y
# dimension con confianza, el codigo se compra solo (comportamiento seguro
# por defecto: nunca agrupa mal por error).
# ---------------------------------------------------------------------------

_ESP_PATTERN = re.compile(r"ESP\.?\s*([0-9]+/[0-9]+|[0-9]+(?:\.[0-9]+)?)\s*\"?")
_CAL_PATTERN = re.compile(r"\bCAL\.?\s*([0-9]+)\b")
_SHEET_DIM_PATTERN = re.compile(
    r"([0-9]+(?:\.[0-9]+)?)\s*(FT|M)\s*X\s*([0-9]+(?:\.[0-9]+)?)\s*(FT|M)"
)
_FINISH_KEYWORDS = ["ALFAJOR", "A36", "HR", "CR", "GALVANIZAD", "INOX", "ACERADA"]


def parse_sheet_material_key(name: str):
    """Deriva un identificador de lote (material+acabado+espesor+dimension)
    directamente del texto de NOMBRE, sin tocar el Excel maestro.
    Devuelve None si no logra identificar espesor Y dimension con confianza."""
    s = normalize_text(name)
    if "LAMINA" not in s and "LÁMINA" not in s:
        return None

    esp = None
    m = _ESP_PATTERN.search(s)
    if m:
        esp = m.group(1)
    else:
        m2 = _CAL_PATTERN.search(s)
        if m2:
            esp = f"CAL{m2.group(1)}"

    dim = None
    md = _SHEET_DIM_PATTERN.search(s)
    if md:
        dim = f"{md.group(1)}{md.group(2)}X{md.group(3)}{md.group(4)}"

    if not esp or not dim:
        return None

    finish = next((f for f in _FINISH_KEYWORDS if f in s), "")
    return f"LAM|{finish}|{esp}|{dim}"


# ---------------------------------------------------------------------------
# Inferencia automatica de REGLA a partir de NOMBRE cuando la columna REGLA
# del maestro esta vacia. Para laminas solo reconoce formatos comerciales
# estandar con divisor fijo. Para materiales lineales exige que la unidad
# maestra sea M y reconoce familias con un tratamiento inequívoco.
# ---------------------------------------------------------------------------

_MULT_SIGN = r"[X\*×]"

_STANDARD_SHEET_FORMATS = [
    ("4", re.compile(rf"\b4\s*FT\s*{_MULT_SIGN}\s*8\s*FT\b|\b8\s*FT\s*{_MULT_SIGN}\s*4\s*FT\b")),
    ("5", re.compile(rf"\b5\s*FT\s*{_MULT_SIGN}\s*10\s*FT\b|\b10\s*FT\s*{_MULT_SIGN}\s*5\s*FT\b")),
    ("6", re.compile(rf"\b5\s*FT\s*{_MULT_SIGN}\s*20\s*FT\b|\b20\s*FT\s*{_MULT_SIGN}\s*5\s*FT\b")),
    ("7", re.compile(rf"\b1\s*M\s*{_MULT_SIGN}\s*3\s*M\b|\b3\s*M\s*{_MULT_SIGN}\s*1\s*M\b")),
]


def is_meter_unit(unit):
    return normalize_text(unit) in METER_UNITS


def infer_rule_from_name(name, unit=""):
    """Deduce reglas inequívocas a partir de NOMBRE y unidad maestra.

    Además de los formatos comerciales de lámina, reconoce familias de
    material lineal únicamente cuando el maestro las valora por metro. Los
    perfiles estructurales conservan su compra en tramos de 6 m, los redondos
    usan 5 mm de merma y los demás lineales usan 10 mm sin imponer un largo
    comercial que el nombre no garantiza.
    """
    s = normalize_text(name)
    for rule, pattern in _STANDARD_SHEET_FORMATS:
        if pattern.search(s):
            return rule

    if not is_meter_unit(unit):
        return None
    if re.search(r"\bREDONDO\b", s):
        return "2"
    if re.search(r"\b(?:PERFIL|VIGA|ANGULO|ÁNGULO|PLATINA)\b", s):
        return "1"
    if re.search(
        r"\b(?:TUBERIA|TUBERÍA|TUBO|TUBING|ESPARRAGO|ESPÁRRAGO)\b"
        r"|\bMANG(?:U(?:ERA)?)?\b"
        r"|\bEMP(?:AQUE)?\s+LINEA",
        s,
    ):
        return "8"
    return None


def material_group_key(code, name, rule):
    """Clave de agrupacion para rq_proposal(). Si no se puede identificar el
    material automaticamente (o la regla no es de lamina), cada codigo se
    compra por separado."""
    if rule in SHEET_RULE_DIVISORS:
        key = parse_sheet_material_key(name)
        if key:
            return key
    return f"__CODE__{code}"


# ---------------------------------------------------------------------------
# Presentacion comercial (caja/paquete) para accesorios / Categoria 0D
# (tornillos, arandelas, abrazaderas, etc. que la empresa NO fabrica).
# Se detecta del NOMBRE igual que la regla de lamina: sin tocar el Excel.
# Si no se detecta ninguna presentacion, el item se sigue comprando en
# unidades sueltas (comportamiento actual, sin cambios).
# ---------------------------------------------------------------------------

_PRESENTATION_PATTERNS = [
    re.compile(r"\bCAJA\s*X\s*(\d+)\b"),
    re.compile(r"\bCJA\s*X\s*(\d+)\b"),
    re.compile(r"\bPAQUETE\s*X\s*(\d+)\b"),
    re.compile(r"\bPAQ\s*X\s*(\d+)\b"),
    re.compile(r"\bBLISTER\s*X\s*(\d+)\b"),
    re.compile(r"\bX\s*(\d+)\s*UND\b"),
    re.compile(r"\(\s*X\s*(\d+)\s*\)"),
]


def parse_package_size(name):
    """Detecta la presentacion comercial (unidades por caja/paquete) desde
    el NOMBRE. Devuelve None si el item se compra suelto (sin presentacion
    fija) — en ese caso no se redondea a paquete, se pide la cantidad neta
    tal cual, como hoy."""
    s = normalize_text(name)
    for pattern in _PRESENTATION_PATTERNS:
        m = pattern.search(s)
        if m:
            return int(m.group(1))
    return None


def split_notes(raw):
    """Notas múltiples: el separador oficial es punto y coma (;). 'NO' equivale a sin nota."""
    text = str(raw or "").strip()
    if not text or normalize_text(text) == "NO":
        return []
    return [x.strip() for x in text.split(";") if x.strip() and normalize_text(x) != "NO"]


def split_associated_spares(raw):
    """Repuestos asociados separados por ';'. Tolera ',' solo para maestros antiguos."""
    text = str(raw or "").strip()
    if not text or normalize_text(text) == "NO":
        return []
    parts = text.split(";") if ";" in text else text.split(",")
    codes = []
    for part in parts:
        match = re.search(r"\b\d{5,15}\b", part)
        if match:
            codes.append(match.group(0))
    return codes


def spare_class(raw):
    n = normalize_text(raw)
    if n in {"CR", "CRITICO", "CRÍTICO"} or n.startswith("CRIT"):
        return "CR"
    if n in {"IM", "IMPORTANTE"} or n.startswith("IMPORT"):
        return "IM"
    if n in {"BR", "BAJA ROTACION", "BAJA ROTACIÓN"} or "BAJA ROT" in n:
        return "BR"
    return ""


def spare_frequency(raw):
    n = normalize_text(raw)
    if n in {"FA", "FRECUENCIA ALTA", "FRECUENTE", "ALTA"}:
        return "FA"
    if n in {"FM", "FRECUENCIA MEDIA", "OCACIONAL", "OCASIONAL", "MEDIA"}:
        return "FM"
    if n in {"FB", "FRECUENCIA BAJA", "POCO FRECUENTE", "BAJA"}:
        return "FB"
    return ""


def rule_usage(master: dict, desc: str, qty: float):
    rule = clean_code(master.get("REGLA")) if normalize_text(master.get("REGLA")) not in {"", "NO"} else "NO"
    unit = str(master.get("U") or "").strip()
    note_parts = []
    warning = ""
    length_mm = extract_length_mm(desc, master.get("NOMBRE"))
    area_m2 = None
    usage = qty

    # Respaldo para códigos por metro cuyo nombre todavía no pertenece a una
    # familia conocida. Una longitud L=... explícita sí basta para aplicar la
    # regla lineal sin depender de palabras clave.
    if rule == "NO" and is_meter_unit(unit) and length_mm is not None:
        rule = "8"

    # Evita que una regla lineal asignada por accidente a una referencia por
    # unidades (por ejemplo una abrazadera) borre su cantidad al no encontrar L.
    if rule in {"1", "2", "8"} and not is_meter_unit(unit):
        return {
            "REGLA": "NO", "UNIDAD": unit, "USO": qty, "LONGITUD_MM": None,
            "AREA_M2": None,
            "ADVERTENCIA": f"REGLA {rule} IGNORADA: LA UNIDAD MAESTRA NO ES M",
            "NOTA_EXTRA": "REVISAR REGLA EN LISTA MAESTRA",
        }

    if rule == "1":
        if length_mm is None:
            warning = "LONGITUD NO DETECTADA"
            usage = 0
        else:
            usage = ((length_mm + 10.0) / 1000.0) * qty
        unit = "M"
    elif rule == "2":
        if length_mm is None:
            warning = "LONGITUD NO DETECTADA"
            usage = 0
        else:
            usage = ((length_mm + 5.0) / 1000.0) * qty
        unit = "M"
    elif rule == "8":
        if length_mm is None:
            warning = "LONGITUD NO DETECTADA"
            usage = 0
        else:
            usage = ((length_mm + 10.0) / 1000.0) * qty
        unit = "M"
    elif rule == "3":
        usage = qty / 2.0
    elif rule in {"4", "5", "6", "7"}:
        dims = extract_dims_mm(desc)
        if not dims:
            warning = "DIMENSION LAMINA NO DETECTADA"
            usage = 0
        else:
            area_m2 = dims[0] * dims[1] / 1_000_000.0 * qty
            sheet_area = SHEET_RULE_DIVISORS[rule]
            usage = area_m2 / sheet_area
            unit = "Ud"
            note_parts.append("VERIFICAR TERMINADO")
    return {
        "REGLA": rule, "UNIDAD": unit, "USO": usage, "LONGITUD_MM": length_mm,
        "AREA_M2": area_m2, "ADVERTENCIA": warning, "NOTA_EXTRA": " | ".join(note_parts)
    }


def build_details(inventor_sources):
    _, master_map, _ = load_master()
    details = []
    for source in inventor_sources:
        rows = parse_inventor(Path(source["path"]))
        mult = safe_float(source.get("multiplier"), 1.0)
        eq = source.get("equipment", "GENERAL")
        for r in rows:
            raw_qty = safe_float(r["ITEM QTY"]) * mult
            code = clean_code(r["STOCK NUMBER"])
            valid = bool(re.fullmatch(r"\d+", code))
            master = master_map.get(code)
            status = "CORRECTO"
            calc = {"REGLA": "NO", "UNIDAD": "", "USO": raw_qty, "LONGITUD_MM": None, "AREA_M2": None, "ADVERTENCIA": "", "NOTA_EXTRA": ""}
            if not valid:
                status = "CODIGO INVALIDO"
            elif not master:
                status = "CODIGO NO EXISTENTE"
            else:
                calc = rule_usage(master, r["DESCRIPTION"], raw_qty)
                if calc["ADVERTENCIA"]:
                    status = calc["ADVERTENCIA"]
            details.append({
                "EQUIPO": eq,
                "ITEM": r["ITEM"],
                "FILENAME": r["FILENAME"],
                "PART NUMBER": r["PART NUMBER"],
                "DESCRIPTION": r["DESCRIPTION"],
                "STOCK NUMBER": code,
                "ITEM QTY": raw_qty,
                "REGLA": calc["REGLA"],
                "UNIDAD": calc["UNIDAD"],
                "CANTIDAD CALCULADA": round(safe_float(calc["USO"]), 6),
                "LONGITUD MM": calc["LONGITUD_MM"] if calc["LONGITUD_MM"] is not None else "",
                "AREA M2": round(calc["AREA_M2"], 6) if calc["AREA_M2"] is not None else "",
                "ESTADO CODIGO": status,
                "NOTA EXTRA": calc["NOTA_EXTRA"],
            })
    return details


def consolidate(details):
    _, master_map, _ = load_master()
    grp = {}
    rule2_lengths = defaultdict(lambda: defaultdict(float))
    for d in details:
        code = clean_code(d.get("STOCK NUMBER"))
        if not code:
            continue
        m = master_map.get(code, {})
        g = grp.setdefault(code, {
            "CODIGO": code,
            "NOMBRE": m.get("NOMBRE") or d.get("DESCRIPTION", ""),
            "UD": d.get("UNIDAD") or m.get("U", ""),
            "CANTIDAD": 0.0,
            "REGLA": d.get("REGLA", "NO"),
            "ADVERTENCIAS": set(),
            # La nota del maestro se propaga aqui para que LM tambien la muestre,
            # no solo RQ y REPUESTOS.
            "NOTA": "\n".join(split_notes(m.get("DESCRIPCION DE LA NOTA"))) if normalize_text(m.get("NOTA")) == "SI" else "",
        })
        g["CANTIDAD"] += safe_float(d.get("CANTIDAD CALCULADA"))
        st = normalize_text(d.get("ESTADO CODIGO"))
        if st != "CORRECTO":
            g["ADVERTENCIAS"].add(str(d.get("ESTADO CODIGO")))
        if str(d.get("REGLA")) == "2" and d.get("LONGITUD MM") not in (None, ""):
            cut = safe_float(d.get("LONGITUD MM")) + 5.0
            rule2_lengths[code][round(cut, 3)] += safe_float(d.get("ITEM QTY"))
    rows = []
    for code, g in sorted(grp.items()):
        note_rule = ""
        if g["REGLA"] == "1":
            # note generated on pending quantity after B1, but keep a base placeholder
            note_rule = "PERFIL / TRAMOS DE 6 m"
        elif g["REGLA"] == "2":
            parts = []
            for cut, qty in sorted(rule2_lengths[code].items()):
                parts.append(f"COMPRAR {qty:g} TRAMO(S) DE {cut:g} mm")
            note_rule = ", ".join(parts)
        elif g["REGLA"] == "8":
            note_rule = "MATERIAL LINEAL: LONGITUD NETA + 10 mm POR PIEZA"
        rows.append({
            "CODIGO": code, "NOMBRE": g["NOMBRE"], "UD": g["UD"],
            "CANTIDAD REQUERIDA": round(g["CANTIDAD"], 6),
            "REGLA": g["REGLA"], "NOTA REGLA": note_rule,
            "NOTA": g["NOTA"],
            "ADVERTENCIA": "; ".join(sorted(g["ADVERTENCIAS"]))
        })
    return rows


def trace_rows():
    return read_rows(get_work_dir() / "TRAZABILIDAD.xlsx")


def managed_by_code():
    sums = defaultdict(float)
    for r in trace_rows():
        if normalize_text(r.get("TIPO")) in {"MOV", "RQ"}:
            sums[clean_code(r.get("CODIGO"))] += safe_float(r.get("CANTIDAD"))
    return sums


def make_lm(consolidated):
    managed = managed_by_code()
    rows = []
    for r in consolidated:
        req = safe_float(r.get("CANTIDAD REQUERIDA"))
        ges = managed.get(clean_code(r.get("CODIGO")), 0.0)
        pend = max(0.0, req - ges)
        if r.get("ADVERTENCIA"):
            state = "CON INCONSISTENCIA"
        elif pend <= 1e-9:
            state = "GESTIONADO"
        elif ges > 0:
            state = "PARCIAL"
        else:
            state = "PENDIENTE"
        rows.append({**r, "GESTIONADO": round(ges, 6), "PENDIENTE": round(pend, 6), "ESTADO": state})
    return rows


def b1_rows():
    return read_rows(get_work_dir() / "B1_FILTRADO.xlsx")


def movement_proposal(lm):
    b1map = {clean_code(r.get("CODIGO")): r for r in b1_rows()}
    out = []
    for r in lm:
        code = clean_code(r.get("CODIGO"))
        pending = safe_float(r.get("PENDIENTE"))
        avail = safe_float(b1map.get(code, {}).get("EXISTENCIA"))
        qty = min(max(pending, 0), max(avail, 0))
        if qty > 1e-9:
            out.append({
                "CODIGO": code, "NOMBRE": r.get("NOMBRE"), "UD": r.get("UD"),
                "PENDIENTE": round(pending, 6), "EXISTENCIA B1": round(avail, 6),
                "MOV PROPUESTO": round(qty, 6)
            })
    return out


def config_map():
    return {normalize_text(r.get("CLAVE")): safe_float(r.get("VALOR")) for r in read_rows(CONFIG_FILE)}


def extra_holidays():
    out = set()
    for r in read_rows(HOLIDAYS_FILE):
        v = r.get("FECHA")
        if isinstance(v, datetime):
            out.add(v.date())
        elif isinstance(v, date):
            out.add(v)
        elif v:
            try:
                out.add(datetime.strptime(str(v)[:10], "%Y-%m-%d").date())
            except Exception:
                pass
    return out


def _easter_sunday(year: int):
    # Anonymous Gregorian algorithm.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _next_monday(d: date):
    return d + timedelta(days=(7 - d.weekday()) % 7)


def colombia_holidays(year):
    easter = _easter_sunday(year)
    fixed = {
        date(year, 1, 1), date(year, 5, 1), date(year, 7, 20), date(year, 8, 7),
        date(year, 12, 8), date(year, 12, 25),
        easter - timedelta(days=3), easter - timedelta(days=2),
        easter + timedelta(days=43), easter + timedelta(days=64), easter + timedelta(days=71),
    }
    movable = [
        date(year, 1, 6), date(year, 3, 19), date(year, 6, 29), date(year, 8, 15),
        date(year, 10, 12), date(year, 11, 1), date(year, 11, 11),
    ]
    return fixed | {_next_monday(d) for d in movable}


def add_business_days(start: date, days: int):
    d = start
    n = 0
    custom = extra_holidays()
    official = colombia_holidays(start.year) | colombia_holidays(start.year + 1)
    off = custom | official
    while n < days:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in off:
            n += 1
    return d


def classification(master):
    n = normalize_text(master.get("TIPO"))
    if "TEMPRANA" in n:
        return "C.TEMPRANA"
    if "PRODU" in n:
        return "PRODUCCION"
    if "ENSAM" in n:
        return "ENSAMBLE"
    return "SIN CLASIFICAR"


def rq_proposal(lm, base_date: date):
    """Construye la RQ propuesta.

    - Codigos con reglas "directas" (NO, 2, 3, 8) generan una fila por codigo,
      como antes.
    - Codigos con reglas de lamina (4,5,6,7) o perfil (1) se agrupan por
      LOTE (mismo material/espesor/formato detectado automaticamente desde
      NOMBRE, ver material_group_key) y se redondea hacia arriba UNA sola
      vez sobre el total del lote — asi se evita comprar una lamina/tramo
      entero por cada codigo individual.
    """
    _, master_map, _ = load_master()
    cfg = config_map()
    direct_rows = []
    batches = {}

    for r in lm:
        pending = safe_float(r.get("PENDIENTE"))
        if pending <= 1e-9:
            continue
        code = clean_code(r.get("CODIGO"))
        m = master_map.get(code, {})
        base_cls = classification(m)
        name = m.get("NOMBRE") or r.get("NOMBRE")
        cls = base_cls
        days = int(cfg.get(f"DIAS_{base_cls}", 0))
        # LM contiene la regla efectivamente aplicada a los renglones. Usarla
        # evita reactivar aquí una regla maestra incompatible que el cálculo
        # ya marcó e ignoró de forma segura.
        rule = clean_code(r.get("REGLA")) if normalize_text(r.get("REGLA")) not in {"", "NO"} else "NO"
        required_date = add_business_days(base_date, days) if days else base_date

        if rule in SHEET_RULE_DIVISORS or rule in PROFILE_RULE_DIVISOR:
            group_key = material_group_key(code, name, rule)
            key = (rule, group_key)
            b = batches.setdefault(key, {
                "rule": rule,
                "material": group_key.split("|", 1)[-1] if not group_key.startswith("__CODE__") else name,
                "unit": "Ud" if rule in SHEET_RULE_DIVISORS else "M",
                "total": 0.0,
                "members": [],
                "earliest_date": required_date,
                "classifications": set(),
            })
            b["total"] += pending
            b["members"].append((code, name, round(pending, 4)))
            b["classifications"].add(cls)
            if required_date < b["earliest_date"]:
                b["earliest_date"] = required_date
            continue

        qty = pending
        note_parts = []
        if rule in {"2", "8"} and r.get("NOTA REGLA"):
            note_parts.append(str(r.get("NOTA REGLA")))
        elif rule == "NO":
            # Categoria 0D (accesorios que no se fabrican: tornillos,
            # arandelas, abrazaderas...). Si el NOMBRE trae una presentacion
            # comercial detectable (caja/paquete), se redondea UNA vez al
            # final a paquetes completos, igual que lamina/perfil. Si no
            # se detecta presentacion, se compra la cantidad neta (unidad
            # suelta), sin cambios respecto al comportamiento actual.
            package = parse_package_size(name)
            if package:
                paquetes = math.ceil(pending / package - 1e-9)
                qty = paquetes * package
                note_parts.append(f"COMPRAR {paquetes} PAQUETE(S)/CAJA(S) DE {package} UND (TOTAL {qty:g} UND, NETO REQUERIDO {pending:g})")
        if normalize_text(m.get("NOTA")) == "SI":
            note_parts.extend(split_notes(m.get("DESCRIPCION DE LA NOTA")))
        direct_rows.append({
            "CLASIFICACION": cls,
            "CODIGO": code,
            "NOMBRE": name,
            "UD": m.get("U") or r.get("UD"),
            "CANTIDAD": round(qty, 6),
            "FECHA BASE": base_date.isoformat(),
            "DIAS": days,
            "FECHA REQUERIDA": required_date.isoformat(),
            "NOTA": "\n".join(x for x in note_parts if x and normalize_text(x) != "NO"),
        })

    batch_rows = []
    for (rule, group_key), b in batches.items():
        if rule in SHEET_RULE_DIVISORS:
            # CANTIDAD REQUERIDA ya está expresada en láminas equivalentes
            # (área de piezas / área comercial). Solo se redondea una vez.
            buy_qty = math.ceil(b["total"] - 1e-9)
            unit_label = "LÁMINA(S)"
        else:
            tramos = math.ceil(b["total"] / PROFILE_RULE_DIVISOR[rule] - 1e-9)
            buy_qty = tramos * PROFILE_RULE_DIVISOR[rule]
            unit_label = "TRAMO(S) DE 6 m"

        cls = next(iter(b["classifications"])) if len(b["classifications"]) == 1 else "SIN CLASIFICAR"
        breakdown = "; ".join(f"{code} ({name}): {qty:g}" for code, name, qty in b["members"])
        note = f"LOTE {b['material']} — {unit_label} — Desglose: {breakdown}"
        if len(b["classifications"]) > 1:
            note += " | ADVERTENCIA: piezas con distinta clasificación en el mismo lote, revisar fecha."

        # Si el lote es un solo codigo (no se pudo agrupar), usa ese codigo
        # como referencia; si es un lote real de varios codigos, usa el
        # primer codigo del lote como referencia de fila (ver NOTA para el
        # desglose completo).
        ref_code = b["members"][0][0]

        batch_rows.append({
            "CLASIFICACION": cls,
            "CODIGO": ref_code,
            "NOMBRE": b["material"],
            "UD": b["unit"],
            "CANTIDAD": buy_qty,
            "FECHA BASE": base_date.isoformat(),
            "DIAS": 0,
            "FECHA REQUERIDA": b["earliest_date"].isoformat(),
            "NOTA": note,
        })

    out = direct_rows + batch_rows
    category_order = {
        "C.TEMPRANA": 0,
        "EXTERNO": 1,
        "PRODUCCION": 2,
        "ENSAMBLE": 3,
        "SIN CLASIFICAR": 99,
    }
    out.sort(key=lambda row: (
        category_order.get(normalize_text(row.get("CLASIFICACION")), 90),
        normalize_text(row.get("NOMBRE")),
        clean_code(row.get("CODIGO")),
    ))
    return out


def spare_rows(details):
    _, master_map, _ = load_master()
    result = {}

    def add(code, qty, equipment="", note=None):
        m = master_map.get(code, {})
        if qty <= 0 or not code:
            return
        if note is None:
            note_lines = split_notes(m.get("DESCRIPCION DE LA NOTA")) if normalize_text(m.get("NOTA")) == "SI" else []
            note = "\n".join(note_lines)
        rec = result.setdefault(code, {
            "CODIGO": code, "NOMBRE": m.get("NOMBRE", ""), "CANTIDAD": 0.0,
            "UD": m.get("U", "Ud"), "CLASIFICACION": spare_class(m.get("TIPO DE REPUESTO")),
            "FRECUENCIA": spare_frequency(m.get("FRECUENCIA DE CAMBIO")), "NOTA": note or "",
            "OBSERVACION": set()
        })
        rec["CANTIDAD"] += qty
        if note and not rec["NOTA"]:
            rec["NOTA"] = note
        if equipment and normalize_text(equipment) != "GENERAL":
            rec["OBSERVACION"].add(equipment)

    for d in details:
        code = clean_code(d.get("STOCK NUMBER"))
        m = master_map.get(code)
        if not m:
            continue
        qty_source = safe_float(d.get("ITEM QTY"))
        eq = str(d.get("EQUIPO", ""))
        if normalize_text(m.get("REPUESTO")) == "SI":
            add(code, qty_source, eq)
        if normalize_text(m.get("REPUESTO DERIVADO")) == "SI":
            for child in split_associated_spares(m.get("DESCRIPCION DE LOS REPUESTOS ASOCIADOS")):
                add(child, qty_source, eq)

    rows = []
    for code, r in sorted(result.items()):
        rows.append({
            "CODIGO": code, "NOMBRE": r["NOMBRE"], "CANTIDAD": round(r["CANTIDAD"], 6),
            "UD": r["UD"], "CLASIFICACION": r["CLASIFICACION"], "FRECUENCIA": r["FRECUENCIA"],
            "NOTA": r["NOTA"], "OBSERVACION": ", ".join(sorted(r["OBSERVACION"]))
        })
    return rows


def value_rows(lm, details):
    _, master_map, _ = load_master()
    rows = []
    total = 0.0
    missing = 0
    for r in lm:
        code = clean_code(r.get("CODIGO"))
        m = master_map.get(code, {})
        price_raw = m.get("ULT.COSTO")
        price = safe_float(price_raw)
        price_ok = price_raw not in (None, "") and price > 0
        qty = safe_float(r.get("CANTIDAD REQUERIDA"))
        subtotal = qty * price if price_ok else None
        if subtotal is None:
            missing += 1
        else:
            total += subtotal
        rows.append({
            "CODIGO": code, "NOMBRE": m.get("NOMBRE") or r.get("NOMBRE"), "UD": m.get("U") or r.get("UD"),
            "CANTIDAD": round(qty, 6), "PRECIO": price if price_ok else "VALOR NO DISPONIBLE",
            "SUBTOTAL": round(subtotal, 2) if subtotal is not None else "VALOR NO DISPONIBLE"
        })
    rows.sort(key=lambda x: safe_float(x["SUBTOTAL"], -1) if x["SUBTOTAL"] != "VALOR NO DISPONIBLE" else -1, reverse=True)

    eq_totals = defaultdict(float)
    eq_missing = defaultdict(int)
    for d in details:
        code = clean_code(d.get("STOCK NUMBER"))
        m = master_map.get(code)
        eq = str(d.get("EQUIPO") or "GENERAL")
        if not m or m.get("ULT.COSTO") in (None, "") or safe_float(m.get("ULT.COSTO")) <= 0:
            eq_missing[eq] += 1
            continue
        eq_totals[eq] += safe_float(d.get("CANTIDAD CALCULADA")) * safe_float(m.get("ULT.COSTO"))
    eq_rows = [{"EQUIPO": k, "VALOR": round(v, 2), "SIN VALOR": eq_missing.get(k, 0)} for k, v in sorted(eq_totals.items())]
    return rows, total, missing, eq_rows


def compare_actual(actual, expected_map):
    out = []
    actual_sum = defaultdict(float)
    for r in actual:
        actual_sum[clean_code(r["CODIGO"])] += safe_float(r["CANTIDAD"])
    all_codes = set(expected_map) | set(actual_sum)
    for code in sorted(all_codes):
        exp = safe_float(expected_map.get(code, 0))
        act = safe_float(actual_sum.get(code, 0))
        if abs(act - exp) <= 1e-6:
            state = "CORRECTO"
        elif act < exp:
            state = "FALTANTE"
        else:
            state = "SOBRANTE"
        out.append({"CODIGO": code, "ESPERADO": exp, "CANTIDAD": act, "ESTADO": state})
    return out
