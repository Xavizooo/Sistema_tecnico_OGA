from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Dict, List

import pandas as pd
from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, send_from_directory, url_for)
from markupsafe import Markup
from werkzeug.utils import secure_filename

# REV15: a single Flask application, with the parent login and CSRF checks.
biblioteca_bp = Blueprint("biblioteca", __name__, url_prefix="/biblioteca")
_STORAGE_LOCK = threading.RLock()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "BIBLIOTECA"
FILES_DIR = DATA_DIR / "archivos"
PLANOS_DIR = FILES_DIR / "planos_pdf"
MODEL3D_DIR = FILES_DIR / "modelos_3d"
LISTA_DIR = FILES_DIR / "listas_materiales"
FICHA_DIR = FILES_DIR / "fichas_tecnicas"

EQUIPOS_FILE = DATA_DIR / "equipos.xlsx"
CARACTERISTICAS_FILE = DATA_DIR / "caracteristicas.xlsx"
REFERENCIAS_FILE = DATA_DIR / "referencias.xlsx"
COSTOS_FILE = DATA_DIR / "costos.xlsx"

CHAR_COLS = [
    "equipo_codigo",
    "orden",
    "nombre",
    "grupo_color",
    "subcaracteristicas_json",
]
REF_COLS = [
    "referencia_codigo",
    "equipo_codigo",
    "equipo_nombre",
    "selecciones_json",
    "planos",
    "modelo3d",
    "lista_materiales",
    "ficha_tecnica",
]
COST_COLS = ["referencia", "costo"]

UPLOAD_INFO = {
    "planos": {
        "folder": PLANOS_DIR,
        "exts": {".pdf"},
        "accept": ".pdf,application/pdf",
        "label": "Planos PDF",
    },
    "modelo3d": {
        "folder": MODEL3D_DIR,
        "exts": {".zip"},
        "accept": ".zip,application/zip,application/x-zip-compressed",
        "label": "Modelo 3D ZIP",
    },
    "lista_materiales": {
        "folder": LISTA_DIR,
        "exts": {".xlsm"},
        "accept": ".xlsm,application/vnd.ms-excel.sheet.macroEnabled.12",
        "label": "Lista materiales XLSM",
    },
    "ficha_tecnica": {
        "folder": FICHA_DIR,
        "exts": {".docx"},
        "accept": ".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "label": "Ficha técnica DOCX",
    },
}


def ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for info in UPLOAD_INFO.values():
        info["folder"].mkdir(parents=True, exist_ok=True)
    if not EQUIPOS_FILE.exists():
        pd.DataFrame(columns=["item", "codigo", "nombre"]).to_excel(EQUIPOS_FILE, index=False)
    if not CARACTERISTICAS_FILE.exists():
        pd.DataFrame(columns=CHAR_COLS).to_excel(CARACTERISTICAS_FILE, index=False)
    if not REFERENCIAS_FILE.exists():
        pd.DataFrame(columns=REF_COLS).to_excel(REFERENCIAS_FILE, index=False)
    if not COSTOS_FILE.exists():
        pd.DataFrame(columns=COST_COLS).to_excel(COSTOS_FILE, index=False)


def read_excel(path: Path, columns: List[str]) -> pd.DataFrame:
    ensure_storage()
    cache = g.setdefault("biblioteca_excel_cache", {})
    key = str(path)
    if key not in cache:
        try:
            df = pd.read_excel(path).fillna("").astype(object)
        except Exception:
            current_app.logger.exception("No se pudo leer el Excel de Biblioteca: %s", path.name)
            abort(503, description="No se pudo leer un archivo de Biblioteca. Cierre el Excel si está abierto y revise su copia de seguridad.")
        for col in columns:
            if col not in df.columns:
                df[col] = ""
        cache[key] = df
    return cache[key].reindex(columns=columns, fill_value="").copy()


def write_excel(path: Path, df: pd.DataFrame) -> None:
    """Atomic file replacement, protected by the per-process library lock."""
    ensure_storage()
    fd, name = tempfile.mkstemp(prefix=".biblio_", suffix=".xlsx", dir=path.parent)
    os.close(fd)
    temp = Path(name)
    try:
        df.to_excel(temp, index=False)
        os.replace(temp, path)
        g.setdefault("biblioteca_excel_cache", {}).pop(str(path), None)
    except PermissionError:
        abort(503, description="No se pudo guardar Biblioteca. Cierre el Excel abierto y vuelva a intentar.")
    finally:
        temp.unlink(missing_ok=True)


