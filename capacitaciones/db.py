from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "capacitaciones"
DB_FILE = DATA_DIR / "capacitaciones.db"
ORIGINALS_DIR = DATA_DIR / "originales"
MEDIA_DIR = DATA_DIR / "media"

STATUS_PENDING = "PENDIENTE"
STATUS_PROCESSING = "PROCESANDO"
STATUS_READY = "LISTO"
STATUS_ERROR = "ERROR"
STATUS_DELETED = "ELIMINADO"


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)


@contextmanager
def connection():
    ensure_directories()
    conn = sqlite3.connect(DB_FILE, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
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
            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                descripcion TEXT NOT NULL DEFAULT '',
                archivo_original TEXT NOT NULL,
                ruta_original TEXT,
                ruta_mp4 TEXT,
                ruta_hls TEXT,
                ruta_poster TEXT,
                estado TEXT NOT NULL,
                progreso INTEGER NOT NULL DEFAULT 0,
                duracion_seg REAL,
                tamano_origen INTEGER NOT NULL DEFAULT 0,
                tamano_salida INTEGER NOT NULL DEFAULT 0,
                ancho INTEGER,
                alto INTEGER,
                error TEXT NOT NULL DEFAULT '',
                subido_por_id TEXT,
                subido_por_usuario TEXT,
                subido_por_nombre TEXT,
                creado_en TEXT NOT NULL,
                actualizado_en TEXT NOT NULL,
                iniciado_en TEXT,
                listo_en TEXT,
                eliminado_en TEXT,
                eliminado_por_id TEXT,
                eliminado_por_usuario TEXT,
                eliminado_por_nombre TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_videos_estado ON videos(estado);
            CREATE INDEX IF NOT EXISTS idx_videos_creado ON videos(creado_en DESC);
            """
        )
        # Si la aplicación se cerró durante una transcodificación, el trabajo
        # vuelve a la cola de forma segura en el siguiente arranque.
        conn.execute(
            """UPDATE videos
               SET estado=?, progreso=0, iniciado_en=NULL, actualizado_en=?
               WHERE estado=? AND eliminado_en IS NULL""",
            (STATUS_PENDING, utcnow(), STATUS_PROCESSING),
        )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def create_video(data: dict[str, Any]) -> dict[str, Any]:
    now = utcnow()
    fields = {
        "id": data["id"],
        "nombre": data["nombre"],
        "descripcion": data.get("descripcion", ""),
        "archivo_original": data["archivo_original"],
        "ruta_original": data.get("ruta_original"),
        "estado": STATUS_PENDING,
        "progreso": 0,
        "tamano_origen": int(data.get("tamano_origen") or 0),
        "subido_por_id": data.get("subido_por_id"),
        "subido_por_usuario": data.get("subido_por_usuario"),
        "subido_por_nombre": data.get("subido_por_nombre"),
        "creado_en": now,
        "actualizado_en": now,
    }
    columns = ",".join(fields.keys())
    marks = ",".join("?" for _ in fields)
    with connection() as conn:
        conn.execute(f"INSERT INTO videos ({columns}) VALUES ({marks})", tuple(fields.values()))
    return get_video(data["id"], include_deleted=True) or {}


def get_video(video_id: str, include_deleted: bool = False) -> dict[str, Any] | None:
    sql = "SELECT * FROM videos WHERE id=?"
    params: list[Any] = [video_id]
    if not include_deleted:
        sql += " AND eliminado_en IS NULL"
    with connection() as conn:
        return row_to_dict(conn.execute(sql, params).fetchone())


def list_videos(include_deleted: bool = False, limit: int = 500) -> list[dict[str, Any]]:
    sql = "SELECT * FROM videos"
    if not include_deleted:
        sql += " WHERE eliminado_en IS NULL"
    sql += " ORDER BY creado_en DESC LIMIT ?"
    with connection() as conn:
        return [dict(r) for r in conn.execute(sql, (max(1, min(limit, 2000)),)).fetchall()]


def pending_video_ids() -> list[str]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id FROM videos WHERE estado=? AND eliminado_en IS NULL ORDER BY creado_en ASC",
            (STATUS_PENDING,),
        ).fetchall()
    return [str(r["id"]) for r in rows]


def update_video(video_id: str, **changes: Any) -> None:
    if not changes:
        return
    changes["actualizado_en"] = utcnow()
    sets = ", ".join(f"{key}=?" for key in changes)
    values = list(changes.values()) + [video_id]
    with connection() as conn:
        conn.execute(f"UPDATE videos SET {sets} WHERE id=?", values)


def mark_processing(video_id: str, duration: float | None = None, width: int | None = None, height: int | None = None) -> None:
    update_video(
        video_id,
        estado=STATUS_PROCESSING,
        progreso=1,
        error="",
        duracion_seg=duration,
        ancho=width,
        alto=height,
        iniciado_en=utcnow(),
    )


def mark_ready(video_id: str, *, mp4_rel: str, hls_rel: str, poster_rel: str | None, output_size: int) -> None:
    update_video(
        video_id,
        estado=STATUS_READY,
        progreso=100,
        ruta_mp4=mp4_rel,
        ruta_hls=hls_rel,
        ruta_poster=poster_rel,
        tamano_salida=int(output_size or 0),
        listo_en=utcnow(),
        error="",
    )


def mark_error(video_id: str, message: str) -> None:
    update_video(video_id, estado=STATUS_ERROR, progreso=0, error=(message or "Error de transcodificación")[:2000])


def mark_pending(video_id: str) -> None:
    update_video(video_id, estado=STATUS_PENDING, progreso=0, error="", iniciado_en=None)


def soft_delete(video_id: str, user: dict[str, Any]) -> None:
    update_video(
        video_id,
        estado=STATUS_DELETED,
        eliminado_en=utcnow(),
        eliminado_por_id=user.get("id"),
        eliminado_por_usuario=user.get("username"),
        eliminado_por_nombre=user.get("name"),
    )


def stats() -> dict[str, Any]:
    with connection() as conn:
        counts = {
            row["estado"]: int(row["cantidad"])
            for row in conn.execute(
                "SELECT estado, COUNT(*) AS cantidad FROM videos WHERE eliminado_en IS NULL GROUP BY estado"
            ).fetchall()
        }
        totals = conn.execute(
            """SELECT COUNT(*) AS cantidad,
                      COALESCE(SUM(tamano_origen),0) AS origen,
                      COALESCE(SUM(tamano_salida),0) AS salida
               FROM videos WHERE eliminado_en IS NULL"""
        ).fetchone()
    return {
        "total": int(totals["cantidad"] if totals else 0),
        "origen": int(totals["origen"] if totals else 0),
        "salida": int(totals["salida"] if totals else 0),
        "pendientes": counts.get(STATUS_PENDING, 0),
        "procesando": counts.get(STATUS_PROCESSING, 0),
        "listos": counts.get(STATUS_READY, 0),
        "errores": counts.get(STATUS_ERROR, 0),
    }
