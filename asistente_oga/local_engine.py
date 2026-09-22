from __future__ import annotations

import re
import shlex
from typing import Any

from .universal_readonly import answer_universal, universal_manifest

from .readonly import (
    FIELD_MAP,
    attachment_links,
    count_opportunities,
    count_opportunities_in_ids,
    database_ready,
    equipment_summary,
    find_exact,
    get_opportunity,
    normalize,
    search_opportunities,
    search_opportunities_in_ids,
    search_term_exists,
    similar_opportunities,
    stats,
    tool_manifest,
)

MUTATION_PATTERN = re.compile(
    r"\b(cambia|cambiar|edita|editar|modifica|modificar|elimina|eliminar|borra|borrar|"
    r"agrega|agregar|anade|anadir|sube|subir|cargar|reemplaza|reemplazar|crea|crear|"
    r"actualiza|actualizar|asigna|asignar|desasigna|desasignar|renombra|renombrar|mueve|mover|"
    r"archiva|archivar|finaliza|finalizar|guarda|guardar|pon|poner|quita|quitar|adjunta|adjuntar|"
    r"marcar|desmarca|desmarcar|cambiale|reemplace|reemplazame)\b",
    re.IGNORECASE,
)

QUERY_STOP_WORDS = {
    # Acciones conversacionales
    "busca", "buscar", "buscame", "encuentra", "encontrar", "muestra", "mostrar", "muestrame",
    "dame", "dime", "trae", "traeme", "quiero", "quisiera", "necesito", "consulta", "consultar",
    "revisa", "revisar", "cuenta", "cuentame", "explica", "explicame", "saber", "sabes", "ver",
    # Sustantivos genericos de la aplicacion
    "proyecto", "proyectos", "oportunidad", "oportunidades", "od", "oga", "informacion", "info",
    "detalle", "detalles", "registro", "registros", "dato", "datos",
    # Conectores y lenguaje cotidiano
    "sobre", "de", "del", "la", "las", "el", "los", "en", "con", "por", "para", "al", "a",
    "que", "cual", "cuales", "quien", "quienes", "donde", "cuando", "como", "un", "una", "unos", "unas",
    "favor", "me", "puedes", "puede", "podrias", "podria", "hay", "tengo", "tenemos", "tienen", "tiene",
    "todos", "todas", "todo", "toda", "actual", "actuales", "algo", "alguno", "alguna", "algunos", "algunas",
    "ese", "esa", "esos", "esas", "este", "esta", "estos", "estas", "anterior", "anteriores",
    "se", "lo", "le", "les", "su", "sus", "mi", "mis", "nuestro", "nuestra", "nuestros", "nuestras",
    # Verbos que suelen ser ruido en una busqueda tecnica
    "uso", "usa", "usan", "usaron", "usado", "usados", "utiliza", "utilizan", "utilizaron", "utilizo",
    "maneja", "manejan", "manejaba", "manejaron", "manejado", "transporta", "transportan", "transportaba",
    "tenga", "tengan", "tenia", "tenian", "contiene", "contienen", "incluye", "incluyen", "trabaja", "trabajan",
    "hizo", "hicieron", "hecho", "sirve", "sirven", "aparece", "aparecen", "pertenece", "pertenecen",
    # Palabras de contexto que no deben volverse filtros
    "historico", "historicos", "historica", "historicas", "mas", "menos", "repetido", "repetidos",
    "cliente", "clientes", "empresa", "empresas", "material", "materiales", "responsable", "responsables",
    "ciudad", "pais", "industria", "estado", "tipo", "planta", "campo", "campos",
    "ganado", "ganada", "ganados", "ganadas", "ganamos", "perdido", "perdida", "perdidos", "perdidas", "perdimos",
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

STATE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(?:ganad[oa]s?|ganamos|cerrad[oa]s?\s+satisfactori[oa]s?|exitos[oa]s?)\b", "Ganada"),
    (r"\b(?:perdid[oa]s?|perdimos|cerrad[oa]s?\s+insatisfactori[oa]s?|no\s+ganad[oa]s?)\b", "Perdida"),
    (r"\b(?:cotizando|cotizacion|cotizaciones|en\s+cotizacion)\b", "Cotizando"),
    (r"\b(?:oferta\s+enviada|ofertas\s+enviadas|enviada\s+al\s+cliente)\b", "Oferta enviada"),
    (r"\b(?:en\s+analisis|analizando|analisis)\b", "En analisis"),
    (r"\b(?:nuev[oa]s?|abiert[oa]s?)\b", "Nueva"),
)