def get_equipos() -> pd.DataFrame:
    return read_excel(EQUIPOS_FILE, ["item", "codigo", "nombre"])


def save_equipos(df: pd.DataFrame) -> None:
    write_excel(EQUIPOS_FILE, df)


def get_caracteristicas() -> pd.DataFrame:
    df = read_excel(CARACTERISTICAS_FILE, CHAR_COLS)
    return df


def save_caracteristicas(df: pd.DataFrame) -> None:
    write_excel(CARACTERISTICAS_FILE, df[CHAR_COLS])


def get_referencias() -> pd.DataFrame:
    return read_excel(REFERENCIAS_FILE, REF_COLS)


def save_referencias(df: pd.DataFrame) -> None:
    write_excel(REFERENCIAS_FILE, df[REF_COLS])


def get_costos() -> pd.DataFrame:
    return read_excel(COSTOS_FILE, COST_COLS)


def save_costos(df: pd.DataFrame) -> None:
    write_excel(COSTOS_FILE, df[COST_COLS])


def format_money(value) -> str:
    raw = str(value).strip()
    if not raw:
        return "Sin costo"
    try:
        amount = float(str(raw).replace("$", "").replace(",", "").replace(" ", ""))
        return "$ {:,.0f}".format(amount).replace(",", ".")
    except Exception:
        return raw


def next_item() -> int:
    equipos = get_equipos()
    if equipos.empty:
        return 1
    return int(pd.to_numeric(equipos["item"], errors="coerce").fillna(0).max()) + 1


def parse_sub_rows(form) -> List[dict]:
    items = []
    for i in range(1, 51):
        code = str(form.get(f"sub_codigo_{i}", "")).strip().upper()
        text = str(form.get(f"sub_texto_{i}", "")).strip().upper()
        if code or text:
            items.append({"codigo": code, "texto": text})
    return items


def parse_json_list(value) -> List[dict]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value or "[]"))
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def get_equipo_row(equipo_codigo: str):
    equipos = get_equipos()
    match = equipos[equipos["codigo"].astype(str) == str(equipo_codigo)]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def chars_for_equipo(equipo_codigo: str) -> List[dict]:
    if not equipo_codigo:
        return []
    df = get_caracteristicas()
    filtered = df[df["equipo_codigo"].astype(str) == str(equipo_codigo)].copy()
    if filtered.empty:
        return []
    filtered["orden_num"] = pd.to_numeric(filtered["orden"], errors="coerce").fillna(9999)
    filtered = filtered.sort_values(["orden_num", "orden"])
    result = []
    for _, row in filtered.iterrows():
        result.append(
            {
                "equipo_codigo": str(row["equipo_codigo"]),
                "orden": str(row["orden"]),
                "nombre": str(row["nombre"]),
                "grupo_color": str(row["grupo_color"] or "green"),
                "subcaracteristicas": parse_json_list(row["subcaracteristicas_json"]),
            }
        )
    return result


def selections_from_request(chars: List[dict], form) -> Dict[str, str]:
    result = {}
    for c in chars:
        key = f"subchoice_{c['orden']}"
        result[c["orden"]] = str(form.get(key, "")).strip().upper()
    return result


def build_reference_code(equipo_codigo: str, selections: Dict[str, str], ordered_chars: List[dict]) -> str:
    parts = [str(equipo_codigo).strip().upper()]
    for c in ordered_chars:
        code = str(selections.get(c["orden"], "")).strip().upper()
        if code:
            parts.append(code)
    return "".join(parts)


def save_cost(reference: str, value: str) -> None:
    reference = str(reference).strip().upper()
    df = get_costos()
    idx = df[df["referencia"].astype(str).str.upper() == reference].index
    if str(value).strip() == "":
        if len(idx):
            df = df.drop(idx)
            save_costos(df.reset_index(drop=True))
        return
    row = {"referencia": reference, "costo": str(value).strip()}
    if len(idx):
        df.loc[idx[0], ["referencia", "costo"]] = [row["referencia"], row["costo"]]
    else:
        df.loc[len(df)] = row
    save_costos(df.reset_index(drop=True))


