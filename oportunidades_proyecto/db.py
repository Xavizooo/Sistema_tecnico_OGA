from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
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


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_search(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


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
                FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
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


def _append_index(entries: list[tuple[int, str, str]], opportunity_id: int, field: str, value: Any) -> None:
    normalized = normalize_search(value)
    if normalized:
        entries.append((opportunity_id, field, normalized))


def _rebuild_search_index_conn(conn: sqlite3.Connection, opportunity_id: int) -> None:
    conn.execute("DELETE FROM search_index WHERE opportunity_id=?", (opportunity_id,))
    opportunity = conn.execute(
        "SELECT * FROM opportunities WHERE id=? AND eliminado_en IS NULL", (opportunity_id,)
    ).fetchone()
    if not opportunity:
        return
    entries: list[tuple[int, str, str]] = []
    field_names = {
        "radicado": "radicado", "proyecto": "proyecto", "nombre": "nombre", "cliente": "cliente",
        "descripcion": "descripcion", "planta": "planta", "ciudad": "ciudad", "pais": "pais",
        "industria": "industria", "tipo_oportunidad": "tipo", "estado": "estado", "fecha_inicio": "fecha",
        "valor_estimado": "valor", "observaciones": "observaciones",
    }
    for column, field in field_names.items():
        _append_index(entries, opportunity_id, field, opportunity[column])
    for row in conn.execute("SELECT username,name FROM opportunity_responsibles WHERE opportunity_id=?", (opportunity_id,)):
        _append_index(entries, opportunity_id, "responsable", f"{row['name']} {row['username']}")

    subsystem_rows = conn.execute(
        "SELECT * FROM subsystems WHERE opportunity_id=? AND eliminado_en IS NULL", (opportunity_id,)
    ).fetchall()
    for subsystem in subsystem_rows:
        sid = int(subsystem["id"])
        _append_index(entries, opportunity_id, "subsistema", subsystem["nombre"])
        _append_index(entries, opportunity_id, "proceso", f"{subsystem['nombre_proceso']} {subsystem['descripcion_proceso']}")
        _append_index(entries, opportunity_id, "voltaje", subsystem["voltaje_potencia"])
        _append_index(entries, opportunity_id, "material", " ".join(str(subsystem[key] or "") for key in ("material_contacto", "material_estructural", "material_transportado")))
        _append_index(entries, opportunity_id, "flujo", subsystem["flujo_kg_h"])
        _append_index(entries, opportunity_id, "distancia", " ".join(str(subsystem[key] or "") for key in ("distancia_horizontal_m", "distancia_vertical_m", "distancia_unidad_soplado_m")))
        _append_index(entries, opportunity_id, "atex", subsystem["atex"])
        _append_index(entries, opportunity_id, "nec", subsystem["nec"])
        _append_index(entries, opportunity_id, "ubicacion", subsystem["ubicacion"])
        _append_index(entries, opportunity_id, "transporte", " ".join(str(subsystem[key] or "") for key in ("tipo_transporte", "tipo_flujo", "diametro_tuberia", "tipo_acople", "preferencia_acoples", "preferencia_tipologia")))
        _append_index(entries, opportunity_id, "observaciones", subsystem["observaciones"])

        for row in conn.execute("SELECT tipo,cantidad,restriccion_altura FROM entry_points WHERE subsystem_id=?", (sid,)):
            _append_index(entries, opportunity_id, "entrada", " ".join(str(value or "") for value in row))
        for row in conn.execute("SELECT tipo,cantidad,restriccion_altura FROM exit_points WHERE subsystem_id=?", (sid,)):
            _append_index(entries, opportunity_id, "salida", " ".join(str(value or "") for value in row))
        for row in conn.execute("SELECT tipo_equipo,referencia,cantidad FROM equipment WHERE subsystem_id=?", (sid,)):
            _append_index(entries, opportunity_id, "equipo", " ".join(str(value or "") for value in row))
        for row in conn.execute("SELECT tipo,titulo,nombre_original FROM attachments WHERE subsystem_id=? AND eliminado_en IS NULL", (sid,)):
            field = "oferta" if row["tipo"] == ATTACHMENT_OFFER else "imagen"
            _append_index(entries, opportunity_id, field, f"{row['titulo']} {row['nombre_original']}")

    if entries:
        conn.executemany("INSERT INTO search_index (opportunity_id,field,value_norm) VALUES (?,?,?)", entries)


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
               (SELECT GROUP_CONCAT(CASE WHEN r.name<>'' THEN r.name ELSE r.username END, ', ')
                  FROM opportunity_responsibles r WHERE r.opportunity_id=o.id) AS responsible_names
        FROM opportunities o
        WHERE {' AND '.join(where)}
        ORDER BY o.actualizado_en DESC, o.id DESC
        LIMIT ?
    """
    with connection() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


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
    return normalize_search(radicado), normalize_search(proyecto)


def preview_bulk_import(payload: dict[str, Any]) -> dict[str, Any]:
    """Compara una previsualización normalizada contra la base actual.

    Una oportunidad se identifica por la pareja Radicado + Proyecto. Esto es
    intencional: la plantilla histórica contiene al menos dos radicados que se
    reutilizaron para proyectos diferentes.
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
                "nombre": str(data.get("nombre") or ""),
                "estado": str(data.get("estado") or "Nueva"),
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


def bulk_import_payload(payload: dict[str, Any], user: dict[str, Any]) -> dict[str, int]:
    """Importa la previsualización en una sola transacción segura.

    Reglas de combinación:
    - Radicado + Proyecto identifica la OD.
    - Una OD existente nunca se sobrescribe.
    - Un subsistema existente (por nombre normalizado) nunca sobrescribe sus
      criterios actuales; solo recibe entradas/salidas/equipos que falten.
    - Las ODs nuevas se crean sin responsables internos, porque la plantilla
      histórica no contiene esa información.
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

                existing_subsystems = {
                    normalize_search(row["nombre"]): int(row["id"])
                    for row in conn.execute(
                        "SELECT id,nombre FROM subsystems WHERE opportunity_id=? AND eliminado_en IS NULL ORDER BY id",
                        (opportunity_id,),
                    ).fetchall()
                }

                opportunity_changed = created_opportunity
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
