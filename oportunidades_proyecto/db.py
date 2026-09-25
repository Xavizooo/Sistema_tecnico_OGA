from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
import math
import re
import sqlite3
import unicodedata
from typing import Any, Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "oportunidades_proyecto"
DB_FILE = DATA_DIR / "oportunidades.db"
FILES_DIR = DATA_DIR / "archivos"

STATUSES = ("Nueva", "En análisis", "Cotizando", "Oferta enviada", "Ganada", "Perdida")
ATTACHMENT_OFFER = "OFERTA"
ATTACHMENT_IMAGE = "IMAGEN"

OPPORTUNITY_FIELDS = (
    "radicado", "proyecto", "nombre", "cliente", "descripcion", "planta",
    "ciudad", "pais", "industria", "tipo_oportunidad", "estado", "fecha_inicio",
    "valor_estimado", "observaciones",
)

SUBSYSTEM_FIELDS = (
    "nombre", "nombre_proceso", "descripcion_proceso", "voltaje_potencia",
    "material_contacto", "material_estructural", "material_transportado", "flujo_kg_h",
    "distancia_horizontal_m", "distancia_vertical_m", "curvas_90",
    "distancia_unidad_soplado_m", "curvas_unidad_soplado", "preferencia_tipologia",
    "preferencia_acoples", "tipo_flujo", "pesaje_oga", "atex", "nec", "ubicacion",
    "aire_comprimido", "tipo_transporte", "diametro_tuberia", "tipo_acople",
    "potencia_hp", "caudal_cfm", "diferencial_presion_psi", "tipo_bomba",
    "area_filtracion_m2", "micraje_filtracion", "consumo_aire_cfm",
    "presion_alimentacion_psi", "es_multiequipos", "observaciones",
)

# Campos técnicos que permanecen visibles/editables en la nueva vista de OD.
# El resto de la información histórica del subsistema se conserva en la BD y
# no se sobrescribe al editar desde esta interfaz simplificada.
VISIBLE_TECH_FIELDS = (
    "voltaje_potencia",
    "material_transportado",
    "flujo_kg_h",
    "potencia_hp",
    "diferencial_presion_psi",
    "caudal_cfm",
    "area_filtracion_m2",
)

SEARCH_FIELD_MAP = {
    "radicado": "radicado",
    "proyecto": "proyecto",
    "nombre": "nombre",
    "cliente": "cliente",
    "descripcion": "descripcion",
    "planta": "planta",
    "ciudad": "ciudad",
    "pais": "pais",
    "industria": "industria",
    "tipo": "tipo",
    "estado": "estado",
    "fecha": "fecha",
    "valor": "valor",
    "observaciones": "observaciones",
    "responsable": "responsable",
    "equipo_responsable": "responsable",
    "subsistema": "subsistema",
    "proceso": "proceso",
    "material": "material",
    "flujo": "flujo",
    "distancia": "distancia",
    "voltaje": "voltaje",
    "atex": "atex",
    "nec": "nec",
    "ubicacion": "ubicacion",
    "transporte": "transporte",
    "equipo": "equipo",
    "entrada": "entrada",
    "salida": "salida",
    "oferta": "oferta",
    "imagen": "imagen",
}

# Definición central del filtro avanzado Clave -> Valor. Las claves son estables
# y apuntan a entradas específicas de search_index; así la interfaz puede filtrar
# cualquier dato funcional del proyecto sin conocer la estructura física de SQLite.
ADVANCED_FILTER_FIELDS = (
    # Proyecto
    {"key": "proyecto", "label": "Proyecto", "group": "Proyecto", "type": "text"},
    {"key": "nombre", "label": "Nombre / título", "group": "Proyecto", "type": "text"},
    {"key": "cliente", "label": "Cliente", "group": "Proyecto", "type": "text"},
    {"key": "descripcion", "label": "Descripción", "group": "Proyecto", "type": "text"},
    {"key": "planta", "label": "Planta", "group": "Proyecto", "type": "text"},
    {"key": "ciudad", "label": "Ciudad", "group": "Proyecto", "type": "text"},
    {"key": "pais", "label": "País", "group": "Proyecto", "type": "text"},
    {"key": "industria", "label": "Tipo de industria", "group": "Proyecto", "type": "text"},
    {"key": "tipo", "label": "Tipo de oportunidad", "group": "Proyecto", "type": "text"},
    {"key": "fecha", "label": "Fecha de inicio", "group": "Proyecto", "type": "text"},
    {"key": "valor", "label": "Valor estimado", "group": "Proyecto", "type": "number"},
    {"key": "observaciones", "label": "Observaciones del proyecto", "group": "Proyecto", "type": "text"},
    {"key": "responsable", "label": "Responsable", "group": "Proyecto", "type": "text"},

    # Grupo técnico / proceso
    {"key": "subsistema", "label": "Grupo técnico / subsistema", "group": "Datos técnicos", "type": "text"},
    {"key": "nombre_proceso", "label": "Nombre del proceso", "group": "Datos técnicos", "type": "text"},
    {"key": "descripcion_proceso", "label": "Descripción del proceso", "group": "Datos técnicos", "type": "text"},
    {"key": "voltaje_potencia", "label": "Voltaje de potencia", "group": "Datos técnicos", "type": "text"},
    {"key": "material_contacto", "label": "Material de contacto con el producto", "group": "Datos técnicos", "type": "text"},
    {"key": "material_estructural", "label": "Material estructural", "group": "Datos técnicos", "type": "text"},
    {"key": "material_transportado", "label": "Material a transportar", "group": "Datos técnicos", "type": "text"},
    {"key": "flujo_kg_h", "label": "Flujo (kg/h)", "group": "Datos técnicos", "type": "number"},
    {"key": "distancia_horizontal_m", "label": "Distancia horizontal (m)", "group": "Datos técnicos", "type": "number"},
    {"key": "distancia_vertical_m", "label": "Distancia vertical (m)", "group": "Datos técnicos", "type": "number"},
    {"key": "curvas_90", "label": "Cantidad de curvas x 90°", "group": "Datos técnicos", "type": "number"},
    {"key": "distancia_unidad_soplado_m", "label": "Distancia unidad de soplado (m)", "group": "Datos técnicos", "type": "number"},
    {"key": "curvas_unidad_soplado", "label": "Curvas unidad de soplado / vacío", "group": "Datos técnicos", "type": "number"},
    {"key": "preferencia_tipologia", "label": "Preferencia de tipología", "group": "Datos técnicos", "type": "text"},
    {"key": "preferencia_acoples", "label": "Preferencia de acoples", "group": "Datos técnicos", "type": "text"},
    {"key": "tipo_flujo", "label": "Tipo de flujo", "group": "Datos técnicos", "type": "text"},
    {"key": "pesaje_oga", "label": "Pesaje OGA", "group": "Datos técnicos", "type": "text"},
    {"key": "atex", "label": "ATEX", "group": "Datos técnicos", "type": "text"},
    {"key": "nec", "label": "NEC", "group": "Datos técnicos", "type": "text"},
    {"key": "ubicacion", "label": "Ubicación", "group": "Datos técnicos", "type": "text"},
    {"key": "aire_comprimido", "label": "Aire comprimido", "group": "Datos técnicos", "type": "text"},
    {"key": "tipo_transporte", "label": "Tipo de transporte", "group": "Datos técnicos", "type": "text"},
    {"key": "diametro_tuberia", "label": "Diámetro de tubería", "group": "Datos técnicos", "type": "text"},
    {"key": "tipo_acople", "label": "Tipo de acople", "group": "Datos técnicos", "type": "text"},
    {"key": "potencia_hp", "label": "Potencia (hp)", "group": "Datos técnicos", "type": "number"},
    {"key": "caudal_cfm", "label": "Caudal (CFM)", "group": "Datos técnicos", "type": "number"},
    {"key": "diferencial_presion_psi", "label": "Diferencial de presión (PSI)", "group": "Datos técnicos", "type": "number"},
    {"key": "tipo_bomba", "label": "Tipo de bomba", "group": "Datos técnicos", "type": "text"},
    {"key": "area_filtracion_m2", "label": "Área de filtración (m²)", "group": "Datos técnicos", "type": "number"},
    {"key": "micraje_filtracion", "label": "Micraje de filtración", "group": "Datos técnicos", "type": "number"},
    {"key": "consumo_aire_cfm", "label": "Consumo de aire (CFM)", "group": "Datos técnicos", "type": "number"},
    {"key": "presion_alimentacion_psi", "label": "Presión de alimentación (PSI)", "group": "Datos técnicos", "type": "number"},
    {"key": "es_multiequipos", "label": "Es multiequipos", "group": "Datos técnicos", "type": "text"},
    {"key": "observaciones_tecnicas", "label": "Observaciones técnicas", "group": "Datos técnicos", "type": "text"},

    # Datos relacionados
    {"key": "entrada_tipo", "label": "Punto de origen · Tipo", "group": "Puntos de origen", "type": "text"},
    {"key": "entrada_cantidad", "label": "Punto de origen · Cantidad", "group": "Puntos de origen", "type": "number"},
    {"key": "entrada_altura", "label": "Punto de origen · Restricción de altura", "group": "Puntos de origen", "type": "text"},
    {"key": "salida_tipo", "label": "Punto de destino · Tipo", "group": "Puntos de destino", "type": "text"},
    {"key": "salida_cantidad", "label": "Punto de destino · Cantidad", "group": "Puntos de destino", "type": "number"},
    {"key": "salida_altura", "label": "Punto de destino · Restricción de altura", "group": "Puntos de destino", "type": "text"},
    {"key": "equipo_tipo", "label": "Equipo · Tipo", "group": "Equipos", "type": "text"},
    {"key": "equipo_referencia", "label": "Equipo · Referencia", "group": "Equipos", "type": "text"},
    {"key": "equipo_cantidad", "label": "Equipo · Cantidad", "group": "Equipos", "type": "number"},
    {"key": "oferta_titulo", "label": "Oferta · Título", "group": "Archivos", "type": "text"},
    {"key": "oferta_archivo", "label": "Oferta · Nombre de archivo", "group": "Archivos", "type": "text"},
    {"key": "imagen_titulo", "label": "Imagen · Título", "group": "Archivos", "type": "text"},
    {"key": "imagen_archivo", "label": "Imagen · Nombre de archivo", "group": "Archivos", "type": "text"},
)