def get_cost(reference: str) -> str:
    df = get_costos()
    match = df[df["referencia"].astype(str).str.upper() == str(reference).strip().upper()]
    return "" if match.empty else str(match.iloc[0]["costo"])


def document_path(kind: str, filename: str) -> Path | None:
    if kind not in UPLOAD_INFO or not filename or filename in {".", ".."}:
        return None
    if any(c in filename for c in ("/", "\\", ":", "\x00")):
        return None
    folder = UPLOAD_INFO[kind]["folder"].resolve()
    path = folder / filename
    try:
        if not path.resolve().is_relative_to(folder):
            return None
    except (ValueError, OSError):
        return None
    return path


def valid_code(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,119}", value))


def file_exists(kind: str, filename: str) -> bool:
    path = document_path(kind, filename)
    return bool(path and path.is_file())


def delete_reference_files(row: dict) -> None:
    for kind in UPLOAD_INFO:
        path = document_path(kind, str(row.get(kind, "")).strip())
        if path:
            path.unlink(missing_ok=True)


def validate_and_save_upload(reference_code: str, kind: str, storage, existing_filename: str = "") -> str:
    if storage is None or not storage.filename:
        return existing_filename
    safe_name = secure_filename(storage.filename)
    ext = Path(safe_name).suffix.lower()
    if not valid_code(reference_code):
        raise ValueError("Referencia no válida. Use letras, números, guiones o puntos, sin espacios.")
    if ext not in UPLOAD_INFO[kind]["exts"]:
        raise ValueError(f"Archivo inválido para {UPLOAD_INFO[kind]['label']}")
    if Path(safe_name).stem.upper() != reference_code.upper():
        raise ValueError(f"El nombre del archivo de {UPLOAD_INFO[kind]['label']} debe ser exactamente {reference_code}{ext}")
    new_name = f"{reference_code}{ext}"
    target = document_path(kind, new_name)
    if target is None:
        raise ValueError("Nombre de archivo no válido.")
    fd, name = tempfile.mkstemp(prefix=".upload_", dir=target.parent)
    os.close(fd)
    temp = Path(name)
    try:
        storage.save(temp)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    if existing_filename and existing_filename != new_name:
        old = document_path(kind, existing_filename)
        if old:
            old.unlink(missing_ok=True)
    return new_name


def references_for_equipo(equipo_codigo: str) -> List[dict]:
    refs = get_referencias()
    if equipo_codigo:
        refs = refs[refs["equipo_codigo"].astype(str) == str(equipo_codigo)]
    refs = refs.sort_values("referencia_codigo")
    costs = {str(r["referencia"]).upper(): str(r["costo"]) for _, r in get_costos().iterrows()}
    result = []
    for _, row in refs.iterrows():
        reference = str(row["referencia_codigo"])
        result.append(
            {
                "referencia_codigo": reference,
                "equipo_codigo": str(row["equipo_codigo"]),
                "equipo_nombre": str(row["equipo_nombre"]),
                "selecciones": parse_json_list(row["selecciones_json"]),
                "planos": str(row["planos"]),
                "modelo3d": str(row["modelo3d"]),
                "lista_materiales": str(row["lista_materiales"]),
                "ficha_tecnica": str(row["ficha_tecnica"]),
                "costo": costs.get(reference.upper(), ""),
                "preview_url": url_for("biblioteca.uploaded_file", kind="planos", filename=str(row["planos"])) if row["planos"] else "",
                "has_planos": file_exists("planos", str(row["planos"])),
                "has_modelo3d": file_exists("modelo3d", str(row["modelo3d"])),
                "has_lista_materiales": file_exists("lista_materiales", str(row["lista_materiales"])),
                "has_ficha_tecnica": file_exists("ficha_tecnica", str(row["ficha_tecnica"])),
            }
        )
    return result


def selected_reference_record(reference_code: str, equipo_codigo: str = "") -> dict | None:
    refs = references_for_equipo(equipo_codigo)
    for row in refs:
        if row["referencia_codigo"] == reference_code:
            return row
    return None


