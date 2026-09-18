from __future__ import annotations

import re
import shlex
from typing import Any

from .readonly import (
    FIELD_MAP,
    attachment_links,
    count_opportunities,
    database_ready,
    equipment_summary,
    find_exact,
    get_opportunity,
    normalize,
    search_opportunities,
    similar_opportunities,
    stats,
    tool_manifest,
)

MUTATION_PATTERN = re.compile(
    r"\b(cambia|cambiar|edita|editar|modifica|modificar|elimina|eliminar|borra|borrar|"
    r"agrega|agregar|anade|anadir|sube|subir|carga|cargar|reemplaza|reemplazar|crea|crear|"
    r"actualiza|actualizar|asigna|asignar|desasigna|desasignar|renombra|renombrar|mueve|mover|"
    r"archiva|archivar|finaliza|finalizar|guarda|guardar|pon|poner|quita|quitar|adjunta|adjuntar|"
    r"marca|marcar|desmarca|desmarcar|cambiale|reemplace|reemplazame)\b",
    re.IGNORECASE,
)

QUERY_STOP_WORDS = {
    "busca", "buscar", "buscame", "encuentra", "encontrar", "muestra", "mostrar", "muestrame",
    "dame", "trae", "traeme", "quiero", "necesito", "consulta", "consultar", "revisa", "revisar",
    "proyecto", "proyectos", "oportunidad", "oportunidades", "od", "oga", "informacion", "informacion",
    "detalle", "detalles", "sobre", "de", "del", "la", "las", "el", "los", "en", "con", "por", "para",
    "que", "cual", "cuales", "un", "una", "unos", "unas", "favor", "me", "puedes", "puede", "podrias",
    "hay", "tengo", "tenemos", "ver", "quiero", "todos", "todas", "actual", "actuales",
    "se", "uso", "usa", "usan", "usaron", "usado", "usados", "utiliza", "utilizan", "utilizaron",
    "historico", "historicos", "historica", "historicas", "mas", "repetido", "repetidos",
}