ADVANCED_FILTER_FIELD_MAP = {item["key"]: item for item in ADVANCED_FILTER_FIELDS}
SEARCH_INDEX_VERSION = "4"


def advanced_filter_fields() -> list[dict[str, str]]:
    return [dict(item) for item in ADVANCED_FILTER_FIELDS]


def parse_filter_number(value: Any) -> float | None:
    """Extrae un número de valores como '1200', '11.5 hp' o '11,5'.

    También soporta separadores de miles repetidos (2.000.000) y formatos
    mixtos comunes (1.200,50 / 1,200.50). Un único punto o coma se trata como
    decimal para no alterar valores técnicos como 1.753 m².
    """
    text = str(value or "").strip().replace("\u00a0", " ")
    match = re.search(r"[-+]?\d[\d.,]*", text)
    if not match:
        return None
    token = match.group(0)
    sign = "-" if token.startswith("-") else ""
    token = token.lstrip("+-")
    try:
        if token.count(".") > 1 and "," not in token:
            normalized = token.replace(".", "")
        elif token.count(",") > 1 and "." not in token:
            normalized = token.replace(",", "")
        elif "." in token and "," in token:
            decimal_sep = "." if token.rfind(".") > token.rfind(",") else ","
            thousand_sep = "," if decimal_sep == "." else "."
            normalized = token.replace(thousand_sep, "").replace(decimal_sep, ".")
        else:
            normalized = token.replace(",", ".")
        return float(sign + normalized)
    except ValueError:
        return None