def build_search_options(equipo_codigo: str) -> List[dict]:
    chars = chars_for_equipo(equipo_codigo)
    refs = references_for_equipo(equipo_codigo)
    for char in chars:
        options = []
        for sub in char["subcaracteristicas"]:
            code = str(sub.get("codigo", "")).strip().upper()
            count = 0
            for ref in refs:
                sels = {str(x.get("orden")): str(x.get("codigo", "")).strip().upper() for x in ref["selecciones"]}
                if sels.get(char["orden"], "") == code:
                    count += 1
            options.append(
                {
                    "codigo": code,
                    "texto": str(sub.get("texto", "")),
                    "enabled": count > 0,
                }
            )
        char["subcaracteristicas"] = options
    return chars


def all_options_map(equipo_codigo: str) -> dict:
    chars = chars_for_equipo(equipo_codigo)
    return {
        c["orden"]: [
            {"codigo": str(s.get("codigo", "")).strip().upper(), "texto": str(s.get("texto", ""))}
            for s in c["subcaracteristicas"]
        ]
        for c in chars
    }


@biblioteca_bp.context_processor
def inject_helpers():
    return {
        "format_money": format_money,
        "upload_accept": {k: v["accept"] for k, v in UPLOAD_INFO.items()},
        "color_class": lambda name: {
            "green": "soft-green",
            "pink": "soft-pink",
            "purple": "soft-purple",
            "orange": "soft-orange",
            "blue": "soft-blue",
        "yellow": "soft-yellow",
        "red": "soft-red",
        "gray": "soft-gray",
        }.get(str(name).lower(), "soft-green"),
    }


@biblioteca_bp.route("")
@biblioteca_bp.route("/")
def home_redirect():
    return redirect(url_for("biblioteca.equipos"))


@biblioteca_bp.route("/equipos")
def equipos():
    equipos = get_equipos().sort_values("item")
    q_equipo = str(request.args.get("q_equipo", "")).strip().lower()
    if q_equipo:
        equipos = equipos[
            equipos["codigo"].astype(str).str.lower().str.contains(q_equipo, regex=False)
            | equipos["nombre"].astype(str).str.lower().str.contains(q_equipo, regex=False)
        ]

    selected_code = str(request.args.get("equipo", "")).strip().upper()
    all_equips = get_equipos().sort_values("item")
    selected_equipo = get_equipo_row(selected_code)
    if selected_equipo is None and not all_equips.empty:
        selected_equipo = all_equips.iloc[0].to_dict()
        selected_code = str(selected_equipo["codigo"])

    chars = chars_for_equipo(selected_code)
    selected_map = {}
    for c in chars:
        selected_map[c["orden"]] = str(request.args.get(f"sel_{c['orden']}", "")).strip().upper()
        if not selected_map[c["orden"]] and c["subcaracteristicas"]:
            selected_map[c["orden"]] = str(c["subcaracteristicas"][0].get("codigo", "")).strip().upper()

    generated_ref = build_reference_code(selected_code, selected_map, chars) if selected_code else ""
    selected_ref = selected_reference_record(generated_ref, selected_code) if generated_ref else None

    referencias = references_for_equipo(selected_code)
    q_ref = str(request.args.get("q_ref", "")).strip().lower()
    if q_ref:
        referencias = [r for r in referencias if q_ref in r["referencia_codigo"].lower()]

    return render_template(
        "biblioteca/biblioteca.html",
        current_page="biblioteca",
        equipos=equipos.to_dict(orient="records"),
        selected_equipo=selected_equipo,
        chars=chars,
        selected_map=selected_map,
        generated_ref=generated_ref,
        selected_ref=selected_ref,
        referencias=referencias,
        q_equipo=q_equipo,
        q_ref=q_ref,
    )


@biblioteca_bp.post("/buscar_referencia")
def buscar_referencia():
    equipo = str(request.form.get("equipo_codigo", "")).strip().upper()
    chars = chars_for_equipo(equipo)
    args = {"equipo": equipo}
    for c in chars:
        args[f"sel_{c['orden']}"] = str(request.form.get(f"subchoice_{c['orden']}", "")).strip().upper()
    return redirect(url_for("biblioteca.equipos", **args))


