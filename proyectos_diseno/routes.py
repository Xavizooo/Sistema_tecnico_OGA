from __future__ import annotations

import os
import shutil
import threading
import uuid
import webbrowser
from datetime import date, datetime
from pathlib import Path
from werkzeug.utils import secure_filename
from typing import Any, Dict, List

from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory, url_for

from .services import (
    STAGE_COLORS,
    STAGE_NAMES,
    PROJECT_TYPES,
    add_business_days,
    alert_for_project,
    approval_days,
    business_days,
    colombia_holidays,
    current_phase,
    designer_daily_hours,
    holiday_dates,
    iso,
    parse_date,
    planned_hours_and_cost,
    progress_metrics,
    project_phase_days,
    project_elapsed_business_days,
    project_periods,
    periods_by_stage,
    stage_bounds,
    project_segments,
    validate_project_dates,
)
from .storage import DATASETS, ExcelStorage, StorageError


APP_DIR = Path(__file__).resolve().parent
BASES_DIR = APP_DIR / "BASES_DE_DATOS"
BACKUP_DIR = APP_DIR / "COPIAS_DE_SEGURIDAD"
# REV20.1: las imagenes pasan a una carpeta persistente dentro de BASES_DE_DATOS.
# Asi no se pierden al reemplazar solamente el codigo en futuras actualizaciones.
IMAGE_DIR = BASES_DIR / "IMAGENES_PROYECTOS"
LEGACY_IMAGE_DIR = APP_DIR / "IMAGENES_PROYECTOS"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def migrate_legacy_project_images() -> None:
    """Copia imagenes de versiones anteriores a la ubicacion persistente."""
    if not LEGACY_IMAGE_DIR.exists() or LEGACY_IMAGE_DIR.resolve() == IMAGE_DIR.resolve():
        return
    for candidate in LEGACY_IMAGE_DIR.iterdir():
        if not candidate.is_file() or candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        target = IMAGE_DIR / candidate.name
        if not target.exists():
            try:
                shutil.copy2(candidate, target)
            except OSError:
                pass


migrate_legacy_project_images()

bp = Blueprint(
    "proyectos_diseno",
    __name__,
    template_folder="templates",
    static_folder="static",
)
storage = ExcelStorage(BASES_DIR, BACKUP_DIR)

HISTORY_STATUSES = {
    "PRODUCCION": "#3b82f6",
    "ENSAMBLE": "#ef4444",
    "DESPACHADO": "#22c55e",
    "PUESTA EN MARCHA": "#f06292",
    "FINALIZADO": "#7dd3fc",
}


def uid() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def project_number_key(project: Dict[str, Any]) -> tuple[int, str]:
    """Ordena números de proyecto como números y deja códigos mixtos al final."""
    text = str(project.get("numero", "")).strip().upper()
    digits = "".join(ch for ch in text if ch.isdigit())
    return (int(digits) if digits else 10**18, text)


def payload() -> Dict[str, Any]:
    return request.get_json(silent=True) or {}


def ok(data: Any = None, message: str = ""):
    body: Dict[str, Any] = {"ok": True}
    if data is not None:
        body["data"] = data
    if message:
        body["message"] = message
    return jsonify(body)


def fail(message: str, status: int = 400, details: Any = None):
    body: Dict[str, Any] = {"ok": False, "message": message}
    if details is not None:
        body["details"] = details
    return jsonify(body), status


@bp.errorhandler(StorageError)
def handle_storage_error(exc: StorageError):
    return fail(str(exc), 400)


@bp.errorhandler(ValueError)
def handle_value_error(exc: ValueError):
    return fail(str(exc), 400)


@bp.errorhandler(Exception)
def handle_unexpected(exc: Exception):
    current_app.logger.exception("Error inesperado")
    return fail(f"Error inesperado: {exc}", 500)


def seed_holidays_if_empty() -> None:
    if storage.read("holidays"):
        return
    rows = []
    for year in (date.today().year, date.today().year + 1):
        for day, name in colombia_holidays(year):
            rows.append({
                "id": uid(), "fecha": day.isoformat(), "nombre": name,
                "origen": "Colombia automático", "activo": True,
            })
    storage.write("holidays", rows)


seed_holidays_if_empty()


def seed_project_sizes_if_empty() -> None:
    if storage.read("project_sizes"):
        return
    defaults = [("BAJO",1,3),("MEDIO BAJO",4,10),("MEDIO",11,15),("MEDIO ALTO",16,20),("ALTO",21,100)]
    storage.write("project_sizes", [
        {"id": uid(), "nombre": name, "minimo": low, "maximo": high, "activo": True}
        for name, low, high in defaults
    ])

seed_project_sizes_if_empty()


def migrate_legacy_upcoming_projects() -> None:
    """Mueve a la hoja informativa los registros creados con la función V07.

    En V07 los proyectos por empezar se guardaban dentro de Proyectos.xlsx y por
    eso afectaban calendario, horas e indicadores. Se reconocen únicamente los
    registros sin ninguna etapa programada, sin equipos y sin actividades cumplidas.
    """
    projects = storage.read("projects")
    progress = storage.read("project_progress")
    equipment = storage.read("project_equipment")
    upcoming = storage.read("upcoming_projects")
    upcoming_numbers = {str(r.get("numero", "")).strip().upper() for r in upcoming}
    move_ids: set[str] = set()
    kept: List[Dict[str, Any]] = []
    changed = False

    for project in projects:
        project_id = str(project.get("id", ""))
        project_progress = [r for r in progress if str(r.get("project_id", "")) == project_id]
        project_equipment = [r for r in equipment if str(r.get("project_id", "")) == project_id]
        no_schedule = not any(project.get(field) for field in (
            "etapa1_fin", "fecha_aprobacion", "etapa2_inicio", "etapa2_fin",
            "etapa3_inicio", "etapa3_fin",
        ))
        untouched_progress = all(not bool(r.get("cumplida")) for r in project_progress)
        legacy_upcoming = (
            str(project.get("estado", "Activo")) != "Finalizado"
            and no_schedule
            and not project_equipment
            and untouched_progress
        )
        if not legacy_upcoming:
            kept.append(project)
            continue

        number = str(project.get("numero", "")).strip().upper()
        if number and number not in upcoming_numbers:
            upcoming.append({
                "id": uid(),
                "numero": number,
                "cliente": str(project.get("cliente", "")).strip(),
                "designer_id": str(project.get("designer_id", "")).strip(),
                "fecha_inicio": iso(parse_date(project.get("fecha_inicio"))),
                "dias_referencia": float(project.get("dias_referencia") or 0),
                "creado_en": project.get("creado_en") or now_iso(),
                "actualizado_en": now_iso(),
            })
            upcoming_numbers.add(number)
        move_ids.add(project_id)
        changed = True

    if changed:
        storage.write("projects", kept)
        storage.write("upcoming_projects", upcoming)
        storage.write("project_progress", [r for r in progress if str(r.get("project_id", "")) not in move_ids])
        storage.write("project_equipment", [r for r in equipment if str(r.get("project_id", "")) not in move_ids])


migrate_legacy_upcoming_projects()


def activity_types(value: Any) -> set[str]:
    if isinstance(value, list):
        parts = value
    else:
        parts = str(value or "").replace(";", ",").split(",")
    return {str(item).strip().upper() for item in parts if str(item).strip().upper() in PROJECT_TYPES}


def activity_totals(active_only: bool = True) -> Dict[str, float]:
    totals = {code: 0.0 for code in PROJECT_TYPES}
    for row in storage.read("activities"):
        if active_only and not bool(row.get("activa", True)):
            continue
        for code in activity_types(row.get("tipos_proyecto")):
            totals[code] += float(row.get("porcentaje") or 0)
    return {code: round(value, 2) for code, value in totals.items()}


def activity_total(project_type: str = "T1", active_only: bool = True) -> float:
    return activity_totals(active_only=active_only).get(str(project_type).upper(), 0.0)


def validate_activity_totals(require_complete: bool = False) -> Dict[str, float]:
    totals = activity_totals()
    for code, total in totals.items():
        if total > 100.0001:
            raise ValueError(f"Las actividades de {code} no pueden superar 100 %.")
        if require_complete and abs(total - 100.0) > 0.001:
            raise ValueError(f"Las actividades de {code} deben sumar exactamente 100 %; actualmente suman {total:g} %.")
    return totals


