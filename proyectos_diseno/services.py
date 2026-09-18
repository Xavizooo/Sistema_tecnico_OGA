from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Sequence, Tuple


STAGE_NAMES = {
    0: "Aprobación",
    1: "Plano general",
    2: "Fabricación",
    3: "Adicionales",
}

STAGE_COLORS = {
    1: "#6dcff4",  # Etapa 01 - celeste
    2: "#ffb91b",  # Etapa 02 - amarillo/ámbar
    3: "#1dd5a3",  # Etapa 03 - turquesa
    0: "#f06292",  # Aprobación - rosado
}

PROJECT_TYPES = {
    "T1": "Proyecto",
    "T2": "Solo Ingeniería",
    "T3": "OT",
    "T4": "Garantía",
}


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    if not text:
        return None
    return date.fromisoformat(text)


def iso(value: date | datetime | None) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def parse_time_minutes(value: str | None) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    parts = text.split(":")
    if len(parts) < 2:
        raise ValueError(f"Hora inválida: {text}")
    return int(parts[0]) * 60 + int(parts[1])


def designer_daily_hours(designer: Dict[str, Any]) -> float:
    start = parse_time_minutes(designer.get("hora_entrada"))
    end = parse_time_minutes(designer.get("hora_salida"))
    lunch_start = parse_time_minutes(designer.get("almuerzo_inicio"))
    lunch_end = parse_time_minutes(designer.get("almuerzo_fin"))
    total = end - start
    if lunch_start and lunch_end:
        total -= max(0, lunch_end - lunch_start)
    return round(max(total, 0) / 60, 2)


def holiday_dates(rows: Iterable[Dict[str, Any]]) -> set[date]:
    result: set[date] = set()
    for row in rows:
        if not bool(row.get("activo", True)):
            continue
        parsed = parse_date(row.get("fecha"))
        if parsed:
            result.add(parsed)
    return result