@biblioteca_bp.route("/buscador")
def buscador():
    equipos_df = get_equipos().sort_values("item")
    selected_code = str(request.args.get("equipo", "")).strip().upper()
    selected_equipo = get_equipo_row(selected_code)
    if selected_equipo is None and not equipos_df.empty:
        selected_equipo = equipos_df.iloc[0].to_dict()
        selected_code = str(selected_equipo["codigo"])

    chars = build_search_options(selected_code)
    all_options = all_options_map(selected_code)
    selected_map = {}
    for c in chars:
        selected_map[c["orden"]] = str(request.args.get(f"sel_{c['orden']}", "")).strip().upper()

    all_refs = references_for_equipo(selected_code)
    current_refs = all_refs
    for orden, value in selected_map.items():
        if value:
            current_refs = [
                r for r in current_refs
                if any(str(s.get("orden")) == orden and str(s.get("codigo", "")).strip().upper() == value for s in r["selecciones"])
            ]

    selected_ref_code = str(request.args.get("ref", "")).strip().upper()
    selected_ref = None
    if selected_ref_code:
        selected_ref = next((r for r in all_refs if r["referencia_codigo"] == selected_ref_code), None)
    if selected_ref is None and len(current_refs) == 1:
        selected_ref = current_refs[0]

    return render_template(
        "biblioteca/buscador.html",
        current_page="buscador",
        equipos=equipos_df.to_dict(orient="records"),
        selected_equipo=selected_equipo,
        chars=chars,
        selected_map=selected_map,
        referencias=all_refs,
        filtered_refs=current_refs,
        selected_ref=selected_ref,
        all_options=all_options,
        refs_json=json.dumps(all_refs, ensure_ascii=False),
    )


@biblioteca_bp.route("/costos", methods=["GET", "POST"])
def costos():
    if request.method == "POST":
        f = request.files.get("archivo_costos")
        if not f or not f.filename:
            flash("Debe seleccionar un archivo Excel.", "error")
            return redirect(url_for("biblioteca.costos"))
        if Path(secure_filename(f.filename)).suffix.lower() not in {".xlsx", ".xlsm"}:
            flash("Solo se permiten archivos Excel .xlsx o .xlsm.", "error")
            return redirect(url_for("biblioteca.costos"))
        try:
            df = pd.read_excel(f)
            if "referencia" not in df.columns or "costo" not in df.columns:
                flash("El Excel debe tener columnas referencia y costo. No se modificaron los costos.", "error")
                return redirect(url_for("biblioteca.costos"))
            df = df[["referencia", "costo"]].fillna("")
            df["referencia"] = df["referencia"].astype(str).str.strip().str.upper()
            df["costo"] = df["costo"].astype(str).str.strip()
            df = df[df["referencia"] != ""]
        except Exception:
            flash("No fue posible leer el Excel. Verifique que sea un archivo válido y no esté protegido.", "error")
            return redirect(url_for("biblioteca.costos"))
        save_costos(df.reset_index(drop=True))
        flash("Costos cargados correctamente.", "success")
        return redirect(url_for("biblioteca.costos"))
    return render_template("biblioteca/costos.html", current_page="costos", cost_count=len(get_costos()))


@biblioteca_bp.post("/equipos/create")
def create_equipo():
    codigo = str(request.form.get("codigo", "")).strip().upper()
    nombre = str(request.form.get("nombre", "")).strip().upper()
    if not valid_code(codigo) or not nombre:
        flash("Debe diligenciar código y nombre.", "error")
        return redirect(url_for("biblioteca.equipos"))
    equipos = get_equipos()
    dup = equipos[(equipos["codigo"].astype(str) == codigo) | (equipos["nombre"].astype(str) == nombre)]
    if not dup.empty:
        flash("El código o nombre del equipo ya existe.", "error")
        return redirect(url_for("biblioteca.equipos"))
    equipos.loc[len(equipos)] = [next_item(), codigo, nombre]
    save_equipos(equipos)
    flash("Equipo creado correctamente.", "success")
    return redirect(url_for("biblioteca.equipos", equipo=codigo))


