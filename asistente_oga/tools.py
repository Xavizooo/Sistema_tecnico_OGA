from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .readonly import (
    FIELD_MAP,
    attachment_links,
    count_opportunities,
    equipment_summary,
    find_exact,
    get_opportunity,
    normalize,
    search_opportunities,
    similar_opportunities,
    stats,
)

READ_ONLY_MODE = "READ_ONLY"

_FREE_STOP = {
    "de", "del", "la", "las", "el", "los", "y", "a", "en", "con", "por", "para",
    "un", "una", "unos", "unas", "que", "cual", "cuales", "hay", "me", "muestre",
    "muestrame", "mostrar", "busca", "buscar", "quiero", "dame", "trae", "traeme",
    "proyecto", "proyectos", "oportunidad", "oportunidades", "oga",
}

_FILTER_FIELDS = (
    "cliente", "material", "estado", "responsable", "proyecto", "radicado", "equipo",
    "industria", "proceso", "subsistema", "entrada", "salida", "transporte", "pais",
    "ciudad", "tipo", "planta", "voltaje", "atex", "nec", "ubicacion", "flujo",
)

_REASON_LABELS = {
    "material": "materiales",
    "transporte": "tipo de transporte",
    "proceso": "proceso",
    "equipo": "equipos",
    "entrada": "puntos de entrada",
    "salida": "puntos de salida",
    "industria": "industria",
    "tipo": "tipo de oportunidad",
    "flujo": "flujo",
}


@dataclass
class ToolResult:
    output: dict[str, Any]
    cards: list[dict[str, Any]]
    sources: list[dict[str, Any]]


