from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
import math
import re
import sqlite3
import unicodedata
from typing import Any, Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
DB_FILE = BASE_DIR / "data" / "oportunidades_proyecto" / "oportunidades.db"

FIELD_MAP = {
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

SIMILARITY_WEIGHTS = {
    "material": 0.28,
    "transporte": 0.20,
    "proceso": 0.14,
    "equipo": 0.14,
    "entrada": 0.08,
    "salida": 0.08,
    "industria": 0.04,
    "tipo": 0.02,
    "flujo": 0.02,
}

STOP_TOKENS = {
    "de", "del", "la", "las", "el", "los", "y", "a", "en", "con", "por", "para",
    "un", "una", "unos", "unas", "tipo", "sistema", "sistemas", "transporte", "principal",
    "no", "si", "aplica", "desde", "hasta", "unidad", "unidades",
}


def normalize(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


def _terms(value: Any) -> set[str]:
    text = normalize(value)
    words = set(re.findall(r"[a-z0-9]+", text))
    return {word for word in words if len(word) > 1 and word not in STOP_TOKENS}


@contextmanager
def readonly_connection():
    """Open the OD database in SQLite read-only mode.

    This is the hard safety boundary for the assistant. SQLite rejects INSERT,
    UPDATE, DELETE, CREATE and every other write operation at connection level.
    """
    if not DB_FILE.exists():
        yield None
        return
    uri = DB_FILE.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    finally:
        conn.close()


def database_ready() -> bool:
    if not DB_FILE.exists():
        return False
    try:
        with readonly_connection() as conn:
            if conn is None:
                return False
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='opportunities'"
            ).fetchone()
            return bool(row)
    except sqlite3.Error:
        return False


def _summary_sql(where: str, limit_clause: bool = True) -> str:
    limit = " LIMIT ?" if limit_clause else ""
    return f"""
        SELECT o.id, o.radicado, o.proyecto, o.nombre, o.cliente, o.descripcion,
               o.planta, o.ciudad, o.pais, o.industria, o.tipo_oportunidad,
               o.estado, o.fecha_inicio, o.valor_estimado, o.actualizado_en,
               (SELECT COUNT(*) FROM subsystems s
                  WHERE s.opportunity_id=o.id AND s.eliminado_en IS NULL) AS subsystem_count,
               (SELECT GROUP_CONCAT(CASE WHEN r.name<>'' THEN r.name ELSE r.username END, ', ')
                  FROM opportunity_responsibles r WHERE r.opportunity_id=o.id) AS responsible_names
        FROM opportunities o
        WHERE {where}
        ORDER BY o.actualizado_en DESC, o.id DESC{limit}
    """


def search_opportunities(tokens: Iterable[tuple[str | None, str]], limit: int = 20) -> list[dict[str, Any]]:
    where = ["o.eliminado_en IS NULL"]
    params: list[Any] = []
    for field, raw in tokens:
        value = normalize(raw)
        if not value:
            continue
        if field:
            canonical = FIELD_MAP.get(field, field)
            where.append(
                "EXISTS (SELECT 1 FROM search_index sx WHERE sx.opportunity_id=o.id AND sx.field=? AND sx.value_norm LIKE ?)"
            )
            params.extend([canonical, f"%{value}%"])
        else:
            where.append(
                "EXISTS (SELECT 1 FROM search_index sx WHERE sx.opportunity_id=o.id AND sx.value_norm LIKE ?)"
            )
            params.append(f"%{value}%")
    params.append(max(1, min(int(limit), 100)))
    with readonly_connection() as conn:
        if conn is None:
            return []
        try:
            rows = conn.execute(_summary_sql(" AND ".join(where)), params).fetchall()
        except sqlite3.OperationalError:
            return []
        return [dict(row) for row in rows]


def count_opportunities(tokens: Iterable[tuple[str | None, str]]) -> int:
    where = ["o.eliminado_en IS NULL"]
    params: list[Any] = []
    for field, raw in tokens:
        value = normalize(raw)
        if not value:
            continue
        if field:
            canonical = FIELD_MAP.get(field, field)
            where.append(
                "EXISTS (SELECT 1 FROM search_index sx WHERE sx.opportunity_id=o.id AND sx.field=? AND sx.value_norm LIKE ?)"
            )
            params.extend([canonical, f"%{value}%"])
        else:
            where.append(
                "EXISTS (SELECT 1 FROM search_index sx WHERE sx.opportunity_id=o.id AND sx.value_norm LIKE ?)"
            )
            params.append(f"%{value}%")
    with readonly_connection() as conn:
        if conn is None:
            return 0
        try:
            row = conn.execute(
                f"SELECT COUNT(*) FROM opportunities o WHERE {' AND '.join(where)}", params
            ).fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row[0] if row else 0)