@biblioteca_bp.post("/equipos/update/<codigo>")
def update_equipo(codigo):
    nuevo_codigo = str(request.form.get("codigo", "")).strip().upper()
    nuevo_nombre = str(request.form.get("nombre", "")).strip().upper()
    if not valid_code(nuevo_codigo) or not nuevo_nombre:
        flash("Debe diligenciar un código válido y un nombre.", "error")
        return redirect(url_for("biblioteca.equipos", equipo=codigo))
    equipos = get_equipos()
    idx = equipos[equipos["codigo"].astype(str) == str(codigo)].index
    if len(idx) == 0:
        flash("Equipo no encontrado.", "error")
        return redirect(url_for("biblioteca.equipos"))
    others = equipos[equipos["codigo"].astype(str) != str(codigo)]
    if not others[(others["codigo"].astype(str) == nuevo_codigo) | (others["nombre"].astype(str) == nuevo_nombre)].empty:
        flash("El código o nombre del equipo ya existe.", "error")
        return redirect(url_for("biblioteca.equipos", equipo=codigo))
    equipos.loc[idx, ["codigo", "nombre"]] = [nuevo_codigo, nuevo_nombre]
    save_equipos(equipos)

    chars = get_caracteristicas()
    chars.loc[chars["equipo_codigo"].astype(str) == str(codigo), "equipo_codigo"] = nuevo_codigo
    save_caracteristicas(chars)

    refs = get_referencias()
    refs.loc[refs["equipo_codigo"].astype(str) == str(codigo), ["equipo_codigo", "equipo_nombre"]] = [nuevo_codigo, nuevo_nombre]
    save_referencias(refs)
    flash("Equipo actualizado correctamente.", "success")
    return redirect(url_for("biblioteca.equipos", equipo=nuevo_codigo))


@biblioteca_bp.post("/equipos/delete/<codigo>")
def delete_equipo(codigo):
    refs = get_referencias()
    if not refs[refs["equipo_codigo"].astype(str) == str(codigo)].empty:
        flash("No se puede eliminar un equipo con referencias creadas.", "error")
        return redirect(url_for("biblioteca.equipos", equipo=codigo))
    equipos = get_equipos()
    equipos = equipos[equipos["codigo"].astype(str) != str(codigo)]
    save_equipos(equipos.reset_index(drop=True))
    chars = get_caracteristicas()
    chars = chars[chars["equipo_codigo"].astype(str) != str(codigo)]
    save_caracteristicas(chars.reset_index(drop=True))
    flash("Equipo eliminado correctamente.", "success")
    return redirect(url_for("biblioteca.equipos"))


@biblioteca_bp.post("/caracteristicas/create")
def create_caracteristica():
    equipo_codigo = str(request.form.get("equipo_codigo", "")).strip().upper()
    orden = str(request.form.get("orden", "")).strip().upper()
    nombre = str(request.form.get("nombre", "")).strip().upper()
    grupo_color = str(request.form.get("grupo_color", "green")).strip().lower()
    subs = parse_sub_rows(request.form)
    if not equipo_codigo or not orden or not nombre:
        flash("Debe diligenciar equipo, orden y nombre de la característica.", "error")
        return redirect(url_for("biblioteca.equipos", equipo=equipo_codigo))
    if not subs:
        flash("Debe crear al menos una subcaracterística.", "error")
        return redirect(url_for("biblioteca.equipos", equipo=equipo_codigo))
    df = get_caracteristicas()
    exists = df[(df["equipo_codigo"].astype(str) == equipo_codigo) & (df["orden"].astype(str) == orden)]
    if not exists.empty:
        flash("Ya existe una característica con ese orden.", "error")
        return redirect(url_for("biblioteca.equipos", equipo=equipo_codigo))
    df.loc[len(df)] = [equipo_codigo, orden, nombre, grupo_color, json.dumps(subs, ensure_ascii=False)]
    save_caracteristicas(df)
    flash("Característica creada correctamente.", "success")
    return redirect(url_for("biblioteca.equipos", equipo=equipo_codigo))