FOLLOWUP_PATTERN = re.compile(
    r"^(?:y\b|ahora\b|solo\b|solamente\b|de\s+es[oa]s?\b|entre\s+es[oa]s?\b|de\s+los\s+anteriores\b|"
    r"entre\s+los\s+anteriores\b|de\s+esas\s+oportunidades\b)",
    re.IGNORECASE,
)

DETAIL_TERMS = {
    "material", "materiales", "flujo", "voltaje", "distancia", "distancias", "atex", "nec", "ubicacion",
    "transporte", "bomba", "bombas", "acople", "acoples", "caudal", "presion", "potencia", "filtracion",
    "entrada", "entradas", "salida", "salidas", "origen", "destino", "criterio", "criterios", "subsistema",
    "subsistemas", "proceso", "procesos",
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


def _state_tokens(message: str) -> list[tuple[str | None, str]]:
    text = normalize(message)
    output: list[tuple[str | None, str]] = []
    for pattern, state in STATE_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            output.append(("estado", state))
    return output


def _natural_field_tokens(message: str) -> list[tuple[str | None, str]]:
    text = normalize(message)
    output: list[tuple[str | None, str]] = []
    type_match = re.search(r"\btipo\s+(?:de\s+oportunidad\s+)?([1-9][0-9]*)\b", text)
    if type_match:
        output.append(("tipo", f"tipo {type_match.group(1)}"))
    return output


def _free_tokens(message: str) -> list[tuple[str | None, str]]:
    cleaned = re.sub(
        r"\b(?:cliente|material|estado|responsable|pais|ciudad|industria|tipo|subsistema|proceso|"
        r"flujo|voltaje|atex|nec|equipo|entrada|salida|oferta|imagen|radicado|proyecto)\s*:\s*"
        r"(?:\"[^\"]*\"|'[^']*'|\S+)",
        " ",
        str(message or ""),
        flags=re.IGNORECASE,
    )
    words = re.findall(r"[A-Za-z0-9_\-/\.]+", normalize(cleaned))
    values: list[tuple[str | None, str]] = []
    for word in words:
        if word in QUERY_STOP_WORDS or len(word) < 2:
            continue
        if word in {
            "pdf", "pdfs", "oferta", "ofertas", "imagen", "imagenes", "foto", "fotos", "similar", "similares",
            "parecido", "parecidos", "parecida", "parecidas", "criterio", "criterios", "equipo", "equipos",
            "cantidad", "cuantos", "cuantas", "total", "id", "identificador", "primero", "primera", "segundo",
            "segunda", "tercero", "tercera", "ultimo", "ultima",
        }:
            continue
        if re.fullmatch(r"\d+", word) and re.search(
            rf"\b(?:proyecto|radicado|od|id)\s*[:#-]?\s*{re.escape(word)}\b", normalize(message)
        ):
            continue
        values.append((None, word))
    return values


def _dedupe_tokens(tokens: list[tuple[str | None, str]]) -> list[tuple[str | None, str]]:
    seen: set[tuple[str | None, str]] = set()
    unique: list[tuple[str | None, str]] = []
    for field, value in tokens:
        item = (field, normalize(value))
        if item[1] and item not in seen:
            seen.add(item)
            unique.append((field, value))
    return unique


def _search_tokens(message: str) -> list[tuple[str | None, str]]:
    structured = _field_tokens(message) + _state_tokens(message) + _natural_field_tokens(message)
    free = _free_tokens(message)

    # El lenguaje cotidiano suele incluir verbos/filtros de relleno. Si al menos
    # una palabra libre existe realmente en el indice, descartamos las que no
    # existen. Si ninguna existe, conservamos la consulta para responder
    # correctamente "sin coincidencias" en vez de listar todo.
    known_free = [item for item in free if search_term_exists(item[1])]
    if known_free:
        free = known_free

    return _dedupe_tokens(structured + free)[:12]


def _context_result_ids(context: dict[str, Any] | None) -> list[int]:
    output: list[int] = []
    raw = (context or {}).get("last_result_ids")
    if not isinstance(raw, list):
        return output
    for item in raw[:20]:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in output:
            output.append(value)
    return output


def _ordinal_index(message: str) -> int | None:
    text = normalize(message)
    mapping = (
        (0, ("primero", "primera", "1ro", "1ra", "numero 1")),
        (1, ("segundo", "segunda", "2do", "2da", "numero 2")),
        (2, ("tercero", "tercera", "3ro", "3ra", "numero 3")),
        (3, ("cuarto", "cuarta", "4to", "4ta", "numero 4")),
        (4, ("quinto", "quinta", "5to", "5ta", "numero 5")),
    )
    for index, words in mapping:
        if any(re.search(rf"\b{re.escape(word)}\b", text) for word in words):
            return index
    if re.search(r"\b(?:ultimo|ultima)\b", text):
        return -1
    return None


def _followup_scope_ids(message: str, context: dict[str, Any] | None) -> list[int]:
    ids = _context_result_ids(context)
    if not ids:
        return []
    text = normalize(message)
    if FOLLOWUP_PATTERN.search(text) or any(phrase in text for phrase in (
        "de esos", "de esas", "entre esos", "entre esas", "los anteriores", "las anteriores"
    )):
        return ids
    return []


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
    data = context or {}
    for key in ("opportunity_id", "last_opportunity_id"):
        try:
            value = data.get(key)
            if value not in (None, ""):
                parsed = int(value)
                if parsed > 0:
                    return parsed
        except (TypeError, ValueError):
            continue
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


def _opportunity_fact_card(detail: dict[str, Any]) -> dict[str, Any]:
    responsibles = detail.get("responsibles") or []
    responsible_names = [str(item.get("name") or item.get("username") or "").strip() for item in responsibles]
    items = []
    for label, value in (
        ("ID OD", detail.get("id")),
        ("Radicado", detail.get("radicado")),
        ("Proyecto", detail.get("proyecto")),
        ("Cliente", detail.get("cliente")),
        ("Estado", detail.get("estado")),
        ("Planta", detail.get("planta")),
        ("Ciudad", detail.get("ciudad")),
        ("Pais", detail.get("pais")),
        ("Industria", detail.get("industria")),
        ("Tipo de oportunidad", detail.get("tipo_oportunidad")),
        ("Fecha de inicio", detail.get("fecha_inicio")),
        ("Equipo responsable", ", ".join(item for item in responsible_names if item)),
    ):
        if value not in (None, ""):
            items.append(f"{label}: {value}")
    return {
        "type": "opportunity_detail",
        "title": str(detail.get("nombre") or detail.get("proyecto") or "Oportunidad"),
        "subtitle": str(detail.get("descripcion") or ""),
        "items": items,
        "internal_id": int(detail.get("id") or 0),
        "url": f"/oportunidades-proyecto/?od={int(detail.get('id') or 0)}",
    }


def _technical_cards(detail: dict[str, Any], message: str) -> list[dict[str, Any]]:
    text = normalize(message)
    requested = set(re.findall(r"[a-z0-9]+", text))
    show_all = bool(requested & {"criterio", "criterios", "detalle", "detalles", "subsistema", "subsistemas", "proceso", "procesos"})
    wants_entry = bool(requested & {"entrada", "entradas", "origen"}) or "de donde" in text
    wants_exit = bool(requested & {"salida", "salidas", "destino"}) or "a donde" in text

    field_groups: list[tuple[set[str], tuple[tuple[str, str], ...]]] = [
        ({"material", "materiales"}, (("material_transportado", "Material transportado"), ("material_contacto", "Material contacto"), ("material_estructural", "Material estructural"))),
        ({"flujo"}, (("flujo_kg_h", "Flujo kg/h"),)),
        ({"voltaje"}, (("voltaje_potencia", "Voltaje"),)),
        ({"distancia", "distancias"}, (("distancia_horizontal_m", "Dist. horizontal m"), ("distancia_vertical_m", "Dist. vertical m"), ("curvas_90", "Curvas 90°"))),
        ({"atex", "nec"}, (("atex", "ATEX"), ("nec", "NEC"))),
        ({"ubicacion"}, (("ubicacion", "Ubicacion"),)),
        ({"transporte"}, (("tipo_transporte", "Tipo de transporte"), ("tipo_flujo", "Tipo de flujo"), ("diametro_tuberia", "Diametro tuberia"))),
        ({"bomba", "bombas"}, (("tipo_bomba", "Tipo de bomba"),)),
        ({"acople", "acoples"}, (("tipo_acople", "Tipo de acople"),)),
        ({"caudal"}, (("caudal_cfm", "Caudal CFM"),)),
        ({"presion"}, (("diferencial_presion_psi", "Diferencial presion PSI"),)),
        ({"potencia"}, (("potencia_hp", "Potencia hp"),)),
        ({"filtracion"}, (("area_filtracion_m2", "Area filtracion m²"),)),
    ]
    default_fields = (
        ("material_transportado", "Material"), ("flujo_kg_h", "Flujo kg/h"),
        ("tipo_transporte", "Transporte"), ("voltaje_potencia", "Voltaje"),
        ("distancia_horizontal_m", "Dist. horizontal m"), ("distancia_vertical_m", "Dist. vertical m"),
        ("atex", "ATEX"), ("nec", "NEC"), ("ubicacion", "Ubicacion"),
    )

    selected_fields: list[tuple[str, str]] = []
    for terms, fields in field_groups:
        if requested & terms:
            selected_fields.extend(fields)
    if show_all or (not selected_fields and not wants_entry and not wants_exit):
        selected_fields.extend(default_fields)

    # preserve order while removing duplicates
    seen = set()
    selected_fields = [item for item in selected_fields if not (item[0] in seen or seen.add(item[0]))]

    cards: list[dict[str, Any]] = []
    for subsystem in detail.get("subsystems") or []:
        criteria: list[str] = []
        for key, label in selected_fields:
            value = str(subsystem.get(key) or "").strip()
            if value:
                criteria.append(f"{label}: {value}")
        if wants_entry or show_all:
            for row in subsystem.get("entry_points") or []:
                criteria.append(f"Entrada: {row.get('tipo') or '-'} | Cant. {row.get('cantidad') or '-'} | Restr. altura {row.get('restriccion_altura') or '-'}")
        if wants_exit or show_all:
            for row in subsystem.get("exit_points") or []:
                criteria.append(f"Salida: {row.get('tipo') or '-'} | Cant. {row.get('cantidad') or '-'} | Restr. altura {row.get('restriccion_altura') or '-'}")
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


def _is_id_question(message: str) -> bool:
    text = normalize(message)
    return bool(re.search(r"\b(?:id|identificador|numero\s+interno)\b", text))


def _is_general_detail_question(message: str) -> bool:
    text = normalize(message)
    return any(phrase in text for phrase in (
        "que sabes", "que se hizo", "de que trata", "cuentame", "informacion del", "informacion de la",
        "datos del", "datos de la", "quien es el cliente", "cual es el cliente", "que cliente",
        "estado del", "responsable del", "responsables del",
    ))


def _has_technical_detail_intent(message: str) -> bool:
    words = set(re.findall(r"[a-z0-9]+", normalize(message)))
    return bool(words & DETAIL_TERMS) or "de donde" in normalize(message) or "a donde" in normalize(message)


def _resolve_single(message: str, context: dict[str, Any] | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    reference = _extract_reference(message)
    rows: list[dict[str, Any]] = []
    if reference:
        rows = find_exact(reference[0], reference[1])
        if len(rows) == 1:
            return get_opportunity(int(rows[0]["id"])), []
        if rows:
            return None, rows

    # Conversacion local: "el primero", "el segundo", "el ultimo"
    # se resuelven contra la lista de resultados que acaba de ver el usuario.
    result_ids = _context_result_ids(context)
    ordinal = _ordinal_index(message)
    if ordinal is not None and result_ids:
        try:
            selected_id = result_ids[ordinal]
        except IndexError:
            selected_id = None
        if selected_id:
            detail = get_opportunity(selected_id)
            if detail:
                return detail, []

    context_id = _context_opportunity_id(context)
    if context_id:
        detail = get_opportunity(context_id)
        if detail:
            return detail, []
    return None, []


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

    # V 17.5.2: antes de asumir que toda pregunta pertenece a Oportunidades,
    # el motor local enruta consultas de solo lectura a los demas modulos OGA.
    universal = answer_universal(text, context or {})
    if universal is not None:
        return universal

    if not database_ready():
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": "La consulta parece pertenecer a Oportunidades de Proyecto, pero esa base todavia no esta disponible. Los demas modulos del asistente local siguen funcionando.",
            "cards": [],
            "sources": [],
        }

    normalized = normalize(text)
    context = context or {}
    context_id = _context_opportunity_id(context)
    source_detail, ambiguous_rows = _resolve_single(text, context)
    scope_ids = _followup_scope_ids(text, context)

    def scoped_search(tokens: list[tuple[str | None, str]], limit: int) -> list[dict[str, Any]]:
        if scope_ids:
            return search_opportunities_in_ids(tokens, scope_ids, limit)
        return search_opportunities(tokens, limit)

    def scoped_count(tokens: list[tuple[str | None, str]]) -> int:
        if scope_ids:
            return count_opportunities_in_ids(tokens, scope_ids)
        return count_opportunities(tokens)

    if any(word in normalized for word in ("ayuda", "que puedes hacer", "como funcionas", "para que sirves")):
        info = stats()
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": (
                "Puedo consultar Oportunidades de Proyecto con lenguaje cotidiano: listar proyectos, buscar por cliente, "
                "material o estado, localizar IDs, mostrar criterios, listar equipos, buscar similares y traer ofertas PDF "
                "o imagenes existentes. Tambien puedo continuar sobre los resultados anteriores con frases como "
                "'cuales tienen BIG BAG?', 'dame el ID del primero' o 'traeme sus PDF'. "
                f"Actualmente tengo acceso de lectura a {info['total']} oportunidades y {info['subsystems']} subsistemas."
            ),
            "cards": [],
            "sources": [],
            "suggestions": [
                "Que proyectos hay?",
                "Muestrame proyectos donde se maneje harina",
                "Cuales tienen BIG BAG?",
                "Dame el ID del primero",
            ],
        }

    # Si un numero de proyecto/radicado coincide con mas de una OD, no se adivina.
    if ambiguous_rows:
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": "Encontre mas de una oportunidad con ese identificador. Selecciona la correcta para continuar:",
            "cards": [_opportunity_card(row, {"internal_id": int(row["id"])}) for row in ambiguous_rows[:12]],
            "sources": [],
        }

    # PDFs / ofertas existentes.
    if any(term in normalized for term in ("pdf", "pdfs", "oferta", "ofertas")):
        if not source_detail:
            tokens = _search_tokens(text)
            matches = scoped_search(tokens, 10) if tokens or scope_ids else []
            if len(matches) == 1:
                source_detail = get_opportunity(int(matches[0]["id"]))
            elif matches:
                return {
                    "ok": True,
                    "mode": "READ_ONLY",
                    "answer": "Encontre varias oportunidades. Elige una para consultar sus ofertas PDF:",
                    "cards": [_opportunity_card(row, {"internal_id": int(row["id"])}) for row in matches],
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
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": "Indica el proyecto o radicado, selecciona uno de los resultados anteriores o abre una OD antes de pedirme su PDF.",
            "cards": [],
            "sources": [],
        }

    # Imagenes existentes.
    if any(term in normalized for term in ("imagen", "imagenes", "foto", "fotos")):
        if not source_detail:
            tokens = _search_tokens(text)
            matches = scoped_search(tokens, 10) if tokens or scope_ids else []
            if len(matches) == 1:
                source_detail = get_opportunity(int(matches[0]["id"]))
            elif matches:
                return {
                    "ok": True,
                    "mode": "READ_ONLY",
                    "answer": "Encontre varias oportunidades. Elige una para consultar sus imagenes:",
                    "cards": [_opportunity_card(row, {"internal_id": int(row["id"])}) for row in matches],
                    "sources": [],
                }
        if source_detail:
            files = attachment_links(int(source_detail["id"]), "IMAGEN")
            return {
                "ok": True,
                "mode": "READ_ONLY",
                "answer": f"Encontre {len(files)} imagen(es) asociadas al Proyecto {source_detail.get('proyecto') or '-'}.",
                "cards": [_attachment_card(item) for item in files],
                "sources": [_opportunity_card(source_detail)],
            }

    # Comparacion tecnica por similitud.
    if any(term in normalized for term in ("similar", "similares", "parecido", "parecidos", "parecida", "parecidas", "semejante", "semejantes")):
        source_id = int(source_detail["id"]) if source_detail else context_id
        if not source_id:
            return {
                "ok": True,
                "mode": "READ_ONLY",
                "answer": "Abre una oportunidad, indica su proyecto/radicado o selecciona un resultado anterior para buscar proyectos similares.",
                "cards": [],
                "sources": [],
            }
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
            "answer": f"Compare el proyecto contra el historico y encontre {len(rows)} coincidencias tecnicas relevantes. El porcentaje es una similitud interna, no una recomendacion de ingenieria.",
            "cards": cards,
            "sources": [_opportunity_card(source)] if source else [],
        }

    # Referencias conversacionales: "dame el ID del primero", "cual es su ID".
    if source_detail and _is_id_question(text):
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": (
                f"El ID interno de la OD es {source_detail.get('id')}. "
                f"Radicado {source_detail.get('radicado') or '-'} | Proyecto {source_detail.get('proyecto') or '-'} ."
            ),
            "cards": [_opportunity_card(source_detail, {"internal_id": int(source_detail["id"])})],
            "sources": [],
        }

    # Preguntas tecnicas cotidianas sobre un proyecto concreto.
    if source_detail and _has_technical_detail_intent(text):
        cards = _technical_cards(source_detail, text)
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": (
                f"Proyecto {source_detail.get('proyecto') or '-'} | Radicado {source_detail.get('radicado') or '-'}: "
                f"encontre {len(cards)} subsistema(s) con la informacion tecnica solicitada."
            ),
            "cards": cards,
            "sources": [_opportunity_card(source_detail)],
        }

    # Preguntas generales sobre un proyecto concreto.
    if source_detail and _is_general_detail_question(text):
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": f"Estos son los datos registrados del Proyecto {source_detail.get('proyecto') or '-'}.",
            "cards": [_opportunity_fact_card(source_detail)],
            "sources": [_opportunity_card(source_detail)],
        }

    # Equipos del proyecto actual o resumen historico de una busqueda.
    if "equipo" in normalized or "equipos" in normalized:
        tokens = _search_tokens(text)
        if source_detail and not tokens:
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

    # Conteos generales o sobre los resultados anteriores.
    if any(term in normalized.split() for term in ("cuantos", "cuantas", "cantidad", "total")):
        tokens = _search_tokens(text)
        total = scoped_count(tokens)
        rows = scoped_search(tokens, 8) if total else []
        scope_text = " dentro de los resultados anteriores" if scope_ids else ""
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": f"Encontre {total} oportunidad(es){scope_text} que cumplen la consulta.",
            "cards": [_opportunity_card(row, {"internal_id": int(row["id"])}) for row in rows],
            "sources": [],
        }

    # Si se indico un proyecto/radicado explicitamente y no se pidio un dato
    # tecnico concreto, devolvemos la OD con su identificacion basica.
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

    # Busqueda cotidiana. Las palabras de relleno que no existen en el indice se
    # eliminan cuando hay al menos un termino real, por ejemplo:
    # "proyectos donde se maneja harina" -> harina.
    tokens = _search_tokens(text)
    rows = scoped_search(tokens, 12)
    total = scoped_count(tokens)
    if not rows:
        if scope_ids:
            return {
                "ok": True,
                "mode": "READ_ONLY",
                "answer": "Ninguno de los resultados anteriores cumple esa nueva condicion. Puedes hacer otra pregunta o iniciar una busqueda general.",
                "cards": [],
                "sources": [],
            }
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": "No encontre coincidencias con esa consulta. Puedes escribirlo de otra forma o usar datos como cliente, proyecto, radicado, material, estado o responsable.",
            "cards": [],
            "sources": [],
        }
    scope_text = " entre los resultados anteriores" if scope_ids else ""
    if not tokens and not scope_ids:
        answer_text = f"Hay {total} oportunidad(es) registradas. Te muestro las {min(len(rows), 12)} mas recientes."
    else:
        answer_text = f"Encontre {total} oportunidad(es){scope_text}. Te muestro {min(len(rows), 12)} resultado(s)."
    return {
        "ok": True,
        "mode": "READ_ONLY",
        "answer": answer_text,
        "cards": [_opportunity_card(row, {"internal_id": int(row["id"])}) for row in rows],
        "sources": [],
    }


def capabilities() -> dict[str, Any]:
    return {
        "read_only": True,
        "tools": list(tool_manifest()) + list(universal_manifest()),
        "mutations_available": False,
    }
