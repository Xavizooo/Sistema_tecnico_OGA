from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import threading
import uuid

from flask import Blueprint, flash, redirect, render_template, request, url_for

from storage import DATA_DIR


bp = Blueprint("clientes", __name__, url_prefix="/clientes")

MODULE_DIR = Path(__file__).resolve().parent
PAISES_FILE = MODULE_DIR / "data" / "paises_y_10_ciudades_importantes.json"
CLIENTES_DIR = DATA_DIR / "CLIENTES"
CLIENTES_FILE = CLIENTES_DIR / "clientes.json"
_CLIENTES_LOCK = threading.RLock()


def _load_paises() -> dict[str, list[str]]:
    if not PAISES_FILE.exists():
        raise RuntimeError(f"No se encontró el archivo de países: {PAISES_FILE}")

    with PAISES_FILE.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    data.pop("_meta", None)
    return {
        str(pais): [str(ciudad) for ciudad in ciudades]
        for pais, ciudades in data.items()
        if isinstance(ciudades, list)
    }


def _ensure_clientes_file() -> None:
    CLIENTES_DIR.mkdir(parents=True, exist_ok=True)
    if not CLIENTES_FILE.exists():
        _save_clientes([])


def _load_clientes() -> list[dict]:
    _ensure_clientes_file()
    with _CLIENTES_LOCK:
        try:
            with CLIENTES_FILE.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []


def _save_clientes(rows: list[dict]) -> None:
    CLIENTES_DIR.mkdir(parents=True, exist_ok=True)
    temp = CLIENTES_FILE.with_suffix(".tmp")
    with _CLIENTES_LOCK:
        with temp.open("w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)
        os.replace(temp, CLIENTES_FILE)


def _filtered_clientes(rows: list[dict], query: str) -> list[dict]:
    query = (query or "").strip().casefold()
    if not query:
        return rows

    fields = ("nombre", "pais", "ciudad", "nota","nit")
    return [
        row
        for row in rows
        if any(query in str(row.get(field, "")).casefold() for field in fields)
    ]


def _normalize_view(raw: str) -> str:
    return "nuevo" if str(raw or "").strip().lower() == "nuevo" else "lista"


def _render(*, form_data: dict | None = None, status: int = 200):
    view = _normalize_view(request.args.get("view", "lista"))
    paises = _load_paises()
    all_clientes = _load_clientes()
    query = request.args.get("q", "").strip()

    clientes = sorted(
        _filtered_clientes(all_clientes, query),
        key=lambda row: str(row.get("nombre", "")).casefold(),
    )

    response = render_template(
        "clientes.html",
        clientes=clientes,
        total_clientes=len(all_clientes),
        paises=paises,
        query=query,
        form_data=form_data or {},
        clientes_page=True,
        clientes_view=view,
    )
    return response, status


@bp.get("/")
def index():
    return _render()


@bp.post("/nuevo")
def create():
    nombre = request.form.get("nombre", "").strip()
    pais = request.form.get("pais", "").strip()
    ciudad = request.form.get("ciudad", "").strip()
    nota = request.form.get("nota", "").strip()
    nit = request.form.get("nit", "").strip()

    form_data = {
        "nombre": nombre,
        "pais": pais,
        "ciudad": ciudad,
        "nota": nota,
        "nit": nit,
    }

    errors: list[str] = []
    paises = _load_paises()

    if not nombre:
        errors.append("El nombre del cliente es obligatorio.")
    elif len(nombre) > 160:
        errors.append("El nombre del cliente no puede superar 160 caracteres.")

    if pais not in paises:
        errors.append("Seleccione un país válido.")
    elif ciudad not in paises[pais]:
        errors.append("Seleccione una ciudad válida para el país indicado.")

    if not nota:
        errors.append("Tienes que poner una nota")
    elif len(nombre) > 160:
            errors.append("El nombre del cliente no puede superar 160 caracteres.")

    if not nit:
        errors.append("El NIT es obligatorio.")
    elif not re.fullmatch(r"\d+", nit):
        errors.append("El NIT debe contener únicamente números.")
    elif len(nit) > 30:
        errors.append("El NIT no puede superar 30 dígitos.")

    rows = _load_clientes()
    if nit and any(str(row.get("nit", "")) == nit for row in rows):
        errors.append("Ya existe un cliente registrado con ese NIT.")

    if errors:
        for message in errors:
            flash(message, "error")
        # Fuerza la vista de formulario cuando hay error de validación.
        # Se renderiza directamente para conservar los valores ingresados.
        paises = _load_paises()
        all_clientes = _load_clientes()
        response = render_template(
            "clientes.html",
            clientes=sorted(all_clientes, key=lambda row: str(row.get("nombre", "")).casefold()),
            total_clientes=len(all_clientes),
            paises=paises,
            query="",
            form_data=form_data,
            clientes_page=True,
            clientes_view="nuevo",
        )
        return response, 400

    rows.append(
        {
            "id": uuid.uuid4().hex,
            "nombre": nombre,
            "pais": pais,
            "ciudad": ciudad,
            "nota": nota,
            "nit": nit,
            "creado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    _save_clientes(rows)

    flash(f"Cliente {nombre} registrado correctamente.", "ok")
    return redirect(url_for("clientes.index", view="lista"))