@biblioteca_bp.post("/caracteristicas/update/<equipo_codigo>/<orden>")
def update_caracteristica(equipo_codigo, orden):
    df = get_caracteristicas()
    idx = df[(df["equipo_codigo"].astype(str) == str(equipo_codigo)) & (df["orden"].astype(str) == str(orden))].index
    if len(idx) == 0:
        flash("Característica no encontrada.", "error")
        return redirect(url_for("biblioteca.equipos", equipo=equipo_codigo))
    nombre = str(request.form.get("nombre", "")).strip().upper()
    grupo_color = str(request.form.get("grupo_color", "green")).strip().lower()
    subs = parse_sub_rows(request.form)
    if not subs:
        flash("Debe conservar al menos una subcaracterística.", "error")
        return redirect(url_for("biblioteca.equipos", equipo=equipo_codigo))
    df.loc[idx, ["nombre", "grupo_color", "subcaracteristicas_json"]] = [nombre, grupo_color, json.dumps(subs, ensure_ascii=False)]
    save_caracteristicas(df)
    flash("Característica actualizada correctamente.", "success")
    return redirect(url_for("biblioteca.equipos", equipo=equipo_codigo))


@biblioteca_bp.post("/caracteristicas/delete/<equipo_codigo>/<orden>")
def delete_caracteristica(equipo_codigo, orden):
    refs = references_for_equipo(equipo_codigo)
    if refs:
        flash("No se pueden eliminar características si el equipo ya tiene referencias creadas.", "error")
        return redirect(url_for("biblioteca.equipos", equipo=equipo_codigo))
    df = get_caracteristicas()
    df = df[~((df["equipo_codigo"].astype(str) == str(equipo_codigo)) & (df["orden"].astype(str) == str(orden)))]
    save_caracteristicas(df.reset_index(drop=True))
    flash("Característica eliminada correctamente.", "success")
    return redirect(url_for("biblioteca.equipos", equipo=equipo_codigo))


@biblioteca_bp.post("/referencias/create")
def create_referencia():
    referencia = str(request.form.get("referencia_codigo", "")).strip().upper()
    equipo_codigo = str(request.form.get("equipo_codigo", "")).strip().upper()
    equipo = get_equipo_row(equipo_codigo)
    if not equipo or not valid_code(referencia):
        flash("Seleccione un equipo existente y una referencia válida.", "error")
        return redirect(url_for("biblioteca.equipos", equipo=equipo_codigo))
    chars = chars_for_equipo(equipo_codigo)
    selecciones = []
    for c in chars:
        value = str(request.form.get(f"subchoice_{c['orden']}", "")).strip().upper()
        match = next((s for s in c["subcaracteristicas"] if str(s.get("codigo", "")).strip().upper() == value), None)
        if match:
            selecciones.append({"orden": c["orden"], "codigo": value, "texto": str(match.get("texto", ""))})
    refs = get_referencias()
    if not refs[refs["referencia_codigo"].astype(str) == referencia].empty:
        flash("La referencia ya existe.", "error")
        return redirect(url_for("biblioteca.equipos", equipo=equipo_codigo))
    row = {
        "referencia_codigo": referencia,
        "equipo_codigo": equipo_codigo,
        "equipo_nombre": equipo["nombre"] if equipo else "",
        "selecciones_json": json.dumps(selecciones, ensure_ascii=False),
        "planos": "",
        "modelo3d": "",
        "lista_materiales": "",
        "ficha_tecnica": "",
    }
    try:
        for kind in ["planos", "modelo3d", "lista_materiales", "ficha_tecnica"]:
            row[kind] = validate_and_save_upload(referencia, kind, request.files.get(kind), "")
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("biblioteca.equipos", equipo=equipo_codigo))
    refs.loc[len(refs)] = row
    save_referencias(refs)
    save_cost(referencia, request.form.get("costo", ""))
    flash("Referencia creada correctamente.", "success")
    args = {"equipo": equipo_codigo}
    for c in chars:
        args[f"sel_{c['orden']}"] = str(request.form.get(f"subchoice_{c['orden']}", "")).strip().upper()
    return redirect(url_for("biblioteca.equipos", **args))