def refresh_active_project_activity_percentages(activity_id: str | None = None) -> Dict[str, int]:
    """v18: sincroniza nombre en todos los proyectos y porcentaje solo en activos.

    Los históricos conservan el porcentaje con el que cerraron, pero si cambia el
    nombre de una actividad el nuevo nombre se refleja tanto en activos como históricos.
    """
    activity_filter = str(activity_id or "").strip()
    catalog = {
        str(row.get("id", "")): {"porcentaje": float(row.get("porcentaje") or 0), "nombre": str(row.get("nombre") or "").strip()}
        for row in storage.read("activities")
        if str(row.get("id", "")).strip() and (not activity_filter or str(row.get("id")) == activity_filter)
    }
    if not catalog:
        return {"updated_projects": 0, "updated_rows": 0, "renamed_rows": 0}
    projects = storage.read("projects")
    active_ids = {str(p.get("id", "")) for p in projects if str(p.get("estado", "Activo")).strip().lower() != "finalizado"}
    progress_rows = storage.read("project_progress")
    updated_project_ids: set[str] = set(); updated_rows = 0; renamed_rows = 0
    for row in progress_rows:
        key = str(row.get("activity_id", "")); info = catalog.get(key)
        if not info: continue
        project_id = str(row.get("project_id", "")); changed = False
        if str(row.get("actividad", "")) != info["nombre"]:
            row["actividad"] = info["nombre"]; renamed_rows += 1; changed = True
        if project_id in active_ids:
            old = float(row.get("porcentaje") or 0); new = info["porcentaje"]
            if abs(old-new) > 0.000001:
                row["porcentaje"] = new; updated_rows += 1; changed = True
        if changed: updated_project_ids.add(project_id)
    if updated_project_ids:
        storage.write("project_progress", progress_rows); stamp=now_iso()
        for project in projects:
            if str(project.get("id", "")) in updated_project_ids: project["actualizado_en"] = stamp
        storage.write("projects", projects)
    return {"updated_projects": len(updated_project_ids), "updated_rows": updated_rows, "renamed_rows": renamed_rows}

def refresh_additional_durations() -> None:
    """Recalcula automáticamente la duración hábil de todos los adicionales."""
    rows = storage.read("additionals")
    holidays = holiday_dates(storage.read("holidays"))
    changed = False
    for row in rows:
        start = parse_date(row.get("fecha_inicio"))
        end = parse_date(row.get("fecha_finalizacion"))
        value = len(business_days(start, end, holidays)) if start and end and end >= start else 0
        if int(float(row.get("dias_duracion") or 0)) != value:
            row["dias_duracion"] = value
            row["actualizado_en"] = now_iso()
            changed = True
    if changed:
        storage.write("additionals", rows)


def refresh_approval_day_values() -> None:
    """Mantiene Proyectos.xlsx sincronizado con los días hábiles de aprobación."""
    projects = storage.read("projects")
    all_periods = storage.read("stage_periods")
    holidays = holiday_dates(storage.read("holidays"))
    changed = False
    for project in projects:
        working = dict(project)
        working["stage_periods"] = [r for r in all_periods if str(r.get("project_id")) == str(project.get("id"))]
        value = approval_days(working, holidays) if project.get("fecha_aprobacion") else 0
        if int(float(project.get("dias_aprobacion") or 0)) != value:
            project["dias_aprobacion"] = value
            changed = True
    if changed:
        storage.write("projects", projects)

# Rev13: al iniciar, los proyectos activos adoptan los porcentajes vigentes del catálogo.
refresh_active_project_activity_percentages()
refresh_additional_durations()


def build_context() -> Dict[str, Any]:
    designers = storage.read("designers")
    pmps = storage.read("pmps")
    activities = storage.read("activities")
    equipment = storage.read("equipment")
    holidays = storage.read("holidays")
    projects = storage.read("projects")
    stage_periods = storage.read("stage_periods")
    project_equipment = storage.read("project_equipment")
    project_progress = storage.read("project_progress")
    upcoming_projects = storage.read("upcoming_projects")
    additionals = storage.read("additionals")
    project_sizes = storage.read("project_sizes")
    project_revisions = storage.read("project_revisions")
    return {
        "designers": designers,
        "pmps": pmps,
        "activities": activities,
        "equipment": equipment,
        "holidays": holidays,
        "projects": projects,
        "stage_periods": stage_periods,
        "upcoming_projects": upcoming_projects,
        "additionals": additionals,
        "project_sizes": project_sizes,
        "project_revisions": project_revisions,
        "project_equipment": project_equipment,
        "project_progress": project_progress,
    }

def resolve_project_image(project: Dict[str, Any]) -> str:
    stored = str(project.get("imagen_path") or "").strip()
    number = "".join(ch for ch in str(project.get("numero") or "").lower() if ch.isalnum())
    if not number:
        return ""
    # Ubicacion principal persistente. Como compatibilidad, tambien busca la carpeta antigua.
    search_dirs = [IMAGE_DIR]
    if LEGACY_IMAGE_DIR.exists() and LEGACY_IMAGE_DIR.resolve() != IMAGE_DIR.resolve():
        search_dirs.append(LEGACY_IMAGE_DIR)
    if stored:
        stored_normalized = "".join(ch for ch in stored.lower() if ch.isalnum())
        if number in stored_normalized:
            for directory in search_dirs:
                if (directory / stored).exists():
                    if directory != IMAGE_DIR and not (IMAGE_DIR / stored).exists():
                        try:
                            shutil.copy2(directory / stored, IMAGE_DIR / stored)
                        except OSError:
                            pass
                    return stored
    for directory in search_dirs:
        for candidate in directory.iterdir():
            if not candidate.is_file() or candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            normalized = "".join(ch for ch in candidate.name.lower() if ch.isalnum())
            if number in normalized:
                if directory != IMAGE_DIR and not (IMAGE_DIR / candidate.name).exists():
                    try:
                        shutil.copy2(candidate, IMAGE_DIR / candidate.name)
                    except OSError:
                        pass
                return candidate.name
    return ""