def _opportunity_card(row: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    oid = int(row.get("id") or 0)
    card = {
        "type": "opportunity",
        "id": oid,
        "internal_id": oid,
        "title": str(row.get("nombre") or row.get("proyecto") or "Oportunidad"),
        "subtitle": f"Radicado {row.get('radicado') or '-'} | Proyecto {row.get('proyecto') or '-'}",
        "client": str(row.get("cliente") or ""),
        "status": str(row.get("estado") or ""),
        "meta": str(row.get("responsible_names") or ""),
        "url": f"/oportunidades-proyecto/?od={oid}",
    }
    if extra:
        card.update(extra)
    return card


def _attachment_card(item: dict[str, Any]) -> dict[str, Any]:
    is_pdf = item.get("tipo") == "OFERTA"
    return {
        "type": "attachment",
        "kind": "PDF" if is_pdf else "IMAGEN",
        "title": str(item.get("titulo") or item.get("nombre_original") or ("Oferta" if is_pdf else "Imagen")),
        "subtitle": f"{item.get('subsystem_name') or 'Subsistema'} | {item.get('nombre_original') or ''}",
        "view_url": item.get("view_url"),
        "download_url": item.get("download_url"),
        "size": int(item.get("tamano") or 0),
    }


def _subsystem_cards(detail: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for subsystem in detail.get("subsystems") or []:
        criteria: list[str] = []
        for key, label in (
            ("material_transportado", "Material"), ("flujo_kg_h", "Flujo kg/h"),
            ("tipo_transporte", "Transporte"), ("voltaje_potencia", "Voltaje"),
            ("distancia_horizontal_m", "Dist. horizontal"), ("distancia_vertical_m", "Dist. vertical"),
            ("atex", "ATEX"), ("nec", "NEC"), ("ubicacion", "Ubicacion"),
        ):
            value = str(subsystem.get(key) or "").strip()
            if value:
                criteria.append(f"{label}: {value}")
        cards.append({
            "type": "subsystem",
            "title": str(subsystem.get("nombre") or "Subsistema"),
            "subtitle": str(subsystem.get("descripcion_proceso") or subsystem.get("nombre_proceso") or ""),
            "criteria": criteria,
            "equipment_count": len(subsystem.get("equipment") or []),
            "offer_count": len(subsystem.get("offers") or []),
            "image_count": len(subsystem.get("images") or []),
        })
    return cards


def _free_tokens(text: str) -> list[tuple[str | None, str]]:
    words = re.findall(r"[a-z0-9][a-z0-9_./-]*", normalize(text))
    tokens: list[tuple[str | None, str]] = []
    seen: set[str] = set()
    for word in words:
        if len(word) < 2 or word in _FREE_STOP or word in seen:
            continue
        seen.add(word)
        tokens.append((None, word))
    return tokens[:10]


def _tokens_from_args(args: dict[str, Any]) -> list[tuple[str | None, str]]:
    tokens: list[tuple[str | None, str]] = []
    text = str(args.get("texto") or "").strip()
    if text:
        tokens.extend(_free_tokens(text))
    for field in _FILTER_FIELDS:
        value = args.get(field)
        if value is None:
            continue
        value = str(value).strip()
        if value:
            tokens.append((field, value))
    return tokens[:20]


def _limit(args: dict[str, Any], default: int = 12, maximum: int = 30) -> int:
    try:
        return max(1, min(int(args.get("limite") or default), maximum))
    except (TypeError, ValueError):
        return default


def _slim_detail(detail: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: detail.get(key) for key in (
            "id", "radicado", "proyecto", "nombre", "cliente", "descripcion", "planta", "ciudad",
            "pais", "industria", "tipo_oportunidad", "estado", "fecha_inicio", "valor_estimado", "observaciones"
        )
    }
    result["responsables"] = detail.get("responsibles") or []
    subsystems = []
    for subsystem in detail.get("subsystems") or []:
        row = {key: subsystem.get(key) for key in (
            "id", "nombre", "nombre_proceso", "descripcion_proceso", "voltaje_potencia", "material_contacto",
            "material_estructural", "material_transportado", "flujo_kg_h", "distancia_horizontal_m",
            "distancia_vertical_m", "curvas_90", "tipo_flujo", "atex", "nec", "ubicacion",
            "aire_comprimido", "tipo_transporte", "diametro_tuberia", "tipo_acople", "potencia_hp",
            "caudal_cfm", "diferencial_presion_psi", "tipo_bomba", "area_filtracion_m2", "observaciones"
        )}
        row["entradas"] = subsystem.get("entry_points") or []
        row["salidas"] = subsystem.get("exit_points") or []
        row["equipos"] = (subsystem.get("equipment") or [])[:80]
        row["cantidad_ofertas"] = len(subsystem.get("offers") or [])
        row["cantidad_imagenes"] = len(subsystem.get("images") or [])
        subsystems.append(row)
    result["subsistemas"] = subsystems
    return result


def _resolve_reference(args: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if args.get("id") not in (None, ""):
        rows = find_exact("id", str(args.get("id")))
    elif str(args.get("proyecto") or "").strip():
        rows = find_exact("proyecto", str(args.get("proyecto")))
    elif str(args.get("radicado") or "").strip():
        rows = find_exact("radicado", str(args.get("radicado")))
    else:
        return None, []
    if len(rows) == 1:
        return get_opportunity(int(rows[0]["id"])), rows
    return None, rows


def tool_definitions() -> list[dict[str, Any]]:
    common_filters = {
        "texto": {"type": "string", "description": "Palabras libres que deben aparecer en la informacion indexada."},
        **{field: {"type": "string", "description": f"Filtro opcional por {field}."} for field in _FILTER_FIELDS},
        "limite": {"type": "integer", "minimum": 1, "maximum": 30},
    }
    return [
        {
            "type": "function",
            "name": "listar_oportunidades",
            "description": "Lista oportunidades recientes sin exigir filtros. Usala para preguntas generales como 'que proyectos hay'.",
            "parameters": {"type": "object", "properties": {"limite": {"type": "integer", "minimum": 1, "maximum": 30}}, "additionalProperties": False},
        },
        {
            "type": "function",
            "name": "buscar_oportunidades",
            "description": "Busca oportunidades combinando texto libre y filtros estructurados. Todos los filtros proporcionados se cumplen al mismo tiempo.",
            "parameters": {"type": "object", "properties": common_filters, "additionalProperties": False},
        },
        {
            "type": "function",
            "name": "contar_oportunidades",
            "description": "Cuenta oportunidades que cumplen una consulta o filtros.",
            "parameters": {"type": "object", "properties": common_filters, "additionalProperties": False},
        },
        {
            "type": "function",
            "name": "obtener_oportunidad",
            "description": "Obtiene el detalle completo de una oportunidad por ID interno, numero de proyecto o radicado.",
            "parameters": {"type": "object", "properties": {
                "id": {"type": "integer"}, "proyecto": {"type": "string"}, "radicado": {"type": "string"}
            }, "additionalProperties": False},
        },
        {
            "type": "function",
            "name": "listar_archivos",
            "description": "Lista ofertas PDF o imagenes existentes de una oportunidad. Solo localiza archivos; nunca los modifica.",
            "parameters": {"type": "object", "properties": {
                "id_oportunidad": {"type": "integer"},
                "tipo": {"type": "string", "enum": ["OFERTA", "IMAGEN", "TODOS"]}
            }, "required": ["id_oportunidad", "tipo"], "additionalProperties": False},
        },
        {
            "type": "function",
            "name": "listar_equipos",
            "description": "Lista equipos asociados a una oportunidad agrupados por subsistema.",
            "parameters": {"type": "object", "properties": {"id_oportunidad": {"type": "integer"}}, "required": ["id_oportunidad"], "additionalProperties": False},
        },
        {
            "type": "function",
            "name": "resumir_equipos_historicos",
            "description": "Agrupa los equipos mas repetidos entre oportunidades que cumplen texto o filtros.",
            "parameters": {"type": "object", "properties": common_filters, "additionalProperties": False},
        },
        {
            "type": "function",
            "name": "buscar_similares",
            "description": "Busca oportunidades historicas tecnicamente similares a una OD existente.",
            "parameters": {"type": "object", "properties": {
                "id_oportunidad": {"type": "integer"}, "limite": {"type": "integer", "minimum": 1, "maximum": 12}
            }, "required": ["id_oportunidad"], "additionalProperties": False},
        },
        {
            "type": "function",
            "name": "estadisticas_oportunidades",
            "description": "Devuelve cantidades generales de oportunidades, subsistemas, equipos, ofertas e imagenes.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    ]


def execute_tool(name: str, args: dict[str, Any] | None = None) -> ToolResult:
    args = dict(args or {})

    if name == "listar_oportunidades":
        limit = _limit(args)
        rows = search_opportunities([], limit)
        total = count_opportunities([])
        return ToolResult(
            {"total": total, "resultados": rows, "mostrados": len(rows)},
            [_opportunity_card(row) for row in rows],
            [],
        )

    if name == "buscar_oportunidades":
        tokens = _tokens_from_args(args)
        limit = _limit(args)
        rows = search_opportunities(tokens, limit)
        total = count_opportunities(tokens)
        return ToolResult(
            {"total": total, "resultados": rows, "mostrados": len(rows), "filtros_aplicados": tokens},
            [_opportunity_card(row) for row in rows],
            [],
        )

    if name == "contar_oportunidades":
        tokens = _tokens_from_args(args)
        total = count_opportunities(tokens)
        examples = search_opportunities(tokens, min(_limit(args, 6, 8), 8)) if total else []
        return ToolResult(
            {"total": total, "ejemplos": examples, "filtros_aplicados": tokens},
            [_opportunity_card(row) for row in examples],
            [],
        )

    if name == "obtener_oportunidad":
        detail, rows = _resolve_reference(args)
        if detail:
            source = _opportunity_card(detail)
            return ToolResult(
                {"encontrada": True, "oportunidad": _slim_detail(detail)},
                _subsystem_cards(detail),
                [source],
            )
        return ToolResult(
            {"encontrada": False, "coincidencias": rows},
            [_opportunity_card(row) for row in rows[:12]],
            [],
        )

    if name == "listar_archivos":
        oid = int(args.get("id_oportunidad") or 0)
        kind = str(args.get("tipo") or "TODOS").upper()
        files = attachment_links(oid, None if kind == "TODOS" else kind)
        source_detail = get_opportunity(oid)
        return ToolResult(
            {"id_oportunidad": oid, "tipo": kind, "archivos": files, "total": len(files)},
            [_attachment_card(item) for item in files],
            [_opportunity_card(source_detail)] if source_detail else [],
        )

    if name == "listar_equipos":
        oid = int(args.get("id_oportunidad") or 0)
        detail = get_opportunity(oid)
        groups: list[dict[str, Any]] = []
        cards: list[dict[str, Any]] = []
        if detail:
            for subsystem in detail.get("subsystems") or []:
                rows = subsystem.get("equipment") or []
                if not rows:
                    continue
                groups.append({"subsistema": subsystem.get("nombre"), "equipos": rows[:100]})
                cards.append({
                    "type": "equipment_group",
                    "title": str(subsystem.get("nombre") or "Subsistema"),
                    "items": [f"{row.get('tipo_equipo') or '-'} | {row.get('referencia') or '-'} | Cant. {row.get('cantidad') or '-'}" for row in rows[:25]],
                })
        return ToolResult(
            {"id_oportunidad": oid, "grupos": groups, "total_registros": sum(len(group["equipos"]) for group in groups)},
            cards,
            [_opportunity_card(detail)] if detail else [],
        )

    if name == "resumir_equipos_historicos":
        tokens = _tokens_from_args(args)
        rows = equipment_summary(tokens, _limit(args, 15, 30))
        total_projects = count_opportunities(tokens)
        cards = [{
            "type": "equipment_stat",
            "title": f"{row.get('tipo_equipo') or '-'} | {row.get('referencia') or '-'}",
            "subtitle": f"Presente en {int(row.get('proyectos') or 0)} proyecto(s)",
            "meta": f"Cantidad historica registrada: {row.get('cantidad_total') or 0:g}" if isinstance(row.get("cantidad_total"), (int, float)) else "",
        } for row in rows]
        return ToolResult(
            {"proyectos_considerados": total_projects, "equipos": rows},
            cards,
            [],
        )

    if name == "buscar_similares":
        oid = int(args.get("id_oportunidad") or 0)
        rows = similar_opportunities(oid, _limit(args, 6, 12))
        source = get_opportunity(oid)
        cards = []
        for row in rows:
            reasons = [_REASON_LABELS.get(item, item) for item in row.get("similarity_reasons", [])]
            cards.append(_opportunity_card(row, {"score": row.get("similarity"), "reason": ", ".join(reasons)}))
        return ToolResult(
            {"id_origen": oid, "resultados": rows},
            cards,
            [_opportunity_card(source)] if source else [],
        )

    if name == "estadisticas_oportunidades":
        info = stats()
        return ToolResult(info, [], [])

    raise ValueError(f"Herramienta no autorizada: {name}")


def readonly_tool_names() -> tuple[str, ...]:
    return tuple(item["name"] for item in tool_definitions())