def is_business_day(day: date, holidays: set[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def business_days(start: date | None, end: date | None, holidays: set[date]) -> List[date]:
    if not start or not end or end < start:
        return []
    days: List[date] = []
    current = start
    while current <= end:
        if is_business_day(current, holidays):
            days.append(current)
        current += timedelta(days=1)
    return days


def add_business_days(start: date, count: int, holidays: set[date]) -> date:
    if count <= 0:
        return start
    current = start
    remaining = count - 1 if is_business_day(start, holidays) else count
    while remaining > 0:
        current += timedelta(days=1)
        if is_business_day(current, holidays):
            remaining -= 1
    return current


def business_day_distance(start: date, end: date, holidays: set[date]) -> int:
    """Días laborales entre fechas. Positivo si end es posterior; negativo si es anterior."""
    if start == end:
        return 0
    sign = 1 if end > start else -1
    low, high = (start, end) if sign > 0 else (end, start)
    count = 0
    current = low + timedelta(days=1)
    while current <= high:
        if is_business_day(current, holidays):
            count += 1
        current += timedelta(days=1)
    return count * sign


def month_business_days(year: int, month: int, holidays: set[date]) -> int:
    first = date(year, month, 1)
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return len(business_days(first, next_month - timedelta(days=1), holidays))


def normalize_periods(periods: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for raw in periods or []:
        stage = int(float(raw.get("etapa") or 0))
        start = parse_date(raw.get("inicio"))
        end = parse_date(raw.get("fin"))
        if stage not in {0, 1, 2, 3} or not start or not end:
            continue
        result.append({
            "id": str(raw.get("id", "")), "project_id": str(raw.get("project_id", "")),
            "etapa": stage, "inicio": iso(start), "fin": iso(end),
            "orden": int(float(raw.get("orden") or 0)),
        })
    return sorted(result, key=lambda r: (int(r["etapa"]), str(r["inicio"]), str(r["fin"]), int(r.get("orden") or 0)))

def project_periods(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    periods = normalize_periods(project.get("stage_periods") or [])
    if periods:
        return periods
    legacy: List[Dict[str, Any]] = []
    for stage in (1, 2, 3):
        start = parse_date(project.get(f"etapa{stage}_inicio"))
        end = parse_date(project.get(f"etapa{stage}_fin"))
        if start and end:
            legacy.append({"id": "", "project_id": str(project.get("id", "")), "etapa": stage, "inicio": iso(start), "fin": iso(end), "orden": 1})
    return legacy


def periods_by_stage(project: Dict[str, Any]) -> Dict[int, List[Dict[str, Any]]]:
    grouped = {0: [], 1: [], 2: [], 3: []}
    for period in project_periods(project):
        stage = int(period["etapa"])
        if stage in grouped:
            grouped[stage].append(period)
    for stage in grouped:
        grouped[stage] = sorted(grouped[stage], key=lambda r: (str(r["inicio"]), str(r["fin"])))
    return grouped

def stage_bounds(project: Dict[str, Any], stage: int) -> tuple[date | None, date | None]:
    periods = periods_by_stage(project).get(stage, [])
    if not periods:
        return None, None
    starts = [parse_date(p.get("inicio")) for p in periods]
    ends = [parse_date(p.get("fin")) for p in periods]
    valid_starts = [d for d in starts if d]
    valid_ends = [d for d in ends if d]
    return (min(valid_starts) if valid_starts else None, max(valid_ends) if valid_ends else None)


def planned_hours_and_cost(
    project: Dict[str, Any], designer: Dict[str, Any] | None, holidays: set[date]
) -> Tuple[float, float, Dict[str, Any]]:
    if not designer:
        return 0.0, 0.0, {"daily_hours": 0, "workdays": 0, "monthly": {}}
    daily_hours = designer_daily_hours(designer)
    monthly_cost = float(designer.get("costo_mensual_empresa") or 0)
    all_days: List[date] = []
    for period in project_periods(project):
        # Aprobación (etapa 0) no genera horas ni costo.
        if int(period.get("etapa") or 0) not in {1, 2, 3}:
            continue
        all_days.extend(business_days(parse_date(period.get("inicio")), parse_date(period.get("fin")), holidays))
    unique_days = sorted(set(all_days))
    total_hours = round(len(unique_days) * daily_hours, 2)
    cost = 0.0
    monthly_breakdown: Dict[str, Dict[str, float]] = defaultdict(lambda: {"dias": 0, "horas": 0, "costo": 0})
    for day in unique_days:
        available_days = month_business_days(day.year, day.month, holidays)
        available_hours = available_days * daily_hours
        hourly_cost = monthly_cost / available_hours if available_hours else 0
        day_cost = hourly_cost * daily_hours
        key = f"{day.year:04d}-{day.month:02d}"
        monthly_breakdown[key]["dias"] += 1
        monthly_breakdown[key]["horas"] += daily_hours
        monthly_breakdown[key]["costo"] += day_cost
        cost += day_cost
    rounded = {key: {"dias": int(v["dias"]), "horas": round(v["horas"], 2), "costo": round(v["costo"], 2)} for key, v in monthly_breakdown.items()}
    return total_hours, round(cost, 2), {"daily_hours": daily_hours, "workdays": len(unique_days), "monthly": rounded}

def validate_project_dates(project: Dict[str, Any]) -> None:
    start = parse_date(project.get("fecha_inicio"))
    reception = parse_date(project.get("fecha_recepcion_alcance"))
    grouped = periods_by_stage(project)
    if not reception:
        raise ValueError("La fecha de RECEPCIÓN DE ALCANCE es obligatoria.")
    if not start:
        raise ValueError("La fecha de inicio del proyecto es obligatoria.")
    if reception >= start:
        raise ValueError("La RECEPCIÓN DE ALCANCE debe ser anterior al inicio de la Etapa 01.")
    if not grouped[1]:
        raise ValueError("La Etapa 01 debe tener al menos un lapso de tiempo.")
    labels = {0: "Aprobación", 1: "Etapa 01", 2: "Etapa 02", 3: "Etapa 03"}
    for stage in (0, 1, 2, 3):
        previous_end = None
        for index, period in enumerate(grouped[stage], 1):
            pstart = parse_date(period.get("inicio")); pend = parse_date(period.get("fin"))
            if not pstart or not pend:
                raise ValueError(f"El lapso {index} de {labels[stage]} debe tener inicio y final.")
            if pend < pstart:
                raise ValueError(f"El lapso {index} de {labels[stage]} termina antes de comenzar.")
            if previous_end and pstart <= previous_end:
                raise ValueError(f"Los lapsos de {labels[stage]} no pueden superponerse.")
            previous_end = pend
    first_s1 = parse_date(grouped[1][0]["inicio"])
    if first_s1 != start:
        raise ValueError("El primer lapso de la Etapa 01 debe comenzar en la fecha de inicio del proyecto.")
    # Etapa 01 y Aprobación pueden alternarse, pero no superponerse.
    combined=[]
    for stage in (0,1):
        for p in grouped[stage]:
            combined.append((parse_date(p.get("inicio")), parse_date(p.get("fin")), stage))
    combined.sort(key=lambda x:(x[0] or date.min,x[1] or date.min))
    for prev,cur in zip(combined,combined[1:]):
        if cur[0] and prev[1] and cur[0] <= prev[1]:
            raise ValueError("Los lapsos de Etapa 01 y Aprobación no pueden superponerse. Cuando una fase termina puede retomar la otra.")
    if grouped[0]:
        first_approval=parse_date(grouped[0][0]["inicio"]); first_s1_end=parse_date(grouped[1][0]["fin"])
        if first_approval and first_s1_end and first_approval <= first_s1_end:
            raise ValueError("El primer lapso de Aprobación debe comenzar después del primer lapso de la Etapa 01.")
        last_approval=parse_date(grouped[0][-1]["fin"]); last_s1=parse_date(grouped[1][-1]["fin"])
        if last_approval and last_s1 and last_approval <= last_s1:
            raise ValueError("El último lapso de Aprobación debe finalizar después del último lapso de la Etapa 01.")
    if grouped[2]:
        if not grouped[0]:
            raise ValueError("Debe programar al menos un lapso de Aprobación antes de la Etapa 02.")
        first_s2=parse_date(grouped[2][0]["inicio"]); last_approval=parse_date(grouped[0][-1]["fin"]); last_s1=parse_date(grouped[1][-1]["fin"])
        latest=max(d for d in (last_approval,last_s1) if d)
        if first_s2 and first_s2 <= latest:
            raise ValueError("La Etapa 02 debe comenzar después de finalizar el último lapso de Aprobación.")
    if grouped[3]:
        if not grouped[2]:
            raise ValueError("Debe programar primero la Etapa 02.")
        last_s2=parse_date(grouped[2][-1]["fin"]); first_s3=parse_date(grouped[3][0]["inicio"])
        if last_s2 and first_s3 and first_s3 <= last_s2:
            raise ValueError("La Etapa 03 debe comenzar después de finalizar el último lapso de la Etapa 02.")

def progress_metrics(project_progress: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    total = round(sum(float(r.get("porcentaje") or 0) for r in project_progress), 2)
    completed = round(
        sum(float(r.get("porcentaje") or 0) for r in project_progress if bool(r.get("cumplida"))), 2
    )
    stages: Dict[int, Dict[str, float]] = {}
    for stage in (1, 2, 3):
        rows = [r for r in project_progress if int(float(r.get("etapa") or 0)) == stage]
        stage_total = sum(float(r.get("porcentaje") or 0) for r in rows)
        stage_completed = sum(float(r.get("porcentaje") or 0) for r in rows if bool(r.get("cumplida")))
        stages[stage] = {
            "peso": round(stage_total, 2),
            "cumplido": round(stage_completed, 2),
            "avance": round((stage_completed / stage_total * 100) if stage_total else 0, 2),
            "completa": bool(rows) and all(bool(r.get("cumplida")) for r in rows),
            "actividades": len(rows),
        }
    return {
        "total_catalogo": total,
        "avance": round(completed, 2),
        "completadas": sum(1 for r in project_progress if bool(r.get("cumplida"))),
        "actividades": len(project_progress),
        "stages": stages,
    }


def current_phase(project: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Any]:
    if str(project.get("estado", "Activo")) == "Finalizado":
        return {"code": "finished", "label": "Finalizado", "stage": None}
    stages = metrics["stages"]; grouped = periods_by_stage(project)
    if not stages[1]["completa"]:
        return {"code": "stage1", "label": "Etapa 01 · Plano general", "stage": 1}
    if not grouped[0]:
        return {"code": "approval", "label": "En aprobación", "stage": 0}
    if not stages[2]["completa"]:
        return {"code": "stage2", "label": "Etapa 02 · Fabricación", "stage": 2}
    if not stages[3]["completa"]:
        return {"code": "stage3", "label": "Etapa 03 · Adicionales", "stage": 3}
    return {"code": "ready", "label": "Listo para finalizar", "stage": 3}

def approval_days(project: Dict[str, Any], holidays: set[date], today: date | None = None) -> int:
    days: set[date] = set()
    for period in periods_by_stage(project).get(0, []):
        days.update(business_days(parse_date(period.get("inicio")), parse_date(period.get("fin")), holidays))
    return len(days)

def project_elapsed_business_days(project: Dict[str, Any], holidays: set[date], end: date | None = None) -> int:
    """Días hábiles desde RECEPCIÓN DE ALCANCE hasta cierre/fecha indicada, inclusive."""
    start = parse_date(project.get("fecha_recepcion_alcance"))
    finish = end or parse_date(project.get("fecha_finalizacion"))
    if not start or not finish or finish < start:
        return 0
    return len(business_days(start, finish, holidays))

def project_phase_days(project: Dict[str, Any], holidays: set[date], today: date | None = None) -> Dict[str, int]:
    result: Dict[str, int] = {}; grouped=periods_by_stage(project)
    for stage in (1,2,3):
        days:set[date]=set()
        for period in grouped[stage]:
            days.update(business_days(parse_date(period["inicio"]), parse_date(period["fin"]), holidays))
        result[f"stage{stage}"]=len(days)
    approval:set[date]=set()
    for period in grouped[0]:
        approval.update(business_days(parse_date(period["inicio"]), parse_date(period["fin"]), holidays))
    result["approval"]=len(approval)
    result["stage_total"]=result["stage1"]+result["stage2"]+result["stage3"]
    result["total"]=result["stage_total"]+result["approval"]
    result["elapsed_from_reception"]=project_elapsed_business_days(project,holidays)
    return result

def phase_deadline(project: Dict[str, Any], phase: Dict[str, Any]) -> date | None:
    code=phase["code"]
    if code=="stage1": return stage_bounds(project,1)[1]
    if code=="approval": return stage_bounds(project,0)[1]
    if code=="stage2": return stage_bounds(project,2)[1]
    if code in {"stage3","ready"}: return stage_bounds(project,3)[1]
    return None

def alert_for_project(
    project: Dict[str, Any], phase: Dict[str, Any], holidays: set[date], today: date | None = None
) -> Dict[str, Any] | None:
    today = today or date.today()
    deadline = phase_deadline(project, phase)
    if not deadline or phase["code"] in {"finished", "ready"}:
        return None
    distance = business_day_distance(today, deadline, holidays)
    if distance > 2:
        return None
    if distance >= 0:
        return {
            "type": "warning",
            "days": distance,
            "message": f"Faltan {distance} día(s) laborable(s)",
            "deadline": deadline.isoformat(),
        }
    late = abs(distance)
    return {
        "type": "danger",
        "days": late,
        "message": f"{late} día(s) laborable(s) de retraso",
        "deadline": deadline.isoformat(),
    }


def project_segments(project: Dict[str, Any], filtered: bool, today: date | None = None) -> List[Dict[str, Any]]:
    today=today or date.today(); segments=[]
    reception=parse_date(project.get("fecha_recepcion_alcance"))
    if reception: segments.append({"kind":"reception","label":"Recepción de alcance","start":iso(reception),"end":iso(reception),"color":"#111111","point":True})
    contra=parse_date(project.get("fecha_contra_actual"))
    if contra: segments.append({"kind":"contra","label":"Contra actual","start":iso(contra),"end":iso(contra),"color":"#ef4444","point":True})
    for revision in project.get("revision_rows") or []:
        d=parse_date(revision.get("fecha"))
        if d: segments.append({"kind":"revision","label":str(revision.get("numero_revision") or "Revisión"),"start":iso(d),"end":iso(d),"color":"#22c55e","point":True,"revision_id":str(revision.get("id") or "")})
    periods=project_periods(project)
    if not filtered:
        for period in periods:
            segments.append({"kind":"project","label":str(project.get("numero","")),"stage":int(period.get("etapa") or 0),"period_id":str(period.get("id") or ""),"start":str(period.get("inicio","")),"end":str(period.get("fin",""))})
        return segments
    for period in periods:
        stage=int(period["etapa"]); label="Aprobación" if stage==0 else f"Etapa 0{stage}"; kind="approval" if stage==0 else f"stage{stage}"
        segments.append({"kind":kind,"stage":stage,"label":label,"period_id":str(period.get("id") or ""),"start":str(period["inicio"]),"end":str(period["fin"]),"color":STAGE_COLORS[stage]})
    return segments

def colombia_holidays(year: int) -> List[Tuple[date, str]]:
    try:
        import holidays  # type: ignore

        co = holidays.country_holidays("CO", years=[year], language="es")
        return sorted((day, str(name)) for day, name in co.items())
    except Exception:
        fixed = [
            (1, 1, "Año Nuevo"), (5, 1, "Día del Trabajo"), (7, 20, "Independencia"),
            (8, 7, "Batalla de Boyacá"), (12, 8, "Inmaculada Concepción"),
            (12, 25, "Navidad"),
        ]
        return [(date(year, m, d), name) for m, d, name in fixed]