def enrich_project(project: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    working = dict(project)
    periods = sorted(
        [r for r in ctx["stage_periods"] if str(r.get("project_id")) == str(project["id"])],
        key=lambda r: (int(float(r.get("etapa") or 0)), str(r.get("inicio")), int(float(r.get("orden") or 0))),
    )
    working["stage_periods"] = periods
    designer = next((d for d in ctx["designers"] if d["id"] == project.get("designer_id")), None)
    pmp = next((item for item in ctx.get("pmps", []) if item.get("id") == project.get("pmp_id")), None)
    size = next((item for item in ctx.get("project_sizes", []) if item.get("id") == project.get("tamano_id")), None)
    revisions = sorted([r for r in ctx.get("project_revisions", []) if str(r.get("project_id")) == str(project.get("id"))], key=lambda r: (str(r.get("fecha", "")), str(r.get("numero_revision", ""))))
    progress_rows = [r for r in ctx["project_progress"] if r.get("project_id") == project["id"]]
    equipment_rows = [r for r in ctx["project_equipment"] if r.get("project_id") == project["id"]]
    metrics = progress_metrics(progress_rows)
    phase = current_phase(working, metrics)
    hset = holiday_dates(ctx["holidays"])
    hours, cost, cost_detail = planned_hours_and_cost(working, designer, hset)
    alert = alert_for_project(working, phase, hset)
    reference_days = int(round(float(project.get("dias_referencia") or 0)))
    start_date = parse_date(project.get("fecha_inicio"))
    tentative = add_business_days(start_date, max(1, reference_days), hset) if reference_days and start_date else start_date
    approval_count = approval_days(working, hset)
    phase_days = project_phase_days(working, hset)
    grouped = periods_by_stage(working)
    result = dict(project)
    resolved_image = resolve_project_image(project)
    result.update({
        "stage_periods": periods,
        "periods_by_stage": {str(stage): grouped[stage] for stage in (0, 1, 2, 3)},
        "project_type_name": PROJECT_TYPES.get(str(project.get("tipo_proyecto", "T1")), str(project.get("tipo_proyecto", "T1"))),
        "designer": designer,
        "designer_name": designer.get("nombre") if designer else "Sin diseñador",
        "pmp": pmp,
        "pmp_name": (pmp.get("nombre") if pmp else None) or project.get("pmp_nombre") or "Sin PMP",
        "bodega": str(project.get("bodega") or ""),
        "project_size": size,
        "tamano_nombre": (size.get("nombre") if size else None) or project.get("tamano_nombre") or "Sin tamaño",
        "revision_rows": revisions,
        "numero_revisiones": len(revisions),
        "imagen_path": resolved_image,
        "imagen_url": url_for("proyectos_diseno.project_image", filename=resolved_image) if resolved_image else "",
        "estatus_historico": str(project.get("estatus_historico") or ("PRODUCCION" if str(project.get("estado")) == "Finalizado" else "")),
        "designer_color": designer.get("color") if designer else "#64748b",
        "progress_rows": sorted(progress_rows, key=lambda r: (int(float(r.get("etapa") or 0)), str(r.get("actividad")))),
        "equipment_rows": equipment_rows,
        "metrics": metrics,
        "phase": phase,
        "planned_hours": hours,
        "planned_cost": cost,
        "cost_detail": cost_detail,
        "approval_days": approval_count,
        "dias_aprobacion": approval_count,
        "phase_days": phase_days,
        "elapsed_days_from_reception": project_elapsed_business_days(working, hset),
        "tentative_end": iso(tentative),
        "alert": alert,
        "is_upcoming": str(project.get("estado")) != "Finalizado" and (start_date or date.min) > date.today(),
    })
    return result

def enriched_upcoming_projects(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    designers = {str(d.get("id")): d for d in ctx["designers"]}
    rows: List[Dict[str, Any]] = []
    for item in ctx.get("upcoming_projects", []):
        designer = designers.get(str(item.get("designer_id", "")))
        row = dict(item)
        row["designer_name"] = designer.get("nombre") if designer else "Sin diseñador"
        row["designer_color"] = designer.get("color") if designer else "#64748b"
        rows.append(row)
    return sorted(rows, key=project_number_key)


def dashboard_data(
    designer_id: str = "",
    project_id: str = "",
    project_ids: List[str] | None = None,
    include_history: bool = False,
    view_mode: str = "general",
) -> Dict[str, Any]:
    ctx = build_context()
    enriched = sorted([enrich_project(p, ctx) for p in ctx["projects"]], key=project_number_key)
    active = [p for p in enriched if p.get("estado") != "Finalizado"]
    history = [p for p in enriched if p.get("estado") == "Finalizado"]

    selected_ids = {str(x) for x in (project_ids or []) if str(x)}
    selected_project = next((p for p in enriched if p["id"] == project_id), None) if project_id else None
    if selected_ids:
        visible = [p for p in (enriched if include_history else active) if str(p.get("id")) in selected_ids]
    elif selected_project:
        visible = [selected_project]
    elif designer_id:
        visible = [p for p in (enriched if include_history else active) if p.get("designer_id") == designer_id]
    else:
        visible = history if include_history else active

    filtered = bool(project_id or selected_ids or designer_id)
    project_view = view_mode == "project"
    calendar_rows: List[Dict[str, Any]] = []
    if project_view:
        for p in sorted(visible, key=project_number_key):
            calendar_rows.append({
                "id": p["id"], "label": f"{p['numero']} · {p['cliente']}",
                "designer_name": p.get("designer_name") or "Sin diseñador",
                "designer_color": p.get("designer_color") or "#64748b",
                "pmp_name": p.get("pmp_name") or "Sin PMP",
                "bodega": p.get("bodega") or "—",
                "color": p["designer_color"],
                "projects": [{
                    "id": p["id"], "numero": p["numero"], "cliente": p["cliente"],
                    "color": p["designer_color"], "segments": project_segments(p, filtered=True),
                }],
            })
    elif not filtered:
        for designer in [d for d in ctx["designers"] if bool(d.get("activo", True))]:
            projects_for_designer = sorted(
                [p for p in visible if p.get("designer_id") == designer["id"]],
                key=project_number_key,
            )
            if not projects_for_designer:
                continue
            calendar_rows.append({
                "id": designer["id"], "label": designer["nombre"], "color": designer["color"],
                "projects": [
                    {
                        "id": p["id"], "numero": p["numero"], "cliente": p["cliente"],
                        "color": designer["color"], "segments": project_segments(p, filtered=False),
                    }
                    for p in projects_for_designer
                ],
            })
        # Proyectos sin diseñador no deben desaparecer.
        unassigned = [p for p in visible if not p.get("designer_id")]
        if unassigned:
            calendar_rows.append({
                "id": "unassigned", "label": "Sin diseñador", "color": "#64748b",
                "projects": [{
                    "id": p["id"], "numero": p["numero"], "cliente": p["cliente"],
                    "color": "#64748b", "segments": project_segments(p, filtered=False),
                } for p in unassigned],
            })
    else:
        for p in visible:
            calendar_rows.append({
                "id": p["id"], "label": f"{p['numero']} · {p['cliente']}",
                "designer_name": p.get("designer_name") or "Sin diseñador",
                "designer_color": p.get("designer_color") or "#64748b",
                "pmp_name": p.get("pmp_name") or "Sin PMP",
                "bodega": p.get("bodega") or "—",
                "color": p["designer_color"],
                "projects": [{
                    "id": p["id"], "numero": p["numero"], "cliente": p["cliente"],
                    "color": p["designer_color"], "segments": project_segments(p, filtered=True),
                }],
            })

    visible_active = [p for p in visible if p.get("estado") != "Finalizado"]
    alerts = [
        {
            "project_id": p["id"], "numero": p["numero"], "cliente": p["cliente"],
            "designer": p["designer_name"], "phase": p["phase"]["label"], **p["alert"],
        }
        for p in visible_active if p.get("alert")
    ]
    # Esta lista es únicamente informativa y no depende de filtros, calendario ni métricas.
    upcoming = enriched_upcoming_projects(ctx)

    total_hours = round(sum(float(p["planned_hours"]) for p in visible), 2)
    total_cost = round(sum(float(p["planned_cost"]) for p in visible), 2)
    weighted_progress = round(sum(float(p["metrics"]["avance"]) for p in visible) / len(visible), 2) if visible else 0
    designer_workload = []
    for designer in ctx["designers"]:
        dprojects = [p for p in visible_active if p.get("designer_id") == designer["id"]]
        if dprojects:
            designer_workload.append({
                "id": designer["id"], "nombre": designer["nombre"], "color": designer["color"],
                "projects": len(dprojects),
                "hours": round(sum(float(p["planned_hours"]) for p in dprojects), 2),
                "cost": round(sum(float(p["planned_cost"]) for p in dprojects), 2),
            })

    return {
        "designers": ctx["designers"],
        "projects": visible,
        "all_active_projects": active,
        "history": history,
        "upcoming": upcoming,
        "alerts": alerts,
        "calendar_rows": calendar_rows,
        "stage_colors": STAGE_COLORS,
        "stage_names": STAGE_NAMES,
        "summary": {
            "active_projects": len(visible_active), "visible_projects": len(visible),
            "progress": weighted_progress, "hours": total_hours, "cost": total_cost,
            "late_projects": sum(1 for a in alerts if a["type"] == "danger"),
        },
        "designer_workload": designer_workload,
        "selected": {"designer_id": designer_id, "project_id": project_id, "project_ids": sorted(selected_ids), "history": include_history, "view_mode": view_mode},
        "activity_total": activity_total(),
        "activity_totals": activity_totals(),
        "project_types": PROJECT_TYPES,
    }


@bp.get("/")
def index():
    return render_template("index.html", app_name="PROYECTOS DISEÑO MECÁNICO", project_design_page=True)


@bp.get("/api/init")
def api_init():
    return ok({
        "dashboard": dashboard_data(),
        "catalogs": {
            "designers": storage.read("designers"),
            "pmps": storage.read("pmps"),
            "activities": storage.read("activities"),
            "equipment": storage.read("equipment"),
            "holidays": storage.read("holidays"),
            "additionals": storage.read("additionals"),
            "project_sizes": storage.read("project_sizes"),
            "project_types": PROJECT_TYPES,
            "history_statuses": HISTORY_STATUSES,
        },
        "paths": {"bases": str(BASES_DIR), "backup": str(BACKUP_DIR)},
    })


@bp.get("/api/dashboard")
def api_dashboard():
    return ok(dashboard_data(
        designer_id=request.args.get("designer_id", ""),
        project_id=request.args.get("project_id", ""),
        project_ids=[item for item in request.args.get("project_ids", "").split(",") if item],
        include_history=request.args.get("history", "0") == "1",
        view_mode=request.args.get("view", "general"),
    ))


# ----------------------------- Diseñadores -----------------------------
@bp.get("/api/designers")
def list_designers():
    return ok(storage.read("designers"))


@bp.post("/api/designers")
def create_designer():
    data = payload()
    name = str(data.get("nombre", "")).strip()
    if not name:
        raise ValueError("El nombre del diseñador es obligatorio.")
    if any(str(r.get("nombre", "")).lower() == name.lower() for r in storage.read("designers")):
        raise ValueError("Ya existe un diseñador con ese nombre.")
    row = {
        "id": uid(), "nombre": name, "color": data.get("color") or "#1268c9",
        "costo_mensual_empresa": float(data.get("costo_mensual_empresa") or 0),
        "hora_entrada": data.get("hora_entrada") or "07:00",
        "hora_salida": data.get("hora_salida") or "17:00",
        "almuerzo_inicio": data.get("almuerzo_inicio") or "12:00",
        "almuerzo_fin": data.get("almuerzo_fin") or "13:00",
        "activo": True,
    }
    hours = designer_daily_hours(row)
    if hours <= 0:
        raise ValueError("El horario del diseñador no genera horas laborables válidas.")
    storage.upsert("designers", row)
    row["horas_diarias"] = hours
    return ok(row, "Diseñador creado.")


@bp.put("/api/designers/<row_id>")
def update_designer(row_id: str):
    current = storage.get("designers", row_id)
    if not current:
        return fail("Diseñador no encontrado.", 404)
    current.update(payload())
    current["id"] = row_id
    if designer_daily_hours(current) <= 0:
        raise ValueError("El horario del diseñador no genera horas laborables válidas.")
    storage.upsert("designers", current)
    return ok(current, "Diseñador actualizado.")


@bp.delete("/api/designers/<row_id>")
def delete_designer(row_id: str):
    current = storage.get("designers", row_id)
    if not current:
        return fail("Diseñador no encontrado.", 404)
    if any(p.get("designer_id") == row_id for p in storage.read("projects")):
        current["activo"] = False
        storage.upsert("designers", current)
        return ok(current, "El diseñador tiene proyectos y quedó inactivo.")
    storage.delete("designers", row_id)
    return ok(message="Diseñador eliminado.")


# ----------------------------- PMP -----------------------------
@bp.get("/api/pmps")
def list_pmps():
    return ok(storage.read("pmps"))


@bp.post("/api/pmps")
def create_pmp():
    data = payload()
    name = str(data.get("nombre", "")).strip()
    if not name:
        raise ValueError("El nombre de la PMP es obligatorio.")
    if any(str(r.get("nombre", "")).strip().lower() == name.lower() for r in storage.read("pmps")):
        raise ValueError("Ya existe una PMP con ese nombre.")
    row = {"id": uid(), "nombre": name, "activo": True}
    storage.upsert("pmps", row)
    return ok(row, "PMP creada.")


@bp.put("/api/pmps/<row_id>")
def update_pmp(row_id: str):
    current = storage.get("pmps", row_id)
    if not current:
        return fail("PMP no encontrada.", 404)
    name = str(payload().get("nombre", current.get("nombre", ""))).strip()
    if not name:
        raise ValueError("El nombre de la PMP es obligatorio.")
    if any(str(r.get("id")) != row_id and str(r.get("nombre", "")).strip().lower() == name.lower() for r in storage.read("pmps")):
        raise ValueError("Ya existe otra PMP con ese nombre.")
    current["nombre"] = name
    storage.upsert("pmps", current)
    return ok(current, "PMP actualizada.")


@bp.delete("/api/pmps/<row_id>")
def delete_pmp(row_id: str):
    current = storage.get("pmps", row_id)
    if not current:
        return fail("PMP no encontrada.", 404)
    if any(str(p.get("pmp_id", "")) == row_id for p in storage.read("projects")):
        current["activo"] = False
        storage.upsert("pmps", current)
        return ok(current, "La PMP está asignada a proyectos y quedó inactiva.")
    storage.delete("pmps", row_id)
    return ok(message="PMP eliminada.")


# ----------------------------- Actividades -----------------------------
@bp.get("/api/activities")
def list_activities():
    return ok({"rows": storage.read("activities"), "totals": activity_totals(), "project_types": PROJECT_TYPES})


@bp.post("/api/activities")
def create_activity():
    data = payload()
    name = str(data.get("nombre", "")).strip()
    stage = int(data.get("etapa") or 0)
    pct = float(data.get("porcentaje") or 0)
    types = activity_types(data.get("tipos_proyecto"))
    if not name:
        raise ValueError("El nombre de la actividad es obligatorio.")
    if stage not in {1, 2, 3}:
        raise ValueError("Seleccione la Etapa 01, 02 o 03.")
    if pct <= 0 or pct > 100:
        raise ValueError("El porcentaje debe ser mayor que 0 y máximo 100.")
    if not types:
        raise ValueError("Seleccione al menos un tipo de proyecto.")
    totals = activity_totals()
    for code in types:
        if totals[code] + pct > 100.0001:
            raise ValueError(f"Las actividades de {code} no pueden superar 100 %.")
    row = {
        "id": uid(), "nombre": name, "etapa": stage, "porcentaje": pct,
        "tipos_proyecto": ",".join(sorted(types)), "activa": True,
    }
    storage.upsert("activities", row)
    return ok({"row": row, "totals": activity_totals()}, "Actividad creada.")


@bp.put("/api/activities/<row_id>")
def update_activity(row_id: str):
    current = storage.get("activities", row_id)
    if not current:
        return fail("Actividad no encontrada.", 404)
    data = payload()
    candidate = dict(current)
    candidate.update(data)
    candidate["id"] = row_id
    candidate["nombre"] = str(candidate.get("nombre", "")).strip()
    candidate["etapa"] = int(candidate.get("etapa") or 0)
    candidate["porcentaje"] = float(candidate.get("porcentaje") or 0)
    types = activity_types(candidate.get("tipos_proyecto"))
    candidate["tipos_proyecto"] = ",".join(sorted(types))
    if not candidate["nombre"] or candidate["etapa"] not in {1, 2, 3} or candidate["porcentaje"] <= 0:
        raise ValueError("Revise el nombre, la etapa y el porcentaje de la actividad.")
    if not types:
        raise ValueError("Seleccione al menos un tipo de proyecto.")
    rows = [candidate if str(r.get("id")) == row_id else r for r in storage.read("activities")]
    totals = {code: 0.0 for code in PROJECT_TYPES}
    for row in rows:
        if not bool(row.get("activa", True)):
            continue
        for code in activity_types(row.get("tipos_proyecto")):
            totals[code] += float(row.get("porcentaje") or 0)
    for code, total in totals.items():
        if total > 100.0001:
            raise ValueError(f"Las actividades de {code} no pueden superar 100 %.")
    storage.upsert("activities", candidate)
    propagation = refresh_active_project_activity_percentages(row_id)
    return ok({
        "row": candidate,
        "totals": activity_totals(),
        **propagation,
    }, "Actividad actualizada y proyectos activos recalculados.")


@bp.delete("/api/activities/<row_id>")
def delete_activity(row_id: str):
    current = storage.get("activities", row_id)
    if not current:
        return fail("Actividad no encontrada.", 404)
    if any(r.get("activity_id") == row_id for r in storage.read("project_progress")):
        current["activa"] = False
        storage.upsert("activities", current)
        return ok({"row": current, "totals": activity_totals()}, "La actividad ya fue usada y quedó inactiva.")
    storage.delete("activities", row_id)
    return ok({"totals": activity_totals()}, "Actividad eliminada.")


# ----------------------------- Equipos -----------------------------

# ----------------------------- Equipos -----------------------------
@bp.get("/api/equipment")
def list_equipment():
    return ok(storage.read("equipment"))


@bp.post("/api/equipment")
def create_equipment():
    data = payload()
    code = str(data.get("codigo", "")).strip().upper()
    name = str(data.get("nombre", "")).strip()
    if not code or not name:
        raise ValueError("Código y nombre del equipo son obligatorios.")
    if any(str(r.get("codigo", "")).upper() == code for r in storage.read("equipment")):
        raise ValueError("Ya existe un equipo con ese código.")
    row = {
        "id": uid(), "codigo": code, "nombre": name,
        "dias_estandar": float(data.get("dias_estandar") or 0),
        "dias_medio": float(data.get("dias_medio") or 0),
        "dias_no_estandar": float(data.get("dias_no_estandar") or 0),
        "dias_complejo": float(data.get("dias_complejo") or 0),
        "activo": True,
    }
    storage.upsert("equipment", row)
    return ok(row, "Equipo creado.")


@bp.put("/api/equipment/<row_id>")
def update_equipment(row_id: str):
    current = storage.get("equipment", row_id)
    if not current:
        return fail("Equipo no encontrado.", 404)
    current.update(payload())
    current["id"] = row_id
    storage.upsert("equipment", current)
    return ok(current, "Equipo actualizado.")


@bp.delete("/api/equipment/<row_id>")
def delete_equipment(row_id: str):
    current = storage.get("equipment", row_id)
    if not current:
        return fail("Equipo no encontrado.", 404)
    if any(r.get("equipment_id") == row_id for r in storage.read("project_equipment")):
        current["activo"] = False
        storage.upsert("equipment", current)
        return ok(current, "El equipo ya fue usado y quedó inactivo.")
    storage.delete("equipment", row_id)
    return ok(message="Equipo eliminado.")


# ----------------------------- Tamaños de proyecto -----------------------------
@bp.get("/api/project-sizes")
def list_project_sizes():
    return ok(storage.read("project_sizes"))

@bp.post("/api/project-sizes")
def create_project_size():
    data = payload(); name = str(data.get("nombre", "")).strip().upper()
    low = int(float(data.get("minimo") or 0)); high = int(float(data.get("maximo") or 0))
    if not name or low <= 0 or high < low:
        raise ValueError("Revise el nombre y el rango del tamaño de proyecto.")
    if any(str(r.get("nombre","")).strip().upper()==name for r in storage.read("project_sizes")):
        raise ValueError("Ya existe un tamaño con ese nombre.")
    row={"id":uid(),"nombre":name,"minimo":low,"maximo":high,"activo":True}; storage.upsert("project_sizes",row); return ok(row,"Tamaño creado.")

@bp.put("/api/project-sizes/<row_id>")
def update_project_size(row_id: str):
    row=storage.get("project_sizes",row_id)
    if not row: return fail("Tamaño no encontrado.",404)
    data=payload(); row["nombre"]=str(data.get("nombre",row.get("nombre",""))).strip().upper(); row["minimo"]=int(float(data.get("minimo",row.get("minimo",0)) or 0)); row["maximo"]=int(float(data.get("maximo",row.get("maximo",0)) or 0))
    if not row["nombre"] or row["minimo"]<=0 or row["maximo"]<row["minimo"]: raise ValueError("Revise el nombre y el rango del tamaño de proyecto.")
    storage.upsert("project_sizes",row)
    # Conserva el nombre histórico/asignado actualizado en proyectos vinculados.
    projects=storage.read("projects"); changed=False
    for project in projects:
        if str(project.get("tamano_id"))==row_id:
            project["tamano_nombre"]=row["nombre"]; changed=True
    if changed: storage.write("projects",projects)
    return ok(row,"Tamaño actualizado.")

@bp.delete("/api/project-sizes/<row_id>")
def delete_project_size(row_id: str):
    row=storage.get("project_sizes",row_id)
    if not row: return fail("Tamaño no encontrado.",404)
    if any(str(p.get("tamano_id"))==row_id for p in storage.read("projects")):
        row["activo"]=False; storage.upsert("project_sizes",row); return ok(row,"El tamaño está asignado y quedó inactivo.")
    storage.delete("project_sizes",row_id); return ok(message="Tamaño eliminado.")

# ----------------------------- Festivos -----------------------------
@bp.get("/api/holidays")
def list_holidays():
    return ok(storage.read("holidays"))


@bp.post("/api/holidays")
def create_holiday():
    data = payload()
    day = parse_date(data.get("fecha"))
    if not day:
        raise ValueError("La fecha del festivo es obligatoria.")
    rows = storage.read("holidays")
    if any(r.get("fecha") == day.isoformat() for r in rows):
        raise ValueError("Esa fecha ya está registrada como festivo.")
    row = {
        "id": uid(), "fecha": day.isoformat(), "nombre": str(data.get("nombre") or "Fecha no laborable"),
        "origen": "Manual", "activo": True,
    }
    storage.upsert("holidays", row)
    refresh_approval_day_values()
    refresh_additional_durations()
    return ok(row, "Festivo agregado.")


@bp.post("/api/holidays/colombia/<int:year>")
def load_colombia_holidays(year: int):
    rows = storage.read("holidays")
    by_date = {r.get("fecha"): r for r in rows}
    added = 0
    for day, name in colombia_holidays(year):
        key = day.isoformat()
        if key in by_date:
            continue
        row = {"id": uid(), "fecha": key, "nombre": name, "origen": "Colombia automático", "activo": True}
        rows.append(row)
        by_date[key] = row
        added += 1
    storage.write("holidays", rows)
    refresh_approval_day_values()
    refresh_additional_durations()
    return ok({"added": added, "rows": rows}, f"Se agregaron {added} festivos de Colombia para {year}.")


@bp.delete("/api/holidays/<row_id>")
def delete_holiday(row_id: str):
    if not storage.delete("holidays", row_id):
        return fail("Festivo no encontrado.", 404)
    refresh_approval_day_values()
    refresh_additional_durations()
    return ok(message="Festivo eliminado.")


# ----------------------------- Adicionales -----------------------------
def normalize_additional(data: Dict[str, Any], current: Dict[str, Any] | None = None) -> Dict[str, Any]:
    row = dict(current or {})
    row.update(data)
    row["titulo"] = str(row.get("titulo", "")).strip()
    row["proyecto"] = str(row.get("proyecto", "")).strip()
    row["solicita"] = str(row.get("solicita", "")).strip()
    row["descripcion"] = str(row.get("descripcion", "")).strip()
    start = parse_date(row.get("fecha_inicio"))
    end = parse_date(row.get("fecha_finalizacion"))
    if not row["titulo"] or not row["proyecto"] or not row["solicita"] or not row["descripcion"]:
        raise ValueError("Título, proyecto, solicita y descripción son obligatorios.")
    if not start or not end:
        raise ValueError("Fecha de inicio y fecha de finalización son obligatorias.")
    if end < start:
        raise ValueError("La fecha de finalización no puede ser anterior a la fecha de inicio.")
    hset = holiday_dates(storage.read("holidays"))
    row["fecha_inicio"] = iso(start)
    row["fecha_finalizacion"] = iso(end)
    row["dias_duracion"] = len(business_days(start, end, hset))
    return row

@bp.get("/api/additionals")
def list_additionals():
    rows = sorted(storage.read("additionals"), key=lambda r: (str(r.get("fecha_inicio", "")), str(r.get("titulo", ""))))
    return ok({"rows": rows, "total_days": sum(float(r.get("dias_duracion") or 0) for r in rows)})

@bp.post("/api/additionals")
def create_additional():
    row = normalize_additional(payload())
    row["id"] = uid()
    row["creado_en"] = now_iso()
    row["actualizado_en"] = row["creado_en"]
    storage.upsert("additionals", row)
    return ok(row, "Adicional creado.")

@bp.put("/api/additionals/<row_id>")
def update_additional(row_id: str):
    current = storage.get("additionals", row_id)
    if not current:
        return fail("Adicional no encontrado.", 404)
    row = normalize_additional(payload(), current)
    row["id"] = row_id
    row["actualizado_en"] = now_iso()
    storage.upsert("additionals", row)
    return ok(row, "Adicional actualizado.")

@bp.delete("/api/additionals/<row_id>")
def delete_additional(row_id: str):
    if not storage.delete("additionals", row_id):
        return fail("Adicional no encontrado.", 404)
    return ok(message="Adicional eliminado.")

# ----------------------------- Proyectos -----------------------------
def normalize_stage_periods(project_id: str, raw_periods: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows=[]; labels={0:"Aprobación",1:"Etapa 01",2:"Etapa 02",3:"Etapa 03"}
    for stage in (0,1,2,3):
        stage_rows=sorted([r for r in raw_periods if int(float(r.get("etapa") or 0))==stage],key=lambda r:(str(r.get("inicio","")),str(r.get("fin",""))))
        for order,item in enumerate(stage_rows,1):
            start=parse_date(item.get("inicio")); end=parse_date(item.get("fin"))
            if not start or not end: raise ValueError(f"Todos los lapsos de {labels[stage]} deben tener inicio y final.")
            rows.append({"id":str(item.get("id") or uid()),"project_id":project_id,"etapa":stage,"inicio":iso(start),"fin":iso(end),"orden":order})
    return rows

def apply_period_bounds(row: Dict[str, Any], periods: List[Dict[str, Any]]) -> None:
    for stage in (1,2,3):
        stage_rows=sorted([r for r in periods if int(r["etapa"])==stage],key=lambda r:r["inicio"])
        row[f"etapa{stage}_inicio"]=stage_rows[0]["inicio"] if stage_rows else ""
        row[f"etapa{stage}_fin"]=stage_rows[-1]["fin"] if stage_rows else ""
    approval_rows=sorted([r for r in periods if int(r["etapa"])==0],key=lambda r:r["inicio"])
    row["fecha_aprobacion"]=approval_rows[-1]["fin"] if approval_rows else ""

def normalize_project_input(data: Dict[str, Any], current: Dict[str, Any] | None = None, project_id: str = "") -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    row = dict(current or {})
    row.update({k: v for k, v in data.items() if k not in {"equipment", "stage_periods", "revisions"}})
    row["numero"] = str(row.get("numero", "")).strip().upper()
    row["cliente"] = str(row.get("cliente", "")).strip()
    row["bodega"] = str(row.get("bodega", "")).strip()
    row["tipo_proyecto"] = str(row.get("tipo_proyecto", "T1")).strip().upper()
    row["pmp_id"] = str(row.get("pmp_id", "")).strip()
    pmps = {str(item.get("id")): item for item in storage.read("pmps")}
    if not row["pmp_id"]:
        raise ValueError("Debe seleccionar una PMP para el proyecto.")
    if row["pmp_id"] not in pmps:
        raise ValueError("La PMP seleccionada ya no existe.")
    row["pmp_nombre"] = pmps.get(row["pmp_id"], {}).get("nombre", row.get("pmp_nombre", ""))
    row["tamano_id"] = str(row.get("tamano_id", "")).strip()
    sizes = {str(item.get("id")): item for item in storage.read("project_sizes")}
    if not row["tamano_id"] or row["tamano_id"] not in sizes:
        raise ValueError("Debe seleccionar un tamaño de proyecto.")
    row["tamano_nombre"] = str(sizes[row["tamano_id"]].get("nombre") or "").strip()
    if not row["numero"] or not row["cliente"] or not row.get("designer_id") or not row.get("bodega"):
        raise ValueError("Número de proyecto, cliente, diseñador y BODEGA son obligatorios.")
    if row["tipo_proyecto"] not in PROJECT_TYPES:
        raise ValueError("Seleccione un tipo de proyecto válido: T1, T2, T3 o T4.")
    if current and str(current.get("tipo_proyecto", "T1")).upper() != row["tipo_proyecto"]:
        raise ValueError("El tipo de proyecto no se puede cambiar. Debe borrar el proyecto y crearlo nuevamente.")
    for field in ("fecha_contra_actual", "fecha_recepcion_alcance", "fecha_inicio", "fecha_finalizacion"):
        row[field] = iso(parse_date(row.get(field)))
    if not row.get("fecha_contra_actual"):
        raise ValueError("La fecha CONTRA ACTUAL es obligatoria.")
    periods = normalize_stage_periods(project_id or str(row.get("id", "")), list(data.get("stage_periods") or []))
    apply_period_bounds(row, periods)
    working = dict(row)
    working["stage_periods"] = periods
    validate_project_dates(working)
    return row, periods

def prepare_project_equipment(project_id: str, selected: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], float]:
    catalog = {r["id"]: r for r in storage.read("equipment")}
    rows: List[Dict[str, Any]] = []
    total_days = 0.0
    used: set[str] = set()
    for item in selected:
        equipment_id = str(item.get("equipment_id", ""))
        if equipment_id in used:
            raise ValueError("Un equipo no puede repetirse en el carrito.")
        used.add(equipment_id)
        equipment = catalog.get(equipment_id)
        if not equipment:
            raise ValueError("Uno de los equipos seleccionados ya no existe.")
        kind = str(item.get("tipo", "estandar")).lower()
        field_by_kind = {"estandar":"dias_estandar","medio":"dias_medio","no_estandar":"dias_no_estandar","complejo":"dias_complejo"}
        if kind not in field_by_kind:
            raise ValueError("El tipo de equipo debe ser estándar, medio, no estándar o complejo.")
        days = float(equipment.get(field_by_kind[kind]) or 0)
        quantity = max(1, int(float(item.get("cantidad") or 1)))
        # La cantidad se registra, pero el tiempo del mismo plano se cuenta una sola vez.
        rows.append({
            "id": uid(), "project_id": project_id, "equipment_id": equipment_id,
            "codigo": equipment.get("codigo"), "nombre": equipment.get("nombre"),
            "cantidad": quantity, "tipo": kind, "dias_aplicados": days,
        })
        total_days += days
    return rows, round(total_days, 2)


def normalize_project_revisions(project_id: str, raw_rows: List[Dict[str, Any]], project_row: Dict[str, Any], periods: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    approval_periods=sorted([r for r in periods if int(float(r.get("etapa") or 0))==0],key=lambda r:(str(r.get("inicio","")),str(r.get("fin",""))))
    seen=set(); rows=[]; timestamp=now_iso()
    for raw in raw_rows:
        number=str(raw.get("numero_revision") or "").strip().upper(); day=parse_date(raw.get("fecha"))
        if not number or not day: raise ValueError("Cada revisión debe tener número y fecha.")
        if number in seen: raise ValueError("No puede repetir el número de revisión dentro del proyecto.")
        seen.add(number)
        inside=any(parse_date(p.get("inicio")) <= day <= parse_date(p.get("fin")) for p in approval_periods if parse_date(p.get("inicio")) and parse_date(p.get("fin")))
        if not inside: raise ValueError(f"{number}: la fecha debe estar dentro de un lapso de Aprobación.")
        rows.append({"id":str(raw.get("id") or uid()),"project_id":project_id,"numero_revision":number,"fecha":iso(day),"creado_en":raw.get("creado_en") or timestamp,"actualizado_en":timestamp})
    return sorted(rows,key=lambda r:(r["fecha"],r["numero_revision"]))

@bp.get("/project-images/<path:filename>")
def project_image(filename: str):
    persistent = IMAGE_DIR / filename
    if persistent.exists():
        return send_from_directory(IMAGE_DIR, filename)
    legacy = LEGACY_IMAGE_DIR / filename
    if legacy.exists():
        return send_from_directory(LEGACY_IMAGE_DIR, filename)
    return fail("Imagen no encontrada.", 404)

@bp.get("/api/projects")
def list_projects():
    ctx = build_context()
    return ok([enrich_project(p, ctx) for p in ctx["projects"]])


@bp.get("/api/projects/<project_id>")
def get_project(project_id: str):
    project = storage.get("projects", project_id)
    if not project:
        return fail("Proyecto no encontrado.", 404)
    return ok(enrich_project(project, build_context()))


@bp.get("/api/upcoming-projects")
def list_upcoming_projects():
    return ok(enriched_upcoming_projects(build_context()))


def normalize_upcoming_input(data: Dict[str, Any], current: Dict[str, Any] | None = None) -> Dict[str, Any]:
    row = dict(current or {})
    row.update(data)
    row["numero"] = str(row.get("numero", "")).strip().upper()
    row["cliente"] = str(row.get("cliente", "")).strip()
    row["designer_id"] = str(row.get("designer_id", "")).strip()
    start = parse_date(row.get("fecha_inicio"))
    row["fecha_inicio"] = iso(start)
    row["dias_referencia"] = max(0.0, float(row.get("dias_referencia") or 0))
    if not row["numero"] or not row["cliente"] or not row["designer_id"] or not start:
        raise ValueError("Número, cliente, diseñador y fecha prevista de inicio son obligatorios.")
    return row


@bp.post("/api/upcoming-projects")
def create_upcoming_project():
    data = payload()
    row = normalize_upcoming_input(data)
    if any(str(p.get("numero", "")).strip().upper() == row["numero"] for p in storage.read("upcoming_projects")):
        raise ValueError("Ya existe un proyecto por empezar con ese número.")
    timestamp = now_iso()
    row.update({"id": uid(), "creado_en": timestamp, "actualizado_en": timestamp})
    storage.upsert("upcoming_projects", row)
    return ok(enriched_upcoming_projects(build_context()), "Proyecto por empezar agregado.")


@bp.put("/api/upcoming-projects/<row_id>")
def update_upcoming_project(row_id: str):
    current = storage.get("upcoming_projects", row_id)
    if not current:
        return fail("Proyecto por empezar no encontrado.", 404)
    row = normalize_upcoming_input(payload(), current)
    duplicates = [
        p for p in storage.read("upcoming_projects")
        if str(p.get("id")) != row_id and str(p.get("numero", "")).strip().upper() == row["numero"]
    ]
    if duplicates:
        raise ValueError("Ya existe otro proyecto por empezar con ese número.")
    row["id"] = row_id
    row["actualizado_en"] = now_iso()
    storage.upsert("upcoming_projects", row)
    return ok(enriched_upcoming_projects(build_context()), "Proyecto por empezar actualizado.")


@bp.delete("/api/upcoming-projects/<row_id>")
def delete_upcoming_project(row_id: str):
    if not storage.delete("upcoming_projects", row_id):
        return fail("Proyecto por empezar no encontrado.", 404)
    return ok(message="Proyecto por empezar eliminado.")


# Compatibilidad con el botón de versiones anteriores.
@bp.post("/api/projects/upcoming")
def create_upcoming_project_legacy():
    return create_upcoming_project()


@bp.post("/api/projects")
def create_project():
    data = payload()
    project_type = str(data.get("tipo_proyecto", "T1")).strip().upper()
    if abs(activity_total(project_type) - 100.0) > 0.001:
        raise ValueError(f"Las actividades activas de {project_type} deben sumar exactamente 100 % antes de crear el proyecto.")
    if any(str(p.get("numero", "")).upper() == str(data.get("numero", "")).strip().upper() for p in storage.read("projects")):
        raise ValueError("Ya existe un proyecto con ese número.")
    project_id = uid()
    row, period_rows = normalize_project_input(data, project_id=project_id)
    equipment_rows, reference_days = prepare_project_equipment(project_id, list(data.get("equipment") or []))
    hset = holiday_dates(storage.read("holidays"))
    start_date = parse_date(row["fecha_inicio"])
    tentative_end = add_business_days(start_date, max(1, int(round(reference_days))), hset) if reference_days and start_date else start_date
    timestamp = now_iso()
    row.update({
        "id": project_id, "dias_referencia": reference_days, "estado": "Activo",
        "fecha_finalizacion": "", "retraso_etapa1": 0, "retraso_etapa2": 0, "retraso_etapa3": 0,
        "notas_historico": "", "estatus_historico": "", "imagen_path": row.get("imagen_path", ""), "creado_en": timestamp, "actualizado_en": timestamp,
        "fecha_tentativa_referencia": iso(tentative_end),
    })
    working = dict(row)
    working["stage_periods"] = period_rows
    row["dias_aprobacion"] = approval_days(working, hset)
    revision_rows = normalize_project_revisions(project_id, list(data.get("revisions") or []), row, period_rows)
    storage.upsert("projects", row)
    storage.replace_where("stage_periods", lambda r: r.get("project_id") == project_id, period_rows)
    storage.replace_where("project_equipment", lambda r: r.get("project_id") == project_id, equipment_rows)
    storage.replace_where("project_revisions", lambda r: str(r.get("project_id")) == project_id, revision_rows)

    progress_rows = []
    for activity in storage.read("activities"):
        if not bool(activity.get("activa", True)) or project_type not in activity_types(activity.get("tipos_proyecto")):
            continue
        progress_rows.append({
            "id": uid(), "project_id": project_id, "activity_id": activity["id"],
            "actividad": activity["nombre"], "etapa": activity["etapa"],
            "porcentaje": activity["porcentaje"], "cumplida": False, "fecha_cumplimiento": "",
        })
    storage.replace_where("project_progress", lambda r: r.get("project_id") == project_id, progress_rows)
    return ok(enrich_project(storage.get("projects", project_id), build_context()), "Proyecto creado.")


@bp.put("/api/projects/<project_id>")
def update_project(project_id: str):
    current = storage.get("projects", project_id)
    if not current:
        return fail("Proyecto no encontrado.", 404)
    data = payload()
    row, period_rows = normalize_project_input(data, current, project_id=project_id)
    duplicates = [p for p in storage.read("projects") if p["id"] != project_id and str(p.get("numero", "")).upper() == row["numero"]]
    if duplicates:
        raise ValueError("Ya existe otro proyecto con ese número.")
    equipment_rows = None
    if "equipment" in data:
        equipment_rows, reference_days = prepare_project_equipment(project_id, list(data.get("equipment") or []))
        row["dias_referencia"] = reference_days
    revision_rows = normalize_project_revisions(project_id, list(data.get("revisions") or []), row, period_rows) if "revisions" in data else None
    hset = holiday_dates(storage.read("holidays"))
    working = dict(row)
    working["stage_periods"] = period_rows
    row["dias_aprobacion"] = approval_days(working, hset)
    row["actualizado_en"] = now_iso()
    storage.upsert("projects", row)
    storage.replace_where("stage_periods", lambda r: str(r.get("project_id")) == project_id, period_rows)
    if equipment_rows is not None:
        storage.replace_where("project_equipment", lambda r: str(r.get("project_id")) == project_id, equipment_rows)
    if revision_rows is not None:
        storage.replace_where("project_revisions", lambda r: str(r.get("project_id")) == project_id, revision_rows)
    return ok(enrich_project(storage.get("projects", project_id), build_context()), "Proyecto actualizado.")


@bp.delete("/api/projects/<project_id>")
def delete_project(project_id: str):
    project = storage.get("projects", project_id)
    if not project:
        return fail("Proyecto no encontrado.", 404)
    storage.delete("projects", project_id)
    storage.replace_where("project_equipment", lambda r: str(r.get("project_id")) == project_id, [])
    storage.replace_where("project_progress", lambda r: str(r.get("project_id")) == project_id, [])
    storage.replace_where("stage_periods", lambda r: str(r.get("project_id")) == project_id, [])
    storage.replace_where("project_revisions", lambda r: str(r.get("project_id")) == project_id, [])
    image_name=str(project.get("imagen_path") or "").strip()
    if image_name:
        (IMAGE_DIR / image_name).unlink(missing_ok=True)
        if LEGACY_IMAGE_DIR.exists() and LEGACY_IMAGE_DIR.resolve() != IMAGE_DIR.resolve():
            (LEGACY_IMAGE_DIR / image_name).unlink(missing_ok=True)
    return ok(message=f"Proyecto {project.get('numero', '')} eliminado.")


@bp.post("/api/projects/<project_id>/image")
def upload_project_image(project_id: str):
    project=storage.get("projects",project_id)
    if not project: return fail("Proyecto no encontrado.",404)
    file=request.files.get("image")
    if not file or not file.filename: raise ValueError("Seleccione una imagen.")
    original=secure_filename(file.filename); project_number=str(project.get("numero") or "").strip()
    normalized_number="".join(ch for ch in project_number.lower() if ch.isalnum())
    normalized_file="".join(ch for ch in original.lower() if ch.isalnum())
    if not normalized_number or normalized_number not in normalized_file:
        raise ValueError(f"El nombre del archivo debe contener el número del proyecto {project_number}.")
    ext=Path(original).suffix.lower()
    if ext not in {".png",".jpg",".jpeg",".webp"}: raise ValueError("La imagen debe ser PNG, JPG, JPEG o WEBP.")
    old=str(project.get("imagen_path") or "").strip()
    filename=secure_filename(f"{project_number}_{original}")
    file.save(IMAGE_DIR / filename)
    if old and old != filename: (IMAGE_DIR / old).unlink(missing_ok=True)
    project["imagen_path"]=filename; project["actualizado_en"]=now_iso(); storage.upsert("projects",project)
    return ok(enrich_project(project,build_context()),"Imagen del proyecto guardada.")

@bp.patch("/api/projects/<project_id>/periods/<period_id>")
def update_project_period(project_id: str, period_id: str):
    project=storage.get("projects",project_id)
    if not project: return fail("Proyecto no encontrado.",404)
    if str(project.get("estado"))=="Finalizado": raise ValueError("Devuelva el proyecto al tablero antes de mover sus barras.")
    periods=storage.read("stage_periods"); target=next((r for r in periods if str(r.get("id"))==period_id and str(r.get("project_id"))==project_id),None)
    if not target: return fail("Lapso no encontrado.",404)
    data=payload(); start=parse_date(data.get("inicio")); end=parse_date(data.get("fin"))
    if not start or not end or end < start: raise ValueError("Revise las fechas del lapso.")
    hset=holiday_dates(storage.read("holidays"))
    if start.weekday()>=5 or start in hset or end.weekday()>=5 or end in hset: raise ValueError("El inicio y el final del lapso deben ser días hábiles.")
    target["inicio"]=iso(start); target["fin"]=iso(end)
    project_period_rows=[r for r in periods if str(r.get("project_id"))==project_id]
    apply_period_bounds(project,project_period_rows); project["fecha_inicio"]=project.get("etapa1_inicio") or project.get("fecha_inicio")
    validation=dict(project); validation["stage_periods"]=project_period_rows
    validate_project_dates(validation)
    # Las revisiones deben continuar dentro del periodo de aprobación.
    normalize_project_revisions(project_id,[r for r in storage.read("project_revisions") if str(r.get("project_id"))==project_id],project,project_period_rows)
    project["dias_aprobacion"]=approval_days(validation,hset)
    project["actualizado_en"]=now_iso(); storage.write("stage_periods",periods); storage.upsert("projects",project)
    return ok(enrich_project(project,build_context()),"Lapso actualizado desde el calendario.")

@bp.post("/api/projects/<project_id>/restore")
def restore_project(project_id: str):
    project=storage.get("projects",project_id)
    if not project: return fail("Proyecto no encontrado.",404)
    if str(project.get("estado"))!="Finalizado": raise ValueError("El proyecto ya está activo.")
    project["estado"]="Activo"; project["fecha_finalizacion"]=""; project["actualizado_en"]=now_iso(); storage.upsert("projects",project)
    return ok(enrich_project(project,build_context()),"Proyecto devuelto al tablero para edición.")

@bp.patch("/api/projects/<project_id>/activities/<progress_id>")
def toggle_project_activity(project_id: str, progress_id: str):
    project = storage.get("projects", project_id)
    if not project:
        return fail("Proyecto no encontrado.", 404)
    row = storage.get("project_progress", progress_id)
    if not row or row.get("project_id") != project_id:
        return fail("Actividad del proyecto no encontrada.", 404)
    data = payload()
    completed = bool(data.get("cumplida", row.get("cumplida", False)))
    row["cumplida"] = completed
    if "fecha_cumplimiento" in data:
        row["fecha_cumplimiento"] = iso(parse_date(data.get("fecha_cumplimiento")))
    elif completed and not row.get("fecha_cumplimiento"):
        row["fecha_cumplimiento"] = date.today().isoformat()
    storage.upsert("project_progress", row)
    project["actualizado_en"] = now_iso()
    storage.upsert("projects", project)
    return ok(enrich_project(project, build_context()), "Avance actualizado.")


@bp.post("/api/projects/<project_id>/approve")
def approve_project(project_id: str):
    raise ValueError("Rev20: la aprobación se programa mediante lapsos de Aprobación al editar el proyecto.")


@bp.post("/api/projects/<project_id>/finish")
def finish_project(project_id: str):
    project = storage.get("projects", project_id)
    if not project:
        return fail("Proyecto no encontrado.", 404)
    enriched = enrich_project(project, build_context())
    if enriched["metrics"]["avance"] < 99.999:
        raise ValueError("Todas las actividades deben estar cumplidas antes de finalizar el proyecto.")
    if not enriched.get("periods_by_stage", {}).get("3"):
        raise ValueError("La Etapa 03 debe tener al menos un lapso de tiempo.")
    data = payload()
    finish_date = parse_date(data.get("fecha_finalizacion")) or date.today()
    # Rev18: la fecha de cierre representa la terminación REAL del proyecto.
    # Puede ser anterior al fin planificado de la Etapa 03 si el diseñador terminó antes.
    # La programación original se conserva en el histórico para comparar lo planeado.
    project["estado"] = "Finalizado"
    project["fecha_finalizacion"] = iso(finish_date)
    # v18.1: los retrasos dejan de formar parte del histórico.
    project["retraso_etapa1"] = 0
    project["retraso_etapa2"] = 0
    project["retraso_etapa3"] = 0
    project["notas_historico"] = str(data.get("notas_historico") or "").strip()
    project["estatus_historico"] = str(project.get("estatus_historico") or "PRODUCCION").strip().upper()
    project["actualizado_en"] = now_iso()
    storage.upsert("projects", project)
    return ok(enrich_project(project, build_context()), "Proyecto enviado al histórico.")


@bp.patch("/api/projects/<project_id>/history")
def update_history_record(project_id: str):
    project = storage.get("projects", project_id)
    if not project:
        return fail("Proyecto no encontrado.", 404)
    if str(project.get("estado", "")) != "Finalizado":
        raise ValueError("Este registro todavía no pertenece al histórico.")
    data = payload()
    if "fecha_recepcion_alcance" in data:
        reception = parse_date(data.get("fecha_recepcion_alcance"))
        start = parse_date(project.get("fecha_inicio"))
        if not reception:
            raise ValueError("La fecha de RECEPCIÓN DE ALCANCE es obligatoria.")
        if start and reception >= start:
            raise ValueError("La RECEPCIÓN DE ALCANCE debe ser anterior al inicio de la Etapa 01.")
        project["fecha_recepcion_alcance"] = iso(reception)
    if "bodega" in data:
        warehouse = str(data.get("bodega") or "").strip()
        if not warehouse:
            raise ValueError("La BODEGA es obligatoria.")
        project["bodega"] = warehouse
    if "pmp_id" in data:
        pmp_id = str(data.get("pmp_id") or "").strip()
        if not pmp_id:
            raise ValueError("Debe seleccionar una PMP.")
        pmp = storage.get("pmps", pmp_id)
        if not pmp:
            raise ValueError("La PMP seleccionada ya no existe.")
        project["pmp_id"] = pmp_id
        project["pmp_nombre"] = str(pmp.get("nombre") or "").strip()
    for field in ("retraso_etapa1", "retraso_etapa2", "retraso_etapa3"):
        if field in data:
            project[field] = max(0, int(float(data.get(field) or 0)))
    if "notas_historico" in data:
        project["notas_historico"] = str(data.get("notas_historico") or "").strip()
    if "estatus_historico" in data:
        status = str(data.get("estatus_historico") or "").strip().upper()
        if status not in HISTORY_STATUSES:
            raise ValueError("Seleccione un ESTATUS histórico válido.")
        project["estatus_historico"] = status
    project["actualizado_en"] = now_iso()
    storage.upsert("projects", project)
    return ok(enrich_project(project, build_context()), "Registro histórico actualizado.")


# ----------------------------- Excel / respaldo -----------------------------
@bp.post("/api/sync-excel")
def sync_excel():
    # Se crea una copia antes de aceptar cambios manuales.
    snapshot = storage.create_snapshot()
    counts = storage.reload_from_excel(validate=True)
    refresh_approval_day_values()
    refresh_additional_durations()
    validate_activity_totals(require_complete=True)
    propagation = refresh_active_project_activity_percentages()
    return ok({
        "counts": counts,
        "snapshot": str(snapshot),
        **propagation,
    }, "Información actualizada desde Excel y proyectos activos recalculados.")


@bp.post("/api/backup")
def manual_backup():
    snapshot = storage.create_snapshot()
    return ok({"snapshot": str(snapshot)}, "Copia de seguridad creada.")


@bp.get("/api/health")
def health():
    return ok({"app": "PROYECTOS DISEÑO MECÁNICO", "bases": str(BASES_DIR), "time": now_iso()})