@biblioteca_bp.post("/referencias/update/<referencia>")
def update_referencia(referencia):
    refs = get_referencias()
    idx = refs[refs["referencia_codigo"].astype(str) == str(referencia)].index
    if len(idx) == 0:
        flash("Referencia no encontrada.", "error")
        return redirect(url_for("biblioteca.equipos"))
    current = refs.iloc[idx[0]].to_dict()
    try:
        for kind in ["planos", "modelo3d", "lista_materiales", "ficha_tecnica"]:
            current[kind] = validate_and_save_upload(referencia, kind, request.files.get(kind), str(current.get(kind, "")))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("biblioteca.equipos", equipo=current["equipo_codigo"]))
    for kind in ["planos", "modelo3d", "lista_materiales", "ficha_tecnica"]:
        refs.loc[idx[0], kind] = current[kind]
    save_referencias(refs)
    save_cost(referencia, request.form.get("costo", ""))
    flash("Referencia actualizada correctamente.", "success")
    return redirect(url_for("biblioteca.equipos", equipo=current["equipo_codigo"]))


@biblioteca_bp.post("/referencias/delete/<referencia>")
def delete_referencia(referencia):
    refs = get_referencias()
    row_df = refs[refs["referencia_codigo"].astype(str) == str(referencia)]
    if row_df.empty:
        flash("Referencia no encontrada.", "error")
        return redirect(url_for("biblioteca.equipos"))
    row = row_df.iloc[0].to_dict()
    delete_reference_files(row)
    refs = refs[refs["referencia_codigo"].astype(str) != str(referencia)]
    save_referencias(refs.reset_index(drop=True))
    save_cost(referencia, "")
    flash("Referencia eliminada correctamente.", "success")
    return redirect(url_for("biblioteca.equipos", equipo=row["equipo_codigo"]))


@biblioteca_bp.route("/uploads/<kind>/<filename>")
def uploaded_file(kind, filename):
    path = document_path(kind, filename)
    if path is None or not path.is_file():
        abort(404, description="Archivo no encontrado.")
    return send_from_directory(path.parent, path.name, as_attachment=kind != "planos")


@biblioteca_bp.route("/download/<kind>/<filename>")
def download_file(kind, filename):
    path = document_path(kind, filename)
    if path is None or not path.is_file():
        abort(404, description="Archivo no encontrado.")
    return send_from_directory(path.parent, path.name, as_attachment=True)


_ICON_PATHS = {
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    "edit": '<path d="m15 5 4 4M4 20l4-1L20 7a2 2 0 0 0-4-4L4 15zM13 20h7"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 10v7M14 10v7"/>',
    "download": '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    "upload": '<path d="M12 16V4m-5 5 5-5 5 5M4 16v5h16v-5"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    "minus": '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
    "close": '<path d="m6 6 12 12M6 18 18 6"/>',
}


def biblio_icon(name: str, state: str = "") -> Markup:
    state = state if state in {"available", "unavailable"} else ""
    return Markup('<svg class="b-icon ' + state + '" viewBox="0 0 24 24" fill="none" '
                  'stroke="currentColor" stroke-width="1.65" stroke-linecap="round" '
                  'stroke-linejoin="round" aria-hidden="true">' + _ICON_PATHS.get(name, "") + '</svg>')


@biblioteca_bp.context_processor
def library_layout_context():
    return {"biblioteca_page": True, "biblio_icon": biblio_icon,
            "biblioteca_urls": {
                "equipos": url_for("biblioteca.equipos"),
                "buscador": url_for("biblioteca.buscador"),
                "buscarReferencia": url_for("biblioteca.buscar_referencia"),
                "editEquipo": url_for("biblioteca.update_equipo", codigo="__CODE__"),
                "editChar": url_for("biblioteca.update_caracteristica", equipo_codigo="__CODE__", orden="__ORDER__"),
                "editReferencia": url_for("biblioteca.update_referencia", referencia="__CODE__"),
                "download": url_for("biblioteca.download_file", kind="__KIND__", filename="__FILE__"),
            }}


@biblioteca_bp.before_request
def lock_library_storage():
    # A shared catalog; the parent app has already validated user/session/CSRF.
    _STORAGE_LOCK.acquire()
    g.biblioteca_storage_locked = True
    ensure_storage()


@biblioteca_bp.teardown_request
def unlock_library_storage(error=None):
    if g.pop("biblioteca_storage_locked", False):
        _STORAGE_LOCK.release()