REASON_LABELS = {
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


def _field_tokens(message: str) -> list[tuple[str | None, str]]:
    try:
        parts = shlex.split(str(message or ""), posix=True)
    except ValueError:
        parts = str(message or "").split()
    output: list[tuple[str | None, str]] = []
    for part in parts:
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        key = normalize(key).replace("-", "_")
        if key in FIELD_MAP and value.strip():
            output.append((key, value.strip()))
    return output


def _free_tokens(message: str) -> list[tuple[str | None, str]]:
    cleaned = re.sub(r"\b(?:cliente|material|estado|responsable|pais|ciudad|industria|tipo|subsistema|proceso|"
                     r"flujo|voltaje|atex|nec|equipo|entrada|salida|oferta|imagen|radicado|proyecto)\s*:\s*"
                     r"(?:\"[^\"]*\"|'[^']*'|\S+)", " ", str(message or ""), flags=re.IGNORECASE)
    words = re.findall(r"[A-Za-z0-9_\-/\.]+", normalize(cleaned))
    values: list[tuple[str | None, str]] = []
    for word in words:
        if word in QUERY_STOP_WORDS or len(word) < 2:
            continue
        if word in {"pdf", "pdfs", "oferta", "ofertas", "imagen", "imagenes", "foto", "fotos", "similar", "similares", "parecido", "parecidos", "criterio", "criterios", "equipo", "equipos", "cantidad", "cuantos", "cuantas", "total", "id"}:
            continue
        if re.fullmatch(r"\d+", word) and re.search(rf"\b(?:proyecto|radicado|od|id)\s*[:#-]?\s*{re.escape(word)}\b", normalize(message)):
            continue
        values.append((None, word))
    return values


def _search_tokens(message: str) -> list[tuple[str | None, str]]:
    tokens = _field_tokens(message) + _free_tokens(message)
    seen: set[tuple[str | None, str]] = set()
    unique: list[tuple[str | None, str]] = []
    for field, value in tokens:
        item = (field, normalize(value))
        if item[1] and item not in seen:
            seen.add(item)
            unique.append((field, value))
    return unique[:12]


def _extract_reference(message: str) -> tuple[str, str] | None:
    text = normalize(message)
    patterns = (
        ("proyecto", r"\bproyecto\s*[:#-]?\s*([a-z0-9._/-]+)"),
        ("radicado", r"\bradicado\s*[:#-]?\s*([a-z0-9._/-]+)"),
        ("id", r"\b(?:od\s*id|id\s*(?:de\s*)?(?:la\s*)?od)\s*[:#-]?\s*(\d+)"),
        ("id", r"\bod\s*#\s*(\d+)"),
    )
    for kind, pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return kind, match.group(1)
    return None


def _context_opportunity_id(context: dict[str, Any] | None) -> int | None:
    try:
        value = (context or {}).get("opportunity_id")
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _opportunity_card(row: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    card = {
        "type": "opportunity",
        "id": int(row.get("id") or 0),
        "title": str(row.get("nombre") or row.get("proyecto") or "Oportunidad"),
        "subtitle": f"Radicado {row.get('radicado') or '-'} | Proyecto {row.get('proyecto') or '-'}",
        "client": str(row.get("cliente") or ""),
        "status": str(row.get("estado") or ""),
        "meta": str(row.get("responsible_names") or ""),
        "url": f"/oportunidades-proyecto/?od={int(row.get('id') or 0)}",
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


def _resolve_single(message: str, context: dict[str, Any] | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    reference = _extract_reference(message)
    rows: list[dict[str, Any]] = []
    if reference:
        rows = find_exact(reference[0], reference[1])
    if not rows:
        context_id = _context_opportunity_id(context)
        if context_id:
            detail = get_opportunity(context_id)
            if detail:
                return detail, []
    if len(rows) == 1:
        return get_opportunity(int(rows[0]["id"])), []
    return None, rows


def _read_only_denial() -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "READ_ONLY",
        "answer": (
            "El Asistente OGA es de solo lectura y no puede crear, editar, reemplazar, subir ni eliminar informacion, "
            "incluso si el usuario es administrador. Si quieres, puedo localizar el registro o archivo actual y mostrarte "
            "sus datos para que realices cualquier cambio desde el modulo correspondiente."
        ),
        "cards": [],
        "sources": [],
        "blocked_write": True,
    }


def answer(message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    text = str(message or "").strip()
    if not text:
        return {"ok": False, "error": "Escribe una consulta."}
    if MUTATION_PATTERN.search(normalize(text)):
        return _read_only_denial()
    if not database_ready():
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": "La base de Oportunidades todavia no esta disponible o no contiene la estructura esperada. Importa o crea oportunidades desde su modulo y luego vuelve a consultar.",
            "cards": [],
            "sources": [],
        }

    normalized = normalize(text)
    context_id = _context_opportunity_id(context)
    source_detail, ambiguous_rows = _resolve_single(text, context)

    if any(word in normalized for word in ("ayuda", "que puedes hacer", "como funcionas")):
        info = stats()
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": (
                "Puedo consultar Oportunidades de Proyecto, buscar por texto o filtros, localizar IDs, mostrar criterios, "
                "listar equipos, encontrar proyectos similares y traer ofertas PDF o imagenes existentes. "
                f"Actualmente tengo acceso de lectura a {info['total']} oportunidades y {info['subsystems']} subsistemas."
            ),
            "cards": [],
            "sources": [],
            "suggestions": [
                "Que proyectos hay?",
                "Muestrame las ofertas del proyecto 3121",
                "Busca proyectos cliente:Nestle",
                "Busca proyectos similares a la OD actual",
            ],
        }

    if ambiguous_rows and any(term in normalized for term in ("pdf", "oferta", "imagen", "criterio", "detalle", "similar", "parecid")):
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": "Encontre mas de una oportunidad con ese identificador. Selecciona la correcta:",
            "cards": [_opportunity_card(row) for row in ambiguous_rows[:10]],
            "sources": [],
        }

    if any(term in normalized for term in ("pdf", "oferta", "ofertas")):
        if not source_detail:
            tokens = _search_tokens(text)
            matches = search_opportunities(tokens, 10) if tokens else []
            if len(matches) == 1:
                source_detail = get_opportunity(int(matches[0]["id"]))
            elif matches:
                return {
                    "ok": True,
                    "mode": "READ_ONLY",
                    "answer": "Encontre varias oportunidades. Elige una para consultar sus ofertas PDF:",
                    "cards": [_opportunity_card(row) for row in matches],
                    "sources": [],
                }
        if source_detail:
            files = attachment_links(int(source_detail["id"]), "OFERTA")
            if not files:
                message_out = f"La oportunidad Proyecto {source_detail.get('proyecto') or '-'} no tiene ofertas PDF registradas."
            else:
                message_out = f"Encontre {len(files)} oferta(s) PDF para Proyecto {source_detail.get('proyecto') or '-'}; estan organizadas por subsistema."
            return {
                "ok": True,
                "mode": "READ_ONLY",
                "answer": message_out,
                "cards": [_attachment_card(item) for item in files],
                "sources": [_opportunity_card(source_detail)],
            }
        return {"ok": True, "mode": "READ_ONLY", "answer": "Indica el proyecto, radicado o abre una OD antes de pedirme su PDF.", "cards": [], "sources": []}

    if any(term in normalized for term in ("imagen", "imagenes", "foto", "fotos")):
        if source_detail:
            files = attachment_links(int(source_detail["id"]), "IMAGEN")
            return {
                "ok": True,
                "mode": "READ_ONLY",
                "answer": f"Encontre {len(files)} imagen(es) asociadas al Proyecto {source_detail.get('proyecto') or '-'}." if files else f"El Proyecto {source_detail.get('proyecto') or '-'} no tiene imagenes registradas.",
                "cards": [_attachment_card(item) for item in files],
                "sources": [_opportunity_card(source_detail)],
            }

    if any(term in normalized for term in ("similar", "similares", "parecido", "parecidos", "parecida", "parecidas")):
        source_id = int(source_detail["id"]) if source_detail else context_id
        if not source_id:
            return {"ok": True, "mode": "READ_ONLY", "answer": "Abre una oportunidad o indica su proyecto/radicado para buscar proyectos similares.", "cards": [], "sources": []}
        source = get_opportunity(source_id)
        rows = similar_opportunities(source_id, 6)
        cards = []
        for row in rows:
            reasons = [REASON_LABELS.get(item, item) for item in row.get("similarity_reasons", [])]
            cards.append(_opportunity_card(row, {
                "score": row.get("similarity"),
                "reason": ", ".join(reasons),
            }))
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": f"Compare la OD actual contra el historico y encontre {len(rows)} coincidencias tecnicas relevantes. El porcentaje es una similitud interna, no una recomendacion de ingenieria.",
            "cards": cards,
            "sources": [_opportunity_card(source)] if source else [],
        }

    if any(term in normalized for term in ("criterio", "criterios", "subsistema", "subsistemas", "detalle", "detalles")) and source_detail:
        subsystems = source_detail.get("subsystems") or []
        cards = []
        for subsystem in subsystems:
            criteria = []
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
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": f"Proyecto {source_detail.get('proyecto') or '-'} | Radicado {source_detail.get('radicado') or '-'} tiene {len(subsystems)} subsistema(s).",
            "cards": cards,
            "sources": [_opportunity_card(source_detail)],
        }

    if "equipo" in normalized or "equipos" in normalized:
        if source_detail and not _search_tokens(text):
            equipment_cards = []
            total = 0
            for subsystem in source_detail.get("subsystems") or []:
                rows = subsystem.get("equipment") or []
                total += len(rows)
                if rows:
                    equipment_cards.append({
                        "type": "equipment_group",
                        "title": str(subsystem.get("nombre") or "Subsistema"),
                        "items": [f"{row.get('tipo_equipo') or '-'} | {row.get('referencia') or '-'} | Cant. {row.get('cantidad') or '-'}" for row in rows[:20]],
                    })
            return {
                "ok": True,
                "mode": "READ_ONLY",
                "answer": f"El Proyecto {source_detail.get('proyecto') or '-'} tiene {total} registro(s) de equipos asociados.",
                "cards": equipment_cards,
                "sources": [_opportunity_card(source_detail)],
            }
        tokens = _search_tokens(text)
        rows = equipment_summary(tokens, 15)
        count = count_opportunities(tokens)
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": f"Revise {count} oportunidad(es) que cumplen la consulta y agrupe los equipos mas repetidos." if count else "No encontre oportunidades que cumplan esa consulta.",
            "cards": [{
                "type": "equipment_stat",
                "title": f"{row.get('tipo_equipo') or '-'} | {row.get('referencia') or '-'}",
                "subtitle": f"Presente en {int(row.get('proyectos') or 0)} proyecto(s)",
                "meta": f"Cantidad historica registrada: {row.get('cantidad_total') or 0:g}" if isinstance(row.get('cantidad_total'), (int, float)) else "",
            } for row in rows],
            "sources": [],
        }

    if any(term in normalized.split() for term in ("cuantos", "cuantas", "cantidad", "total")):
        tokens = _search_tokens(text)
        total = count_opportunities(tokens)
        rows = search_opportunities(tokens, 8) if total else []
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": f"Encontre {total} oportunidad(es) que cumplen la consulta.",
            "cards": [_opportunity_card(row) for row in rows],
            "sources": [],
        }

    reference = _extract_reference(text)
    if reference:
        rows = find_exact(reference[0], reference[1])
        if rows:
            return {
                "ok": True,
                "mode": "READ_ONLY",
                "answer": f"Encontre {len(rows)} oportunidad(es) con ese identificador. Cada resultado muestra su ID interno, radicado y proyecto.",
                "cards": [_opportunity_card(row, {"internal_id": int(row["id"])}) for row in rows],
                "sources": [],
            }

    tokens = _search_tokens(text)
    rows = search_opportunities(tokens, 12)
    total = count_opportunities(tokens)
    if not rows:
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": "No encontre coincidencias en Oportunidades de Proyecto. Prueba con cliente:, proyecto:, radicado:, material:, estado: o responsable:.",
            "cards": [],
            "sources": [],
        }
    return {
        "ok": True,
        "mode": "READ_ONLY",
        "answer": f"Encontre {total} oportunidad(es). Te muestro las {min(len(rows), 12)} mas relevantes segun los filtros de la consulta.",
        "cards": [_opportunity_card(row, {"internal_id": int(row["id"])}) for row in rows],
        "sources": [],
    }


def capabilities() -> dict[str, Any]:
    return {
        "read_only": True,
        "tools": list(tool_manifest()),
        "mutations_available": False,
    }
