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

    if not database_ready():
        return {
            "ok": True,
            "mode": "READ_ONLY",
            "answer": "La base de Oportunidades todavia no esta disponible. Crea o importa oportunidades y vuelve a consultar.",
            "cards": [],
            "sources": [],
            "engine": "Motor local",
        }

    status = provider_status()
    if status.get("configured"):
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
    return {
        **base,
        "read_only": True,
        "mutations_available": False,
        "provider": status,
        "tools": [{"name": name, "mode": "READ_ONLY"} for name in readonly_tool_names()],
        "stats": stats(),
    }