def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_search(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


def predictive_text_score(query: Any, candidate: Any) -> float:
    """Puntaje 0..1 para búsqueda tolerante a errores y palabras parciales.

    Da prioridad a coincidencias literales, pero permite errores pequeños de
    digitación (``peet`` -> ``pet``), palabras en distinto orden y valores con
    texto adicional (``pet food`` -> ``PET FOOD (PELLET)``).
    """
    q = normalize_search(query)
    c = normalize_search(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    # Las mayúsculas/minúsculas y tildes ya quedaron normalizadas arriba.
    # Priorizamos además los prefijos para que escribir "ne" sugiera NESTLE
    # antes que valores que solo contienen esas letras en la mitad.
    if c.startswith(q):
        return 0.999
    if q in c:
        return 0.995

    q_tokens = re.findall(r"[a-z0-9]+", q)
    c_tokens = re.findall(r"[a-z0-9]+", c)
    if not q_tokens or not c_tokens:
        return SequenceMatcher(None, q, c).ratio()

    token_scores: list[float] = []
    for q_token in q_tokens:
        best = 0.0
        for c_token in c_tokens:
            ratio = SequenceMatcher(None, q_token, c_token).ratio()
            # Una palabra parcialmente escrita sigue siendo una señal fuerte.
            if q_token.startswith(c_token) or c_token.startswith(q_token):
                overlap = min(len(q_token), len(c_token)) / max(len(q_token), len(c_token))
                ratio = max(ratio, overlap)
            best = max(best, ratio)
        token_scores.append(best)

    average = sum(token_scores) / len(token_scores)
    weakest = min(token_scores)
    phrase = SequenceMatcher(None, q, c).ratio()
    # Obliga a que todas las palabras aporten, evitando que una sola palabra
    # exacta haga pasar una frase completamente distinta.
    token_score = (average * 0.70) + (weakest * 0.30)
    return max(phrase, token_score)


def predictive_text_threshold(query: Any) -> float:
    """Umbral conservador: las consultas cortas necesitan mayor similitud."""
    normalized = normalize_search(query)
    compact = re.sub(r"[^a-z0-9]", "", normalized)
    if len(compact) <= 3:
        return 0.88
    if len(compact) <= 5:
        return 0.80
    return 0.72


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)


@contextmanager
def connection():
    ensure_directories()
    conn = sqlite3.connect(DB_FILE, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def ensure_database() -> None:
    ensure_directories()
    with connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                radicado TEXT NOT NULL DEFAULT '',
                proyecto TEXT NOT NULL DEFAULT '',
                nombre TEXT NOT NULL DEFAULT '',
                cliente TEXT NOT NULL DEFAULT '',
                descripcion TEXT NOT NULL DEFAULT '',
                planta TEXT NOT NULL DEFAULT '',
                ciudad TEXT NOT NULL DEFAULT '',
                pais TEXT NOT NULL DEFAULT '',
                industria TEXT NOT NULL DEFAULT '',
                tipo_oportunidad TEXT NOT NULL DEFAULT '',
                estado TEXT NOT NULL DEFAULT 'Nueva',
                fecha_inicio TEXT NOT NULL DEFAULT '',
                valor_estimado TEXT NOT NULL DEFAULT '',
                observaciones TEXT NOT NULL DEFAULT '',
                creado_por_id TEXT,
                creado_por_usuario TEXT,
                creado_por_nombre TEXT,
                creado_en TEXT NOT NULL,
                actualizado_por_id TEXT,
                actualizado_por_usuario TEXT,
                actualizado_por_nombre TEXT,
                actualizado_en TEXT NOT NULL,
                eliminado_en TEXT,
                eliminado_por_id TEXT,
                eliminado_por_usuario TEXT,
                eliminado_por_nombre TEXT
            );

            CREATE TABLE IF NOT EXISTS opportunity_responsibles (
                opportunity_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (opportunity_id, user_id),
                FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS subsystems (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id INTEGER NOT NULL,
                nombre TEXT NOT NULL DEFAULT 'Principal',
                nombre_proceso TEXT NOT NULL DEFAULT '',
                descripcion_proceso TEXT NOT NULL DEFAULT '',
                voltaje_potencia TEXT NOT NULL DEFAULT '',
                material_contacto TEXT NOT NULL DEFAULT '',
                material_estructural TEXT NOT NULL DEFAULT '',
                material_transportado TEXT NOT NULL DEFAULT '',
                flujo_kg_h TEXT NOT NULL DEFAULT '',
                distancia_horizontal_m TEXT NOT NULL DEFAULT '',
                distancia_vertical_m TEXT NOT NULL DEFAULT '',
                curvas_90 TEXT NOT NULL DEFAULT '',
                distancia_unidad_soplado_m TEXT NOT NULL DEFAULT '',
                curvas_unidad_soplado TEXT NOT NULL DEFAULT '',
                preferencia_tipologia TEXT NOT NULL DEFAULT '',
                preferencia_acoples TEXT NOT NULL DEFAULT '',
                tipo_flujo TEXT NOT NULL DEFAULT '',
                pesaje_oga TEXT NOT NULL DEFAULT '',
                atex TEXT NOT NULL DEFAULT '',
                nec TEXT NOT NULL DEFAULT '',
                ubicacion TEXT NOT NULL DEFAULT '',
                aire_comprimido TEXT NOT NULL DEFAULT '',
                tipo_transporte TEXT NOT NULL DEFAULT '',
                diametro_tuberia TEXT NOT NULL DEFAULT '',
                tipo_acople TEXT NOT NULL DEFAULT '',
                potencia_hp TEXT NOT NULL DEFAULT '',
                caudal_cfm TEXT NOT NULL DEFAULT '',
                diferencial_presion_psi TEXT NOT NULL DEFAULT '',
                tipo_bomba TEXT NOT NULL DEFAULT '',
                area_filtracion_m2 TEXT NOT NULL DEFAULT '',
                micraje_filtracion TEXT NOT NULL DEFAULT '',
                consumo_aire_cfm TEXT NOT NULL DEFAULT '',
                presion_alimentacion_psi TEXT NOT NULL DEFAULT '',
                es_multiequipos TEXT NOT NULL DEFAULT '',
                observaciones TEXT NOT NULL DEFAULT '',
                creado_por_id TEXT,
                creado_por_usuario TEXT,
                creado_por_nombre TEXT,
                creado_en TEXT NOT NULL,
                actualizado_en TEXT NOT NULL,
                eliminado_en TEXT,
                FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS entry_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subsystem_id INTEGER NOT NULL,
                tipo TEXT NOT NULL DEFAULT '',
                cantidad TEXT NOT NULL DEFAULT '',
                restriccion_altura TEXT NOT NULL DEFAULT '',
                creado_en TEXT NOT NULL,
                FOREIGN KEY (subsystem_id) REFERENCES subsystems(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS exit_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subsystem_id INTEGER NOT NULL,
                tipo TEXT NOT NULL DEFAULT '',
                cantidad TEXT NOT NULL DEFAULT '',
                restriccion_altura TEXT NOT NULL DEFAULT '',
                creado_en TEXT NOT NULL,
                FOREIGN KEY (subsystem_id) REFERENCES subsystems(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS equipment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subsystem_id INTEGER NOT NULL,
                tipo_equipo TEXT NOT NULL DEFAULT '',
                referencia TEXT NOT NULL DEFAULT '',
                cantidad TEXT NOT NULL DEFAULT '',
                creado_en TEXT NOT NULL,
                FOREIGN KEY (subsystem_id) REFERENCES subsystems(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subsystem_id INTEGER NOT NULL,
                tipo TEXT NOT NULL,
                titulo TEXT NOT NULL DEFAULT '',
                nombre_original TEXT NOT NULL DEFAULT '',
                ruta_relativa TEXT NOT NULL,
                mime_type TEXT NOT NULL DEFAULT '',
                tamano INTEGER NOT NULL DEFAULT 0,
                creado_por_id TEXT,
                creado_por_usuario TEXT,
                creado_por_nombre TEXT,
                creado_en TEXT NOT NULL,
                eliminado_en TEXT,
                eliminado_por_id TEXT,
                eliminado_por_usuario TEXT,
                eliminado_por_nombre TEXT,
                FOREIGN KEY (subsystem_id) REFERENCES subsystems(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS search_index (
                opportunity_id INTEGER NOT NULL,
                field TEXT NOT NULL,
                value_norm TEXT NOT NULL,
                value_display TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS search_index_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_od_active ON opportunities(eliminado_en, actualizado_en DESC);
            CREATE INDEX IF NOT EXISTS idx_od_radicado ON opportunities(radicado);
            CREATE INDEX IF NOT EXISTS idx_od_proyecto ON opportunities(proyecto);
            CREATE INDEX IF NOT EXISTS idx_sub_od ON subsystems(opportunity_id, eliminado_en);
            CREATE INDEX IF NOT EXISTS idx_attach_sub ON attachments(subsystem_id, tipo, eliminado_en);
            CREATE INDEX IF NOT EXISTS idx_search_od ON search_index(opportunity_id);
            CREATE INDEX IF NOT EXISTS idx_search_field ON search_index(field);
            """
        )
        # Migración compatible desde el índice histórico (sin value_display).
        search_columns = {row[1] for row in conn.execute("PRAGMA table_info(search_index)").fetchall()}
        if "value_display" not in search_columns:
            conn.execute("ALTER TABLE search_index ADD COLUMN value_display TEXT NOT NULL DEFAULT ''")

        index_version_row = conn.execute(
            "SELECT value FROM search_index_meta WHERE key='version'"
        ).fetchone()
        index_version = str(index_version_row[0]) if index_version_row else ""
        if index_version != SEARCH_INDEX_VERSION:
            conn.execute("DELETE FROM search_index")
            ids = [
                int(row[0]) for row in conn.execute(
                    "SELECT id FROM opportunities WHERE eliminado_en IS NULL ORDER BY id"
                ).fetchall()
            ]
            for opportunity_id in ids:
                _rebuild_search_index_conn(conn, opportunity_id)
            conn.execute(
                "INSERT INTO search_index_meta(key,value) VALUES('version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (SEARCH_INDEX_VERSION,),
            )


def _clean_dict(source: dict[str, Any], fields: Iterable[str]) -> dict[str, str]:
    return {field: str(source.get(field) or "").strip() for field in fields}


def _user_fields(prefix: str, user: dict[str, Any]) -> dict[str, Any]:
    return {
        f"{prefix}_por_id": user.get("id"),
        f"{prefix}_por_usuario": user.get("username"),
        f"{prefix}_por_nombre": user.get("name"),
    }


def _insert(conn: sqlite3.Connection, table: str, values: dict[str, Any]) -> int:
    columns = list(values.keys())
    marks = ",".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({marks})",
        [values[column] for column in columns],
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def _update(conn: sqlite3.Connection, table: str, row_id: int, values: dict[str, Any]) -> None:
    if not values:
        return
    columns = list(values.keys())
    conn.execute(
        f"UPDATE {table} SET {', '.join(f'{column}=?' for column in columns)} WHERE id=?",
        [values[column] for column in columns] + [row_id],
    )


def _replace_responsibles(conn: sqlite3.Connection, opportunity_id: int, users: Iterable[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM opportunity_responsibles WHERE opportunity_id=?", (opportunity_id,))
    for user in users:
        if not user.get("id"):
            continue
        conn.execute(
            "INSERT OR IGNORE INTO opportunity_responsibles (opportunity_id,user_id,username,name) VALUES (?,?,?,?)",
            (opportunity_id, str(user.get("id")), str(user.get("username") or ""), str(user.get("name") or "")),
        )


def create_opportunity(data: dict[str, Any], responsibles: Iterable[dict[str, Any]], user: dict[str, Any]) -> int:
    now = utcnow()
    values: dict[str, Any] = _clean_dict(data, OPPORTUNITY_FIELDS)
    if values["estado"] not in STATUSES:
        values["estado"] = STATUSES[0]
    values.update(_user_fields("creado", user))
    values.update({
        "creado_en": now,
        "actualizado_por_id": user.get("id"),
        "actualizado_por_usuario": user.get("username"),
        "actualizado_por_nombre": user.get("name"),
        "actualizado_en": now,
    })
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            opportunity_id = _insert(conn, "opportunities", values)
            _replace_responsibles(conn, opportunity_id, responsibles)
            _rebuild_search_index_conn(conn, opportunity_id)
            conn.execute("COMMIT")
            return opportunity_id
        except Exception:
            conn.execute("ROLLBACK")
            raise


def update_opportunity(opportunity_id: int, data: dict[str, Any], responsibles: Iterable[dict[str, Any]], user: dict[str, Any]) -> None:
    values: dict[str, Any] = _clean_dict(data, OPPORTUNITY_FIELDS)
    if values["estado"] not in STATUSES:
        values["estado"] = STATUSES[0]
    values.update({
        "actualizado_por_id": user.get("id"),
        "actualizado_por_usuario": user.get("username"),
        "actualizado_por_nombre": user.get("name"),
        "actualizado_en": utcnow(),
    })
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT id FROM opportunities WHERE id=? AND eliminado_en IS NULL", (opportunity_id,)).fetchone()
            if not row:
                raise ValueError("La oportunidad no existe.")
            _update(conn, "opportunities", opportunity_id, values)
            _replace_responsibles(conn, opportunity_id, responsibles)
            _rebuild_search_index_conn(conn, opportunity_id)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def update_opportunity_with_visible_technical(
    opportunity_id: int,
    data: dict[str, Any],
    responsibles: Iterable[dict[str, Any]],
    technical_updates: dict[int, dict[str, Any]],
    user: dict[str, Any],
) -> None:
    """Actualiza en una sola transacción la OD y los datos técnicos visibles.

    Solo modifica los siete campos definidos en ``VISIBLE_TECH_FIELDS``. De
    esta manera los campos históricos que ya no aparecen en la interfaz se
    conservan sin cambios.
    """
    values: dict[str, Any] = _clean_dict(data, OPPORTUNITY_FIELDS)
    if values["estado"] not in STATUSES:
        values["estado"] = STATUSES[0]
    now = utcnow()
    values.update({
        "actualizado_por_id": user.get("id"),
        "actualizado_por_usuario": user.get("username"),
        "actualizado_por_nombre": user.get("name"),
        "actualizado_en": now,
    })

    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT id FROM opportunities WHERE id=? AND eliminado_en IS NULL",
                (opportunity_id,),
            ).fetchone()
            if not row:
                raise ValueError("La oportunidad no existe.")

            _update(conn, "opportunities", opportunity_id, values)
            _replace_responsibles(conn, opportunity_id, responsibles)

            active_ids = {
                int(item["id"])
                for item in conn.execute(
                    "SELECT id FROM subsystems WHERE opportunity_id=? AND eliminado_en IS NULL",
                    (opportunity_id,),
                ).fetchall()
            }
            for raw_id, payload in technical_updates.items():
                try:
                    subsystem_id = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if subsystem_id not in active_ids:
                    continue
                tech_values = {
                    field: str(payload.get(field) or "").strip()
                    for field in VISIBLE_TECH_FIELDS
                }
                tech_values["actualizado_en"] = now
                _update(conn, "subsystems", subsystem_id, tech_values)

            _rebuild_search_index_conn(conn, opportunity_id)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def update_visible_subsystem(subsystem_id: int, data: dict[str, Any]) -> int:
    """Edita únicamente los siete campos técnicos visibles de un subsistema."""
    values = {
        field: str(data.get(field) or "").strip()
        for field in VISIBLE_TECH_FIELDS
    }
    values["actualizado_en"] = utcnow()
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT opportunity_id FROM subsystems WHERE id=? AND eliminado_en IS NULL",
                (subsystem_id,),
            ).fetchone()
            if not row:
                raise ValueError("El subsistema no existe.")
            opportunity_id = int(row["opportunity_id"])
            _update(conn, "subsystems", subsystem_id, values)
            conn.execute("UPDATE opportunities SET actualizado_en=? WHERE id=?", (utcnow(), opportunity_id))
            _rebuild_search_index_conn(conn, opportunity_id)
            conn.execute("COMMIT")
            return opportunity_id
        except Exception:
            conn.execute("ROLLBACK")
            raise


def soft_delete_opportunity(opportunity_id: int, user: dict[str, Any]) -> bool:
    now = utcnow()
    with connection() as conn:
        cur = conn.execute(
            """UPDATE opportunities SET eliminado_en=?, eliminado_por_id=?, eliminado_por_usuario=?, eliminado_por_nombre=?, actualizado_en=?
               WHERE id=? AND eliminado_en IS NULL""",
            (now, user.get("id"), user.get("username"), user.get("name"), now, opportunity_id),
        )
        conn.execute("DELETE FROM search_index WHERE opportunity_id=?", (opportunity_id,))
        return cur.rowcount > 0


def create_subsystem(opportunity_id: int, data: dict[str, Any], user: dict[str, Any]) -> int:
    now = utcnow()
    values: dict[str, Any] = _clean_dict(data, SUBSYSTEM_FIELDS)
    values["nombre"] = values["nombre"] or "Principal"
    values.update({
        "opportunity_id": opportunity_id,
        "creado_por_id": user.get("id"),
        "creado_por_usuario": user.get("username"),
        "creado_por_nombre": user.get("name"),
        "creado_en": now,
        "actualizado_en": now,
    })
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            active = conn.execute("SELECT id FROM opportunities WHERE id=? AND eliminado_en IS NULL", (opportunity_id,)).fetchone()
            if not active:
                raise ValueError("La oportunidad no existe.")
            subsystem_id = _insert(conn, "subsystems", values)
            conn.execute("UPDATE opportunities SET actualizado_en=? WHERE id=?", (now, opportunity_id))
            _rebuild_search_index_conn(conn, opportunity_id)
            conn.execute("COMMIT")
            return subsystem_id
        except Exception:
            conn.execute("ROLLBACK")
            raise


def update_subsystem(subsystem_id: int, data: dict[str, Any]) -> int:
    values: dict[str, Any] = _clean_dict(data, SUBSYSTEM_FIELDS)
    values["nombre"] = values["nombre"] or "Principal"
    values["actualizado_en"] = utcnow()
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT opportunity_id FROM subsystems WHERE id=? AND eliminado_en IS NULL", (subsystem_id,)
            ).fetchone()
            if not row:
                raise ValueError("El subsistema no existe.")
            opportunity_id = int(row["opportunity_id"])
            _update(conn, "subsystems", subsystem_id, values)
            conn.execute("UPDATE opportunities SET actualizado_en=? WHERE id=?", (utcnow(), opportunity_id))
            _rebuild_search_index_conn(conn, opportunity_id)
            conn.execute("COMMIT")
            return opportunity_id
        except Exception:
            conn.execute("ROLLBACK")
            raise


def soft_delete_subsystem(subsystem_id: int) -> int | None:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT opportunity_id FROM subsystems WHERE id=? AND eliminado_en IS NULL", (subsystem_id,)
            ).fetchone()
            if not row:
                conn.execute("ROLLBACK")
                return None
            opportunity_id = int(row["opportunity_id"])
            now = utcnow()
            conn.execute("UPDATE subsystems SET eliminado_en=?, actualizado_en=? WHERE id=?", (now, now, subsystem_id))
            conn.execute("UPDATE opportunities SET actualizado_en=? WHERE id=?", (now, opportunity_id))
            _rebuild_search_index_conn(conn, opportunity_id)
            conn.execute("COMMIT")
            return opportunity_id
        except Exception:
            conn.execute("ROLLBACK")
            raise


def create_attachment(subsystem_id: int, *, tipo: str, titulo: str, original_name: str, relative_path: str,
                      mime_type: str, size: int, user: dict[str, Any]) -> int:
    if tipo not in {ATTACHMENT_OFFER, ATTACHMENT_IMAGE}:
        raise ValueError("Tipo de archivo no válido.")
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT opportunity_id FROM subsystems WHERE id=? AND eliminado_en IS NULL", (subsystem_id,)
            ).fetchone()
            if not row:
                raise ValueError("El subsistema no existe.")
            values = {
                "subsystem_id": subsystem_id,
                "tipo": tipo,
                "titulo": str(titulo or "").strip(),
                "nombre_original": str(original_name or "").strip(),
                "ruta_relativa": str(relative_path),
                "mime_type": str(mime_type or ""),
                "tamano": int(size or 0),
                "creado_por_id": user.get("id"),
                "creado_por_usuario": user.get("username"),
                "creado_por_nombre": user.get("name"),
                "creado_en": utcnow(),
            }
            attachment_id = _insert(conn, "attachments", values)
            opportunity_id = int(row["opportunity_id"])
            conn.execute("UPDATE opportunities SET actualizado_en=? WHERE id=?", (utcnow(), opportunity_id))
            _rebuild_search_index_conn(conn, opportunity_id)
            conn.execute("COMMIT")
            return attachment_id
        except Exception:
            conn.execute("ROLLBACK")
            raise


def get_attachment(attachment_id: int, include_deleted: bool = False) -> dict[str, Any] | None:
    sql = """SELECT a.*, s.opportunity_id, s.nombre AS subsistema_nombre
             FROM attachments a JOIN subsystems s ON s.id=a.subsystem_id WHERE a.id=?"""
    if not include_deleted:
        sql += " AND a.eliminado_en IS NULL AND s.eliminado_en IS NULL"
    with connection() as conn:
        row = conn.execute(sql, (attachment_id,)).fetchone()
        return dict(row) if row else None


def soft_delete_attachment(attachment_id: int, user: dict[str, Any]) -> dict[str, Any] | None:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                """SELECT a.*, s.opportunity_id FROM attachments a
                   JOIN subsystems s ON s.id=a.subsystem_id
                   WHERE a.id=? AND a.eliminado_en IS NULL""", (attachment_id,)
            ).fetchone()
            if not row:
                conn.execute("ROLLBACK")
                return None
            data = dict(row)
            conn.execute(
                """UPDATE attachments SET eliminado_en=?, eliminado_por_id=?, eliminado_por_usuario=?, eliminado_por_nombre=?
                   WHERE id=?""",
                (utcnow(), user.get("id"), user.get("username"), user.get("name"), attachment_id),
            )
            opportunity_id = int(row["opportunity_id"])
            conn.execute("UPDATE opportunities SET actualizado_en=? WHERE id=?", (utcnow(), opportunity_id))
            _rebuild_search_index_conn(conn, opportunity_id)
            conn.execute("COMMIT")
            return data
        except Exception:
            conn.execute("ROLLBACK")
            raise


def add_point(subsystem_id: int, kind: str, tipo: str, cantidad: str, restriccion_altura: str) -> int:
    table = "entry_points" if kind == "entrada" else "exit_points" if kind == "salida" else ""
    if not table:
        raise ValueError("Tipo de punto inválido.")
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT opportunity_id FROM subsystems WHERE id=? AND eliminado_en IS NULL", (subsystem_id,)).fetchone()
            if not row:
                raise ValueError("El subsistema no existe.")
            point_id = _insert(conn, table, {
                "subsystem_id": subsystem_id,
                "tipo": str(tipo or "").strip(),
                "cantidad": str(cantidad or "").strip(),
                "restriccion_altura": str(restriccion_altura or "").strip(),
                "creado_en": utcnow(),
            })
            opportunity_id = int(row["opportunity_id"])
            _rebuild_search_index_conn(conn, opportunity_id)
            conn.execute("COMMIT")
            return point_id
        except Exception:
            conn.execute("ROLLBACK")
            raise


def set_primary_point(subsystem_id: int, kind: str, tipo: str) -> int:
    """Crea, actualiza o limpia el punto principal mostrado en A-AB.

    Los puntos adicionales se conservan. El formulario técnico edita únicamente
    el primer punto de entrada/salida; la tabla flotante sigue permitiendo
    administrar puntos adicionales de forma independiente.
    """
    table = "entry_points" if kind == "entrada" else "exit_points" if kind == "salida" else ""
    if not table:
        raise ValueError("Tipo de punto inválido.")
    value = str(tipo or "").strip()
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT opportunity_id FROM subsystems WHERE id=? AND eliminado_en IS NULL",
                (subsystem_id,),
            ).fetchone()
            if not row:
                raise ValueError("El subsistema no existe.")
            opportunity_id = int(row["opportunity_id"])
            point = conn.execute(
                f"SELECT id FROM {table} WHERE subsystem_id=? ORDER BY id LIMIT 1",
                (subsystem_id,),
            ).fetchone()
            if point and value:
                conn.execute(f"UPDATE {table} SET tipo=? WHERE id=?", (value, int(point["id"])))
            elif point and not value:
                conn.execute(f"DELETE FROM {table} WHERE id=?", (int(point["id"]),))
            elif value:
                _insert(conn, table, {
                    "subsystem_id": subsystem_id,
                    "tipo": value,
                    "cantidad": "1",
                    "restriccion_altura": "",
                    "creado_en": utcnow(),
                })
            conn.execute("UPDATE opportunities SET actualizado_en=? WHERE id=?", (utcnow(), opportunity_id))
            _rebuild_search_index_conn(conn, opportunity_id)
            conn.execute("COMMIT")
            return opportunity_id
        except Exception:
            conn.execute("ROLLBACK")
            raise


def add_equipment(subsystem_id: int, tipo_equipo: str, referencia: str, cantidad: str) -> int:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT opportunity_id FROM subsystems WHERE id=? AND eliminado_en IS NULL", (subsystem_id,)).fetchone()
            if not row:
                raise ValueError("El subsistema no existe.")
            equipment_id = _insert(conn, "equipment", {
                "subsystem_id": subsystem_id,
                "tipo_equipo": str(tipo_equipo or "").strip(),
                "referencia": str(referencia or "").strip(),
                "cantidad": str(cantidad or "").strip(),
                "creado_en": utcnow(),
            })
            opportunity_id = int(row["opportunity_id"])
            _rebuild_search_index_conn(conn, opportunity_id)
            conn.execute("COMMIT")
            return equipment_id
        except Exception:
            conn.execute("ROLLBACK")
            raise


def delete_child(table: str, row_id: int) -> int | None:
    if table not in {"entry_points", "exit_points", "equipment"}:
        raise ValueError("Tabla no válida.")
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                f"""SELECT s.opportunity_id FROM {table} x JOIN subsystems s ON s.id=x.subsystem_id WHERE x.id=?""",
                (row_id,),
            ).fetchone()
            if not row:
                conn.execute("ROLLBACK")
                return None
            opportunity_id = int(row["opportunity_id"])
            conn.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))
            _rebuild_search_index_conn(conn, opportunity_id)
            conn.execute("COMMIT")
            return opportunity_id
        except Exception:
            conn.execute("ROLLBACK")
            raise


def get_opportunity(opportunity_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM opportunities WHERE id=? AND eliminado_en IS NULL", (opportunity_id,)).fetchone()
        return dict(row) if row else None


def get_subsystem(subsystem_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM subsystems WHERE id=? AND eliminado_en IS NULL", (subsystem_id,)
        ).fetchone()
        return dict(row) if row else None


def get_opportunity_detail(opportunity_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        opportunity_row = conn.execute(
            "SELECT * FROM opportunities WHERE id=? AND eliminado_en IS NULL", (opportunity_id,)
        ).fetchone()
        if not opportunity_row:
            return None
        opportunity = dict(opportunity_row)
        opportunity["responsibles"] = [
            dict(row) for row in conn.execute(
                "SELECT * FROM opportunity_responsibles WHERE opportunity_id=? ORDER BY name, username", (opportunity_id,)
            ).fetchall()
        ]
        subsystems: list[dict[str, Any]] = []
        for row in conn.execute(
            "SELECT * FROM subsystems WHERE opportunity_id=? AND eliminado_en IS NULL ORDER BY id", (opportunity_id,)
        ).fetchall():
            subsystem = dict(row)
            sid = int(subsystem["id"])
            subsystem["entry_points"] = [dict(item) for item in conn.execute(
                "SELECT * FROM entry_points WHERE subsystem_id=? ORDER BY id", (sid,)
            ).fetchall()]
            subsystem["exit_points"] = [dict(item) for item in conn.execute(
                "SELECT * FROM exit_points WHERE subsystem_id=? ORDER BY id", (sid,)
            ).fetchall()]
            subsystem["equipment"] = [dict(item) for item in conn.execute(
                "SELECT * FROM equipment WHERE subsystem_id=? ORDER BY id", (sid,)
            ).fetchall()]
            subsystem["offers"] = [dict(item) for item in conn.execute(
                "SELECT * FROM attachments WHERE subsystem_id=? AND tipo=? AND eliminado_en IS NULL ORDER BY creado_en DESC, id DESC",
                (sid, ATTACHMENT_OFFER),
            ).fetchall()]
            subsystem["images"] = [dict(item) for item in conn.execute(
                "SELECT * FROM attachments WHERE subsystem_id=? AND tipo=? AND eliminado_en IS NULL ORDER BY creado_en DESC, id DESC",
                (sid, ATTACHMENT_IMAGE),
            ).fetchall()]
            subsystems.append(subsystem)
        opportunity["subsystems"] = subsystems
        return opportunity


def list_recent(limit: int = 100) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT o.*,
                      (SELECT COUNT(*) FROM subsystems s WHERE s.opportunity_id=o.id AND s.eliminado_en IS NULL) AS subsystem_count,
                      (SELECT COUNT(*) FROM opportunity_responsibles r WHERE r.opportunity_id=o.id) AS responsible_count
               FROM opportunities o
               WHERE o.eliminado_en IS NULL
               ORDER BY o.actualizado_en DESC, o.id DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        return [dict(row) for row in rows]


def _append_index(entries: list[tuple[int, str, str, str]], opportunity_id: int, field: str, value: Any) -> None:
    display = str(value or "").strip()
    normalized = normalize_search(display)
    if normalized:
        entries.append((opportunity_id, field, normalized, display))


def _append_index_aliases(
    entries: list[tuple[int, str, str, str]], opportunity_id: int, fields: Iterable[str], value: Any
) -> None:
    for field in fields:
        _append_index(entries, opportunity_id, field, value)


def _rebuild_search_index_conn(conn: sqlite3.Connection, opportunity_id: int) -> None:
    conn.execute("DELETE FROM search_index WHERE opportunity_id=?", (opportunity_id,))
    opportunity = conn.execute(
        "SELECT * FROM opportunities WHERE id=? AND eliminado_en IS NULL", (opportunity_id,)
    ).fetchone()
    if not opportunity:
        return

    entries: list[tuple[int, str, str, str]] = []
    field_names = {
        "radicado": "radicado",
        "proyecto": "proyecto",
        "nombre": "nombre",
        "cliente": "cliente",
        "descripcion": "descripcion",
        "planta": "planta",
        "ciudad": "ciudad",
        "pais": "pais",
        "industria": "industria",
        "tipo_oportunidad": "tipo",
        "estado": "estado",
        "fecha_inicio": "fecha",
        "valor_estimado": "valor",
        "observaciones": "observaciones",
    }
    for column, field in field_names.items():
        _append_index(entries, opportunity_id, field, opportunity[column])

    for row in conn.execute(
        "SELECT username,name FROM opportunity_responsibles WHERE opportunity_id=?", (opportunity_id,)
    ):
        label = " ".join(part for part in (str(row["name"] or "").strip(), str(row["username"] or "").strip()) if part)
        _append_index(entries, opportunity_id, "responsable", label)

    subsystem_rows = conn.execute(
        "SELECT * FROM subsystems WHERE opportunity_id=? AND eliminado_en IS NULL", (opportunity_id,)
    ).fetchall()
    for subsystem in subsystem_rows:
        sid = int(subsystem["id"])
        # Índice detallado para el nuevo filtro Clave -> Valor.
        subsystem_fields = {
            "nombre": "subsistema",
            "nombre_proceso": "nombre_proceso",
            "descripcion_proceso": "descripcion_proceso",
            "voltaje_potencia": "voltaje_potencia",
            "material_contacto": "material_contacto",
            "material_estructural": "material_estructural",
            "material_transportado": "material_transportado",
            "flujo_kg_h": "flujo_kg_h",
            "distancia_horizontal_m": "distancia_horizontal_m",
            "distancia_vertical_m": "distancia_vertical_m",
            "curvas_90": "curvas_90",
            "distancia_unidad_soplado_m": "distancia_unidad_soplado_m",
            "curvas_unidad_soplado": "curvas_unidad_soplado",
            "preferencia_tipologia": "preferencia_tipologia",
            "preferencia_acoples": "preferencia_acoples",
            "tipo_flujo": "tipo_flujo",
            "pesaje_oga": "pesaje_oga",
            "atex": "atex",
            "nec": "nec",
            "ubicacion": "ubicacion",
            "aire_comprimido": "aire_comprimido",
            "tipo_transporte": "tipo_transporte",
            "diametro_tuberia": "diametro_tuberia",
            "tipo_acople": "tipo_acople",
            "potencia_hp": "potencia_hp",
            "caudal_cfm": "caudal_cfm",
            "diferencial_presion_psi": "diferencial_presion_psi",
            "tipo_bomba": "tipo_bomba",
            "area_filtracion_m2": "area_filtracion_m2",
            "micraje_filtracion": "micraje_filtracion",
            "consumo_aire_cfm": "consumo_aire_cfm",
            "presion_alimentacion_psi": "presion_alimentacion_psi",
            "es_multiequipos": "es_multiequipos",
            "observaciones": "observaciones_tecnicas",
        }
        for column, field in subsystem_fields.items():
            _append_index(entries, opportunity_id, field, subsystem[column])

        # Alias del buscador libre/campo:valor histórico.
        _append_index(entries, opportunity_id, "proceso", f"{subsystem['nombre_proceso']} {subsystem['descripcion_proceso']}")
        _append_index(entries, opportunity_id, "voltaje", subsystem["voltaje_potencia"])
        _append_index(
            entries, opportunity_id, "material",
            " ".join(str(subsystem[key] or "") for key in ("material_contacto", "material_estructural", "material_transportado")),
        )
        _append_index(entries, opportunity_id, "flujo", subsystem["flujo_kg_h"])
        _append_index(
            entries, opportunity_id, "distancia",
            " ".join(str(subsystem[key] or "") for key in ("distancia_horizontal_m", "distancia_vertical_m", "distancia_unidad_soplado_m")),
        )
        _append_index(entries, opportunity_id, "transporte", " ".join(
            str(subsystem[key] or "") for key in ("tipo_transporte", "tipo_flujo", "diametro_tuberia", "tipo_acople", "preferencia_acoples", "preferencia_tipologia")
        ))
        _append_index(entries, opportunity_id, "observaciones", subsystem["observaciones"])

        for row in conn.execute("SELECT tipo,cantidad,restriccion_altura FROM entry_points WHERE subsystem_id=?", (sid,)):
            _append_index(entries, opportunity_id, "entrada_tipo", row["tipo"])
            _append_index(entries, opportunity_id, "entrada_cantidad", row["cantidad"])
            _append_index(entries, opportunity_id, "entrada_altura", row["restriccion_altura"])
            _append_index(entries, opportunity_id, "entrada", " ".join(str(value or "") for value in row))
        for row in conn.execute("SELECT tipo,cantidad,restriccion_altura FROM exit_points WHERE subsystem_id=?", (sid,)):
            _append_index(entries, opportunity_id, "salida_tipo", row["tipo"])
            _append_index(entries, opportunity_id, "salida_cantidad", row["cantidad"])
            _append_index(entries, opportunity_id, "salida_altura", row["restriccion_altura"])
            _append_index(entries, opportunity_id, "salida", " ".join(str(value or "") for value in row))
        for row in conn.execute("SELECT tipo_equipo,referencia,cantidad FROM equipment WHERE subsystem_id=?", (sid,)):
            _append_index(entries, opportunity_id, "equipo_tipo", row["tipo_equipo"])
            _append_index(entries, opportunity_id, "equipo_referencia", row["referencia"])
            _append_index(entries, opportunity_id, "equipo_cantidad", row["cantidad"])
            _append_index(entries, opportunity_id, "equipo", " ".join(str(value or "") for value in row))
        for row in conn.execute(
            "SELECT tipo,titulo,nombre_original FROM attachments WHERE subsystem_id=? AND eliminado_en IS NULL", (sid,)
        ):
            if row["tipo"] == ATTACHMENT_OFFER:
                _append_index(entries, opportunity_id, "oferta_titulo", row["titulo"])
                _append_index(entries, opportunity_id, "oferta_archivo", row["nombre_original"])
                _append_index(entries, opportunity_id, "oferta", f"{row['titulo']} {row['nombre_original']}")
            else:
                _append_index(entries, opportunity_id, "imagen_titulo", row["titulo"])
                _append_index(entries, opportunity_id, "imagen_archivo", row["nombre_original"])
                _append_index(entries, opportunity_id, "imagen", f"{row['titulo']} {row['nombre_original']}")

    if entries:
        conn.executemany(
            "INSERT INTO search_index (opportunity_id,field,value_norm,value_display) VALUES (?,?,?,?)",
            entries,
        )


def rebuild_search_index(opportunity_id: int | None = None) -> None:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if opportunity_id is not None:
                _rebuild_search_index_conn(conn, int(opportunity_id))
            else:
                conn.execute("DELETE FROM search_index")
                ids = [int(row["id"]) for row in conn.execute("SELECT id FROM opportunities WHERE eliminado_en IS NULL")]
                for oid in ids:
                    _rebuild_search_index_conn(conn, oid)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def search_opportunities(tokens: list[tuple[str | None, str]], limit: int = 200) -> list[dict[str, Any]]:
    where = ["o.eliminado_en IS NULL"]
    params: list[Any] = []
    for field, raw_value in tokens:
        value = normalize_search(raw_value)
        if not value:
            continue
        if field:
            canonical = SEARCH_FIELD_MAP.get(field, field)
            where.append(
                "EXISTS (SELECT 1 FROM search_index sx WHERE sx.opportunity_id=o.id AND sx.field=? AND sx.value_norm LIKE ?)"
            )
            params.extend([canonical, f"%{value}%"])
        else:
            where.append(
                "EXISTS (SELECT 1 FROM search_index sx WHERE sx.opportunity_id=o.id AND sx.value_norm LIKE ?)"
            )
            params.append(f"%{value}%")
    params.append(max(1, min(int(limit), 500)))
    sql = f"""
        SELECT o.id, o.radicado, o.proyecto, o.nombre, o.cliente, o.descripcion, o.planta, o.ciudad, o.pais,
               o.industria, o.tipo_oportunidad, o.estado, o.fecha_inicio, o.valor_estimado, o.actualizado_en,
               (SELECT COUNT(*) FROM subsystems s WHERE s.opportunity_id=o.id AND s.eliminado_en IS NULL) AS subsystem_count,
               (SELECT s.material_transportado FROM subsystems s
                  WHERE s.opportunity_id=o.id AND s.eliminado_en IS NULL ORDER BY s.id LIMIT 1) AS material_transportado,
               (SELECT ep.tipo FROM entry_points ep JOIN subsystems s ON s.id=ep.subsystem_id
                  WHERE s.opportunity_id=o.id AND s.eliminado_en IS NULL ORDER BY s.id, ep.id LIMIT 1) AS punto_ingreso,
               (SELECT xp.tipo FROM exit_points xp JOIN subsystems s ON s.id=xp.subsystem_id
                  WHERE s.opportunity_id=o.id AND s.eliminado_en IS NULL ORDER BY s.id, xp.id LIMIT 1) AS punto_destino,
               (SELECT s.flujo_kg_h FROM subsystems s
                  WHERE s.opportunity_id=o.id AND s.eliminado_en IS NULL ORDER BY s.id LIMIT 1) AS flujo_kg_h,
               (SELECT s.distancia_horizontal_m FROM subsystems s
                  WHERE s.opportunity_id=o.id AND s.eliminado_en IS NULL ORDER BY s.id LIMIT 1) AS distancia_horizontal_m,
               (SELECT s.distancia_vertical_m FROM subsystems s
                  WHERE s.opportunity_id=o.id AND s.eliminado_en IS NULL ORDER BY s.id LIMIT 1) AS distancia_vertical_m,
               (SELECT s.curvas_90 FROM subsystems s
                  WHERE s.opportunity_id=o.id AND s.eliminado_en IS NULL ORDER BY s.id LIMIT 1) AS curvas_90,
               (SELECT s.tipo_transporte FROM subsystems s
                  WHERE s.opportunity_id=o.id AND s.eliminado_en IS NULL ORDER BY s.id LIMIT 1) AS tipo_transporte,
               (SELECT s.material_contacto FROM subsystems s
                  WHERE s.opportunity_id=o.id AND s.eliminado_en IS NULL ORDER BY s.id LIMIT 1) AS material_contacto,
               (SELECT GROUP_CONCAT(CASE WHEN r.name<>'' THEN r.name ELSE r.username END, ', ')
                  FROM opportunity_responsibles r WHERE r.opportunity_id=o.id) AS responsible_names
        FROM opportunities o
        WHERE {' AND '.join(where)}
        ORDER BY o.actualizado_en DESC, o.id DESC
        LIMIT ?
    """
    with connection() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _numeric_filter_values(
    conn: sqlite3.Connection, opportunity_ids: list[int], field: str
) -> dict[int, list[tuple[float, str]]]:
    if not opportunity_ids:
        return {}
    marks = ",".join("?" for _ in opportunity_ids)
    sql = (
        f"SELECT opportunity_id,value_display FROM search_index "
        f"WHERE field=? AND opportunity_id IN ({marks})"
    )
    values: dict[int, list[tuple[float, str]]] = {}
    for row in conn.execute(sql, [field, *opportunity_ids]).fetchall():
        number = parse_filter_number(row["value_display"])
        if number is None:
            continue
        values.setdefault(int(row["opportunity_id"]), []).append((number, str(row["value_display"] or "")))
    return values


def _text_filter_values(
    conn: sqlite3.Connection, opportunity_ids: list[int], field: str
) -> dict[int, list[str]]:
    if not opportunity_ids:
        return {}
    marks = ",".join("?" for _ in opportunity_ids)
    sql = (
        f"SELECT opportunity_id,value_display FROM search_index "
        f"WHERE field=? AND opportunity_id IN ({marks}) AND TRIM(value_display)<>''"
    )
    values: dict[int, list[str]] = {}
    for row in conn.execute(sql, [field, *opportunity_ids]).fetchall():
        display = str(row["value_display"] or "").strip()
        if display:
            values.setdefault(int(row["opportunity_id"]), []).append(display)
    return values


def search_opportunities_advanced(
    tokens: list[tuple[str | None, str]],
    filters: Iterable[dict[str, Any]] | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Busca texto libre + filtros Clave -> Valor.

    Los filtros de texto del constructor avanzado usan coincidencia predictiva:
    toleran errores pequeños, texto parcial y orden diferente de palabras. Los
    filtros numéricos conservan el comportamiento de valor exacto / más cercano.
    """
    cleaned: list[dict[str, str]] = []
    for item in list(filters or [])[:20]:
        key = str((item or {}).get("key") or "").strip()
        value = str((item or {}).get("value") or "").strip()
        if key in ADVANCED_FILTER_FIELD_MAP and value:
            cleaned.append({"key": key, "value": value})

    numeric_filters: list[tuple[dict[str, str], dict[str, str], float]] = []
    text_filters: list[tuple[dict[str, str], dict[str, str]]] = []
    for item in cleaned:
        definition = ADVANCED_FILTER_FIELD_MAP[item["key"]]
        if definition["type"] == "number":
            target = parse_filter_number(item["value"])
            if target is not None:
                numeric_filters.append((item, definition, target))
                continue
        text_filters.append((item, definition))

    # La búsqueda libre superior conserva su semántica histórica. Los filtros
    # avanzados de texto se evalúan después para poder aplicar similitud.
    rows = search_opportunities(list(tokens), limit=500)
    meta: dict[str, Any] = {
        "approximate": False,
        "predictive": False,
        "candidate_total": len(rows),
        "nearest": [],
        "predictive_matches": [],
    }

    if text_filters and rows:
        ids = [int(row["id"]) for row in rows]
        with connection() as conn:
            text_maps = {
                definition["key"]: _text_filter_values(conn, ids, definition["key"])
                for _, definition in text_filters
            }

        surviving: list[dict[str, Any]] = []
        best_examples: dict[str, tuple[float, str, bool]] = {}
        predictive_used = False
        for row in rows:
            oid = int(row["id"])
            accepted = True
            row_matches: list[tuple[str, float, str, bool]] = []
            for item, definition in text_filters:
                query_value = item["value"]
                candidates = text_maps.get(definition["key"], {}).get(oid, [])
                if not candidates:
                    accepted = False
                    break
                scored = [
                    (predictive_text_score(query_value, candidate), candidate)
                    for candidate in candidates
                ]
                score, display = max(scored, key=lambda pair: pair[0])
                threshold = predictive_text_threshold(query_value)
                if score < threshold:
                    accepted = False
                    break
                literal = normalize_search(query_value) in normalize_search(display)
                row_matches.append((definition["key"], score, display, literal))
            if not accepted:
                continue
            surviving.append(row)
            for key, score, display, literal in row_matches:
                if not literal:
                    predictive_used = True
                    previous = best_examples.get(key)
                    if previous is None or score > previous[0]:
                        best_examples[key] = (score, display, literal)

        rows = surviving
        meta["predictive"] = predictive_used
        for item, definition in text_filters:
            example = best_examples.get(definition["key"])
            if not example:
                continue
            meta["predictive_matches"].append({
                "key": definition["key"],
                "label": definition["label"],
                "requested": item["value"],
                "matched": example[1],
                "score": round(example[0], 4),
            })

    candidate_total = len(rows)
    meta["candidate_total"] = candidate_total
    result_limit = max(1, min(int(limit), 500))
    if not numeric_filters or not rows:
        return {"rows": rows[:result_limit], "meta": meta}

    ids = [int(row["id"]) for row in rows]
    with connection() as conn:
        value_maps = {
            definition["key"]: _numeric_filter_values(conn, ids, definition["key"])
            for _, definition, _ in numeric_filters
        }

    scored: list[tuple[float, bool, dict[str, Any], dict[str, tuple[float, str] | None]]] = []
    for row in rows:
        oid = int(row["id"])
        score = 0.0
        all_exact = True
        nearest_for_row: dict[str, tuple[float, str] | None] = {}
        valid = True
        for item, definition, target in numeric_filters:
            choices = value_maps.get(definition["key"], {}).get(oid, [])
            if not choices:
                valid = False
                break
            nearest = min(choices, key=lambda pair: abs(pair[0] - target))
            distance = abs(nearest[0] - target)
            tolerance = max(1e-9, abs(target) * 1e-9)
            exact = distance <= tolerance
            all_exact = all_exact and exact
            score += distance / max(abs(target), 1.0)
            nearest_for_row[definition["key"]] = nearest
        if valid:
            scored.append((score, all_exact, row, nearest_for_row))

    exact_rows = [item for item in scored if item[1]]
    if exact_rows:
        exact_ids = {int(item[2]["id"]) for item in exact_rows}
        result_rows = [row for row in rows if int(row["id"]) in exact_ids][:result_limit]
        return {"rows": result_rows, "meta": meta}

    scored.sort(key=lambda item: (item[0], -int(item[2]["id"])))
    result_rows = [item[2] for item in scored[:min(result_limit, 25)]]
    meta["approximate"] = bool(scored)

    for original, definition, target in numeric_filters:
        seen: set[float] = set()
        nearest_values: list[dict[str, Any]] = []
        pool: list[tuple[float, str]] = []
        for _, _, _, nearest_for_row in scored:
            pair = nearest_for_row.get(definition["key"])
            if pair is not None:
                pool.append(pair)
        for number, display in sorted(pool, key=lambda pair: (abs(pair[0] - target), pair[0])):
            rounded = round(number, 10)
            if rounded in seen:
                continue
            seen.add(rounded)
            nearest_values.append({
                "value": display,
                "number": number,
                "distance": abs(number - target),
            })
            if len(nearest_values) >= 5:
                break
        meta["nearest"].append({
            "key": definition["key"],
            "label": definition["label"],
            "requested": original["value"],
            "values": nearest_values,
        })

    return {"rows": result_rows, "meta": meta}

def filter_value_suggestions(field: str, query: str = "", limit: int = 8) -> list[dict[str, Any]]:
    definition = ADVANCED_FILTER_FIELD_MAP.get(str(field or "").strip())
    if not definition:
        return []
    max_items = max(1, min(int(limit), 20))
    query_text = str(query or "").strip()
    with connection() as conn:
        rows = conn.execute(
            """SELECT value_display, value_norm, COUNT(*) AS uses
                 FROM search_index
                 WHERE field=? AND TRIM(value_display)<>''
                 GROUP BY value_display, value_norm
            """,
            (definition["key"],),
        ).fetchall()

    if definition["type"] == "number":
        target = parse_filter_number(query_text)
        values: list[tuple[float, str, int]] = []
        for row in rows:
            number = parse_filter_number(row["value_display"])
            if number is None:
                continue
            values.append((number, str(row["value_display"]), int(row["uses"])))
        if target is None:
            values.sort(key=lambda item: (item[0], -item[2]))
        else:
            values.sort(key=lambda item: (abs(item[0] - target), item[0], -item[2]))
        result = []
        seen: set[float] = set()
        for number, display, uses in values:
            rounded = round(number, 10)
            if rounded in seen:
                continue
            seen.add(rounded)
            result.append({
                "value": display,
                "count": uses,
                "distance": None if target is None else abs(number - target),
                "exact": False if target is None else math.isclose(number, target, rel_tol=1e-9, abs_tol=1e-9),
            })
            if len(result) >= max_items:
                break
        return result

    normalized_query = normalize_search(query_text)
    if not normalized_query:
        text_values = [(str(row["value_display"]), int(row["uses"])) for row in rows]
        text_values.sort(key=lambda item: (-item[1], normalize_search(item[0])))
        return [{"value": value, "count": uses, "score": None, "predictive": False} for value, uses in text_values[:max_items]]

    ranked: list[tuple[bool, bool, float, int, str]] = []
    suggestion_threshold = max(0.55, predictive_text_threshold(query_text) - 0.16)
    for row in rows:
        display = str(row["value_display"] or "").strip()
        if not display:
            continue
        # No confiamos únicamente en value_norm almacenado: lo normalizamos de
        # nuevo para que bases antiguas también sean 100 % case/accent insensitive.
        normalized_value = normalize_search(row["value_norm"] or display)
        prefix = normalized_value.startswith(normalized_query)
        literal = normalized_query in normalized_value
        score = predictive_text_score(query_text, display)
        if not literal and score < suggestion_threshold:
            continue
        ranked.append((prefix, literal, score, int(row["uses"]), display))

    # Prefijo > coincidencia contenida > similitud > frecuencia de uso.
    # Así "ne" coloca NESTLE antes que palabras que casualmente contienen "ne".
    ranked.sort(key=lambda item: (not item[0], not item[1], -item[2], -item[3], normalize_search(item[4])))
    return [
        {
            "value": display,
            "count": uses,
            "score": round(score, 4),
            "predictive": not literal,
            "prefix": prefix,
        }
        for prefix, literal, score, uses, display in ranked[:max_items]
    ]


def stats() -> dict[str, int]:
    with connection() as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM opportunities WHERE eliminado_en IS NULL").fetchone()[0])
        subsystem_count = int(conn.execute("SELECT COUNT(*) FROM subsystems WHERE eliminado_en IS NULL").fetchone()[0])
        rows = conn.execute(
            "SELECT estado, COUNT(*) AS cantidad FROM opportunities WHERE eliminado_en IS NULL GROUP BY estado"
        ).fetchall()
    result = {"total": total, "subsistemas": subsystem_count}
    for row in rows:
        result[str(row["estado"])] = int(row["cantidad"])
    return result

# ---------------------------------------------------------------------------
# Cargue masivo de oportunidades (Fase 2)
# ---------------------------------------------------------------------------

def _bulk_opportunity_key(radicado: Any, proyecto: Any) -> tuple[str, str]:
    # Proyecto es el identificador funcional de la plantilla actual. Radicado se
    # conserva solo por compatibilidad histórica y ya no participa en el merge.
    return "", normalize_search(proyecto)


def preview_bulk_import(payload: dict[str, Any]) -> dict[str, Any]:
    """Compara una previsualización normalizada contra la base actual.

    En la plantilla actual una oportunidad se identifica por Proyecto.
    Radicado se conserva únicamente como compatibilidad con cargas históricas.
    """
    opportunities = list(payload.get("opportunities") or [])
    with connection() as conn:
        existing_rows = conn.execute(
            "SELECT id,radicado,proyecto FROM opportunities WHERE eliminado_en IS NULL"
        ).fetchall()
        existing_map = {
            _bulk_opportunity_key(row["radicado"], row["proyecto"]): int(row["id"])
            for row in existing_rows
        }
        rows: list[dict[str, Any]] = []
        new_opportunities = existing_opportunities = 0
        new_subsystems = existing_subsystems = 0
        for item in opportunities:
            data = dict(item.get("data") or {})
            key = _bulk_opportunity_key(data.get("radicado"), data.get("proyecto"))
            existing_id = existing_map.get(key)
            staged_subsystems = list(item.get("subsystems") or [])
            if existing_id is None:
                action = "CREAR"
                new_opportunities += 1
                new_count = len(staged_subsystems)
                existing_count = 0
            else:
                action = "COMBINAR"
                existing_opportunities += 1
                names = {
                    normalize_search(row["nombre"])
                    for row in conn.execute(
                        "SELECT nombre FROM subsystems WHERE opportunity_id=? AND eliminado_en IS NULL",
                        (existing_id,),
                    ).fetchall()
                }
                existing_count = sum(
                    1 for subsystem in staged_subsystems
                    if normalize_search((subsystem.get("data") or {}).get("nombre")) in names
                )
                new_count = len(staged_subsystems) - existing_count
            new_subsystems += new_count
            existing_subsystems += existing_count
            rows.append({
                "radicado": str(data.get("radicado") or ""),
                "proyecto": str(data.get("proyecto") or ""),
                "cliente": str(data.get("cliente") or ""),
                "fecha_inicio": str(data.get("fecha_inicio") or ""),
                "industria": str(data.get("industria") or ""),
                "subsistemas": len(staged_subsystems),
                "subsistemas_nuevos": new_count,
                "subsistemas_existentes": existing_count,
                "action": action,
                "existing_id": existing_id,
            })
    return {
        "rows": rows,
        "new_opportunities": new_opportunities,
        "existing_opportunities": existing_opportunities,
        "new_subsystems": new_subsystems,
        "existing_subsystems": existing_subsystems,
    }


def _normalized_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(normalize_search(value) for value in values)


def _insert_missing_multiset(
    conn: sqlite3.Connection,
    table: str,
    subsystem_id: int,
    fields: tuple[str, ...],
    staged_rows: Iterable[dict[str, Any]],
) -> tuple[int, int]:
    """Inserta solo la multiplicidad que todavía no existe.

    Si la fuente contiene dos renglones idénticos, conserva ambos en la primera
    importación y evita crear otros dos al cargar nuevamente el mismo Excel.
    """
    staged_counter: Counter[tuple[str, ...]] = Counter()
    staged_example: dict[tuple[str, ...], dict[str, str]] = {}
    for source in staged_rows:
        cleaned = {field: str(source.get(field) or "").strip() for field in fields}
        if not any(cleaned.values()):
            continue
        key = _normalized_tuple(cleaned[field] for field in fields)
        staged_counter[key] += 1
        staged_example[key] = cleaned

    existing_counter: Counter[tuple[str, ...]] = Counter()
    sql = f"SELECT {','.join(fields)} FROM {table} WHERE subsystem_id=?"
    for row in conn.execute(sql, (subsystem_id,)).fetchall():
        existing_counter[_normalized_tuple(row[field] for field in fields)] += 1

    added = skipped = 0
    for key, staged_count in staged_counter.items():
        existing_count = existing_counter.get(key, 0)
        to_add = max(0, staged_count - existing_count)
        skipped += min(staged_count, existing_count)
        sample = staged_example[key]
        for _ in range(to_add):
            values: dict[str, Any] = {"subsystem_id": subsystem_id, **sample, "creado_en": utcnow()}
            _insert(conn, table, values)
            added += 1
    return added, skipped


def _fill_empty_fields_conn(
    conn: sqlite3.Connection,
    table: str,
    row_id: int,
    source: dict[str, Any],
    fields: Iterable[str],
) -> bool:
    """Completa solo campos vacíos; nunca pisa información existente."""
    row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
    if not row:
        return False
    updates: dict[str, Any] = {}
    for field in fields:
        incoming = str(source.get(field) or "").strip()
        current = str(row[field] or "").strip() if field in row.keys() else ""
        if incoming and not current:
            updates[field] = incoming
    if not updates:
        return False
    _update(conn, table, row_id, updates)
    return True


def bulk_import_payload(payload: dict[str, Any], user: dict[str, Any]) -> dict[str, int]:
    """Importa la previsualización en una sola transacción segura.

    Reglas de combinación:
    - Proyecto identifica la OD en la plantilla A–AB.
    - Una OD existente conserva sus valores y solo completa campos vacíos.
    - Un grupo técnico existente conserva sus valores y solo completa campos vacíos.
    - Entradas, salidas y equipos se agregan únicamente si no existen todavía.
    - Las ODs nuevas se crean sin responsables internos, porque el Excel no contiene esa información.
    """
    opportunities = list(payload.get("opportunities") or [])
    result = {
        "oportunidades_creadas": 0,
        "oportunidades_combinadas": 0,
        "subsistemas_creados": 0,
        "subsistemas_existentes": 0,
        "entradas_agregadas": 0,
        "entradas_omitidas": 0,
        "salidas_agregadas": 0,
        "salidas_omitidas": 0,
        "equipos_agregados": 0,
        "equipos_omitidos": 0,
    }
    now = utcnow()
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing_map = {
                _bulk_opportunity_key(row["radicado"], row["proyecto"]): int(row["id"])
                for row in conn.execute(
                    "SELECT id,radicado,proyecto FROM opportunities WHERE eliminado_en IS NULL"
                ).fetchall()
            }
            touched: set[int] = set()
            for item in opportunities:
                source_data = dict(item.get("data") or {})
                data = _clean_dict(source_data, OPPORTUNITY_FIELDS)
                if data["estado"] not in STATUSES:
                    data["estado"] = STATUSES[0]
                if not data["radicado"] or not data["proyecto"]:
                    continue
                key = _bulk_opportunity_key(data["radicado"], data["proyecto"])
                opportunity_id = existing_map.get(key)
                created_opportunity = opportunity_id is None
                if opportunity_id is None:
                    values: dict[str, Any] = dict(data)
                    values.update(_user_fields("creado", user))
                    values.update({
                        "creado_en": now,
                        "actualizado_por_id": user.get("id"),
                        "actualizado_por_usuario": user.get("username"),
                        "actualizado_por_nombre": user.get("name"),
                        "actualizado_en": now,
                    })
                    opportunity_id = _insert(conn, "opportunities", values)
                    existing_map[key] = opportunity_id
                    result["oportunidades_creadas"] += 1
                else:
                    result["oportunidades_combinadas"] += 1

                opportunity_changed = created_opportunity
                if not created_opportunity:
                    # La plantilla A:AB puede aportar datos que antes no existían en
                    # la OD. Solo completamos celdas vacías para respetar ediciones.
                    opportunity_changed = _fill_empty_fields_conn(
                        conn, "opportunities", opportunity_id, data, OPPORTUNITY_FIELDS
                    )

                existing_subsystems = {
                    normalize_search(row["nombre"]): int(row["id"])
                    for row in conn.execute(
                        "SELECT id,nombre FROM subsystems WHERE opportunity_id=? AND eliminado_en IS NULL ORDER BY id",
                        (opportunity_id,),
                    ).fetchall()
                }

                for staged_subsystem in item.get("subsystems") or []:
                    sub_data = _clean_dict(dict(staged_subsystem.get("data") or {}), SUBSYSTEM_FIELDS)
                    sub_data["nombre"] = sub_data["nombre"] or "Principal"
                    sub_key = normalize_search(sub_data["nombre"])
                    subsystem_id = existing_subsystems.get(sub_key)
                    if subsystem_id is None:
                        sub_values: dict[str, Any] = dict(sub_data)
                        sub_values.update({
                            "opportunity_id": opportunity_id,
                            "creado_por_id": user.get("id"),
                            "creado_por_usuario": user.get("username"),
                            "creado_por_nombre": user.get("name"),
                            "creado_en": now,
                            "actualizado_en": now,
                        })
                        subsystem_id = _insert(conn, "subsystems", sub_values)
                        existing_subsystems[sub_key] = subsystem_id
                        result["subsistemas_creados"] += 1
                        opportunity_changed = True
                    else:
                        result["subsistemas_existentes"] += 1
                        if _fill_empty_fields_conn(
                            conn, "subsystems", subsystem_id, sub_data, SUBSYSTEM_FIELDS
                        ):
                            conn.execute(
                                "UPDATE subsystems SET actualizado_en=? WHERE id=?",
                                (utcnow(), subsystem_id),
                            )
                            opportunity_changed = True

                    added, skipped = _insert_missing_multiset(
                        conn, "entry_points", subsystem_id,
                        ("tipo", "cantidad", "restriccion_altura"),
                        staged_subsystem.get("entry_points") or [],
                    )
                    result["entradas_agregadas"] += added
                    result["entradas_omitidas"] += skipped
                    opportunity_changed = opportunity_changed or bool(added)

                    added, skipped = _insert_missing_multiset(
                        conn, "exit_points", subsystem_id,
                        ("tipo", "cantidad", "restriccion_altura"),
                        staged_subsystem.get("exit_points") or [],
                    )
                    result["salidas_agregadas"] += added
                    result["salidas_omitidas"] += skipped
                    opportunity_changed = opportunity_changed or bool(added)

                    added, skipped = _insert_missing_multiset(
                        conn, "equipment", subsystem_id,
                        ("tipo_equipo", "referencia", "cantidad"),
                        staged_subsystem.get("equipment") or [],
                    )
                    result["equipos_agregados"] += added
                    result["equipos_omitidos"] += skipped
                    opportunity_changed = opportunity_changed or bool(added)

                if opportunity_changed:
                    conn.execute(
                        "UPDATE opportunities SET actualizado_por_id=?, actualizado_por_usuario=?, actualizado_por_nombre=?, actualizado_en=? WHERE id=?",
                        (user.get("id"), user.get("username"), user.get("name"), utcnow(), opportunity_id),
                    )
                    touched.add(opportunity_id)

            for opportunity_id in touched:
                _rebuild_search_index_conn(conn, opportunity_id)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return result
