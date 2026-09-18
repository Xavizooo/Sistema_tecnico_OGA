from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from .engine import answer, capabilities
from .readonly import stats

bp = Blueprint("asistente_oga", __name__, url_prefix="/asistente-oga")


def _safe_history(raw) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    output: list[dict[str, str]] = []
    for item in raw[-10:]:
        if not isinstance(item, dict):
            continue
        role = "user" if str(item.get("role")) == "user" else "assistant"
        content = str(item.get("content") or "").strip()
        if content:
            output.append({"role": role, "content": content[:1500]})
    return output


@bp.get("/")
def index():
    caps = capabilities()
    return render_template(
        "asistente/index.html",
        assistant_page=True,
        assistant_stats=stats(),
        assistant_capabilities=caps,
        assistant_provider=caps.get("provider") or {},
    )


@bp.post("/consultar")
def consult():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message") or "").strip()
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    history = _safe_history(payload.get("history"))
    if len(message) > 4000:
        return jsonify({"ok": False, "error": "La consulta supera el limite de 4000 caracteres."}), 400
    result = answer(message, context, history)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@bp.get("/capacidades")
def capability_manifest():
    return jsonify({"ok": True, **capabilities()})
