from __future__ import annotations

from typing import Any

from .local_engine import MUTATION_PATTERN, capabilities as local_capabilities, answer as local_answer
from .openai_provider import ProviderError, provider_status, run_agent
from .readonly import database_ready, normalize, stats
from .tools import execute_tool, readonly_tool_names


def _read_only_denial() -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "READ_ONLY",
        "answer": (
            "El Asistente OGA es estrictamente de solo lectura. No puede crear, editar, reemplazar, subir ni eliminar "
            "informacion o archivos, incluso si el usuario es administrador. Si quieres, puedo localizar el registro, "
            "ID, PDF o imagen existente para que lo consultes."
        ),
        "cards": [],
        "sources": [],
        "blocked_write": True,
        "engine": "Barrera local de seguridad",
    }


def answer(message: str, context: dict[str, Any] | None = None, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    text = str(message or "").strip()
    if not text:
        return {"ok": False, "error": "Escribe una consulta."}
    if len(text) > 4000:
        return {"ok": False, "error": "La consulta supera el limite de 4000 caracteres."}

    # Primera barrera local. La segunda es que el agente solo recibe herramientas READ_ONLY
    # y SQLite se abre con mode=ro + PRAGMA query_only=ON.
    if MUTATION_PATTERN.search(normalize(text)):
        return _read_only_denial()

    if (context or {}).get("_is_designer"):
        return restricted_answer(text, context or {}, history or [])

    status = provider_status()
    # La IA avanzada de esta revision conserva herramientas de Oportunidades.
    # Si esa base no existe, usamos el motor local transversal en vez de bloquear
    # consultas a Biblioteca, Proyectos, RQ, Planos, etc.
    if status.get("configured") and database_ready():
        try:
            return run_agent(text, context or {}, history or [], execute_tool)
        except ProviderError as exc:
            # Degradacion controlada: una caida de Internet/API no inutiliza el asistente.
            fallback = local_answer(text, context or {})
            fallback["engine"] = "Motor local de respaldo"
            fallback["provider_warning"] = str(exc)
            return fallback
        except Exception as exc:
            fallback = local_answer(text, context or {})
            fallback["engine"] = "Motor local de respaldo"
            fallback["provider_warning"] = f"IA avanzada no disponible: {type(exc).__name__}"
            return fallback

    fallback = local_answer(text, context or {})
    fallback["engine"] = "Motor local · configura OPENAI_API_KEY para IA avanzada"
    return fallback


def capabilities() -> dict[str, Any]:
    base = local_capabilities()
    status = provider_status()
    tools: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(base.get("tools") or []) + [{"name": name, "mode": "READ_ONLY"} for name in readonly_tool_names()]:
        name = str(item.get("name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        tools.append(dict(item))
    return {
        **base,
        "read_only": True,
        "mutations_available": False,
        "provider": status,
        "tools": tools,
        "stats": stats(),
    }


def restricted_answer(text, context, history):
    """Un diseñador consulta solo una fuente autorizada, sin búsqueda transversal."""
    from . import universal_readonly as u
    allowed = set(context.get('_allowed_modules', []))
    module = u._module_detect(text, context)
    mapping = {'diseno': 'proyectos', 'lista_maestra': 'rq', 'rq': 'rq', 'planos': 'planos',
        'biblioteca': 'biblioteca', 'capacitaciones': 'capacitaciones', 'calendario': 'rq', 'backups': 'rq'}
    calls = {'diseno': lambda: u._design_answer(text), 'lista_maestra': lambda: u._master_answer(text),
        'rq': lambda: u._rq_answer(text, context), 'planos': lambda: u._planos_answer(text, context),
        'biblioteca': lambda: u._library_answer(text), 'capacitaciones': lambda: u._training_answer(text),
        'calendario': lambda: u._calendar_answer(text), 'backups': lambda: u._backups_answer(context)}
    if module in mapping and mapping[module] in allowed: return calls[module]()
    if module is None and 'oportunidades' in allowed and any(w in normalize(text).split() for w in ['od','oportunidad','oportunidades','radicado','oferta','ofertas']):
        status = provider_status()
        if status.get('configured') and database_ready():
            try: return run_agent(text, context, history, execute_tool)
            except ProviderError: pass
        return local_answer(text, {**context, '_restricted_od': True})
    return {'ok': True, 'mode': 'READ_ONLY', 'answer':
      'Consulta limitada a tus módulos autorizados. Indica el módulo en tu pregunta (por ejemplo: Biblioteca, RQ, Planos u Oportunidades). Las consultas de usuarios y auditoría requieren al Desarrollador.',
      'cards': [], 'sources': [], 'engine': 'Consulta con permisos'}