def get_opportunity(opportunity_id: int) -> dict[str, Any] | None:
    with readonly_connection() as conn:
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT * FROM opportunities WHERE id=? AND eliminado_en IS NULL", (int(opportunity_id),)
            ).fetchone()
        except (sqlite3.Error, ValueError, TypeError):
            return None
        if not row:
            return None
        opportunity = dict(row)
        opportunity["responsibles"] = [dict(item) for item in conn.execute(
            "SELECT user_id, username, name FROM opportunity_responsibles WHERE opportunity_id=? ORDER BY name, username",
            (opportunity_id,),
        ).fetchall()]
        subsystems: list[dict[str, Any]] = []
        for subsystem_row in conn.execute(
            "SELECT * FROM subsystems WHERE opportunity_id=? AND eliminado_en IS NULL ORDER BY id",
            (opportunity_id,),
        ).fetchall():
            subsystem = dict(subsystem_row)
            sid = int(subsystem["id"])
            subsystem["entry_points"] = [dict(item) for item in conn.execute(
                "SELECT id,tipo,cantidad,restriccion_altura FROM entry_points WHERE subsystem_id=? ORDER BY id", (sid,)
            ).fetchall()]
            subsystem["exit_points"] = [dict(item) for item in conn.execute(
                "SELECT id,tipo,cantidad,restriccion_altura FROM exit_points WHERE subsystem_id=? ORDER BY id", (sid,)
            ).fetchall()]
            subsystem["equipment"] = [dict(item) for item in conn.execute(
                "SELECT id,tipo_equipo,referencia,cantidad FROM equipment WHERE subsystem_id=? ORDER BY id", (sid,)
            ).fetchall()]
            subsystem["offers"] = [dict(item) for item in conn.execute(
                """SELECT id,titulo,nombre_original,mime_type,tamano,creado_en
                     FROM attachments WHERE subsystem_id=? AND tipo='OFERTA' AND eliminado_en IS NULL
                     ORDER BY creado_en DESC,id DESC""", (sid,)
            ).fetchall()]
            subsystem["images"] = [dict(item) for item in conn.execute(
                """SELECT id,titulo,nombre_original,mime_type,tamano,creado_en
                     FROM attachments WHERE subsystem_id=? AND tipo='IMAGEN' AND eliminado_en IS NULL
                     ORDER BY creado_en DESC,id DESC""", (sid,)
            ).fetchall()]
            subsystems.append(subsystem)
        opportunity["subsystems"] = subsystems
        return opportunity


def find_exact(kind: str, value: str, limit: int = 20) -> list[dict[str, Any]]:
    value = str(value or "").strip()
    if not value:
        return []
    kind = normalize(kind)
    with readonly_connection() as conn:
        if conn is None:
            return []
        params: list[Any] = []
        if kind in {"id", "od", "od_id"} and value.isdigit():
            where = "o.eliminado_en IS NULL AND o.id=?"
            params = [int(value)]
        elif kind == "radicado":
            where = "o.eliminado_en IS NULL AND LOWER(TRIM(o.radicado))=LOWER(TRIM(?))"
            params = [value]
        elif kind in {"proyecto", "project"}:
            where = "o.eliminado_en IS NULL AND LOWER(TRIM(o.proyecto))=LOWER(TRIM(?))"
            params = [value]
        else:
            return []
        params.append(max(1, min(int(limit), 50)))
        try:
            rows = conn.execute(_summary_sql(where), params).fetchall()
        except sqlite3.Error:
            return []
        return [dict(row) for row in rows]


def attachment_links(opportunity_id: int, kind: str | None = None) -> list[dict[str, Any]]:
    with readonly_connection() as conn:
        if conn is None:
            return []
        clauses = ["s.opportunity_id=?", "s.eliminado_en IS NULL", "a.eliminado_en IS NULL"]
        params: list[Any] = [int(opportunity_id)]
        if kind in {"OFERTA", "IMAGEN"}:
            clauses.append("a.tipo=?")
            params.append(kind)
        rows = conn.execute(
            f"""SELECT a.id,a.tipo,a.titulo,a.nombre_original,a.mime_type,a.tamano,a.creado_en,
                       s.id AS subsystem_id,s.nombre AS subsystem_name
                FROM attachments a JOIN subsystems s ON s.id=a.subsystem_id
                WHERE {' AND '.join(clauses)}
                ORDER BY s.id,a.creado_en DESC,a.id DESC""", params
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["view_url"] = f"/oportunidades-proyecto/archivos/{item['id']}"
            item["download_url"] = f"/oportunidades-proyecto/archivos/{item['id']}/descargar"
            output.append(item)
        return output


def stats() -> dict[str, Any]:
    with readonly_connection() as conn:
        if conn is None:
            return {"total": 0, "subsystems": 0, "equipment": 0, "offers": 0, "images": 0, "states": {}}
        try:
            total = int(conn.execute("SELECT COUNT(*) FROM opportunities WHERE eliminado_en IS NULL").fetchone()[0])
            subsystems = int(conn.execute("SELECT COUNT(*) FROM subsystems WHERE eliminado_en IS NULL").fetchone()[0])
            equipment = int(conn.execute(
                """SELECT COUNT(*) FROM equipment e JOIN subsystems s ON s.id=e.subsystem_id
                   JOIN opportunities o ON o.id=s.opportunity_id
                   WHERE s.eliminado_en IS NULL AND o.eliminado_en IS NULL"""
            ).fetchone()[0])
            offers = int(conn.execute(
                "SELECT COUNT(*) FROM attachments WHERE tipo='OFERTA' AND eliminado_en IS NULL"
            ).fetchone()[0])
            images = int(conn.execute(
                "SELECT COUNT(*) FROM attachments WHERE tipo='IMAGEN' AND eliminado_en IS NULL"
            ).fetchone()[0])
            states = {str(row["estado"]): int(row["qty"]) for row in conn.execute(
                "SELECT estado,COUNT(*) qty FROM opportunities WHERE eliminado_en IS NULL GROUP BY estado"
            ).fetchall()}
        except sqlite3.OperationalError:
            return {"total": 0, "subsystems": 0, "equipment": 0, "offers": 0, "images": 0, "states": {}}
        return {"total": total, "subsystems": subsystems, "equipment": equipment, "offers": offers, "images": images, "states": states}


def equipment_summary(tokens: Iterable[tuple[str | None, str]], limit: int = 15) -> list[dict[str, Any]]:
    matches = search_opportunities(tokens, limit=100)
    ids = [int(item["id"]) for item in matches]
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    with readonly_connection() as conn:
        if conn is None:
            return []
        rows = conn.execute(
            f"""SELECT e.tipo_equipo,e.referencia,
                       SUM(CASE WHEN TRIM(e.cantidad) GLOB '[0-9]*' THEN CAST(e.cantidad AS REAL) ELSE 0 END) AS cantidad_total,
                       COUNT(DISTINCT s.opportunity_id) AS proyectos
                FROM equipment e
                JOIN subsystems s ON s.id=e.subsystem_id AND s.eliminado_en IS NULL
                JOIN opportunities o ON o.id=s.opportunity_id AND o.eliminado_en IS NULL
                WHERE s.opportunity_id IN ({marks})
                GROUP BY e.tipo_equipo,e.referencia
                ORDER BY proyectos DESC,cantidad_total DESC,e.tipo_equipo,e.referencia
                LIMIT ?""", ids + [max(1, min(int(limit), 50))]
        ).fetchall()
        return [dict(row) for row in rows]


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _numeric_values(values: Iterable[str]) -> list[float]:
    found: list[float] = []
    for value in values:
        for raw in re.findall(r"\d+(?:[.,]\d+)?", str(value or "")):
            try:
                found.append(float(raw.replace(",", ".")))
            except ValueError:
                pass
    return found


def _numeric_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    best = 0.0
    for a in left:
        for b in right:
            high = max(abs(a), abs(b), 1.0)
            score = max(0.0, 1.0 - abs(a - b) / high)
            best = max(best, score)
    return best


def similar_opportunities(opportunity_id: int, limit: int = 6) -> list[dict[str, Any]]:
    source_id = int(opportunity_id)
    with readonly_connection() as conn:
        if conn is None:
            return []
        source_exists = conn.execute(
            "SELECT 1 FROM opportunities WHERE id=? AND eliminado_en IS NULL", (source_id,)
        ).fetchone()
        if not source_exists:
            return []
        fields = tuple(SIMILARITY_WEIGHTS.keys())
        marks = ",".join("?" for _ in fields)
        rows = conn.execute(
            f"SELECT opportunity_id,field,value_norm FROM search_index WHERE field IN ({marks})",
            fields,
        ).fetchall()
        feature_values: dict[int, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for row in rows:
            feature_values[int(row["opportunity_id"])][str(row["field"])].append(str(row["value_norm"] or ""))
        source = feature_values.get(source_id, {})
        source_sets = {field: _terms(" ".join(source.get(field, []))) for field in fields if field != "flujo"}
        source_flow = _numeric_values(source.get("flujo", []))
        scored: list[tuple[float, int, list[str]]] = []
        for candidate_id, values in feature_values.items():
            if candidate_id == source_id:
                continue
            score = 0.0
            reasons: list[tuple[float, str]] = []
            for field, weight in SIMILARITY_WEIGHTS.items():
                if field == "flujo":
                    similarity = _numeric_similarity(source_flow, _numeric_values(values.get(field, [])))
                else:
                    similarity = _jaccard(source_sets.get(field, set()), _terms(" ".join(values.get(field, []))))
                contribution = weight * similarity
                score += contribution
                if similarity >= 0.20:
                    reasons.append((contribution, field))
            if score > 0.025:
                scored.append((score, candidate_id, [item[1] for item in sorted(reasons, reverse=True)[:4]]))
        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = scored[:max(1, min(int(limit), 20))]
        if not selected:
            return []
        ids = [item[1] for item in selected]
        id_marks = ",".join("?" for _ in ids)
        summaries = conn.execute(
            f"""SELECT o.id,o.radicado,o.proyecto,o.nombre,o.cliente,o.estado,o.industria,o.tipo_oportunidad,
                       (SELECT COUNT(*) FROM subsystems s WHERE s.opportunity_id=o.id AND s.eliminado_en IS NULL) AS subsystem_count
                FROM opportunities o WHERE o.id IN ({id_marks}) AND o.eliminado_en IS NULL""", ids
        ).fetchall()
        by_id = {int(row["id"]): dict(row) for row in summaries}
        result = []
        for score, candidate_id, reasons in selected:
            row = by_id.get(candidate_id)
            if not row:
                continue
            row["similarity"] = round(score * 100, 1)
            row["similarity_reasons"] = reasons
            result.append(row)
        return result


def tool_manifest() -> tuple[dict[str, Any], ...]:
    """Public manifest for the future LLM tool layer. Every tool is read-only."""
    return (
        {"name": "buscar_oportunidades", "mode": "READ_ONLY"},
        {"name": "contar_oportunidades", "mode": "READ_ONLY"},
        {"name": "obtener_oportunidad", "mode": "READ_ONLY"},
        {"name": "buscar_por_id", "mode": "READ_ONLY"},
        {"name": "listar_ofertas", "mode": "READ_ONLY"},
        {"name": "listar_imagenes", "mode": "READ_ONLY"},
        {"name": "resumir_equipos", "mode": "READ_ONLY"},
        {"name": "buscar_similares", "mode": "READ_ONLY"},
        {"name": "estadisticas_oportunidades", "mode": "READ_ONLY"},
    )
