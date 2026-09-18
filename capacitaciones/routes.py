from __future__ import annotations

from functools import wraps
from pathlib import Path
import os
import shutil
import uuid

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, send_file, send_from_directory, url_for
from werkzeug.utils import secure_filename

from auth_store import audit_event
from .db import (
    DATA_DIR, MEDIA_DIR, ORIGINALS_DIR,
    STATUS_ERROR, STATUS_PENDING, STATUS_PROCESSING, STATUS_READY,
    create_video, get_video, list_videos, soft_delete, stats,
)
from .transcoder import cancel, enqueue, retry, worker_state

bp = Blueprint("capacitaciones", __name__, url_prefix="/capacitaciones")

MAX_VIDEO_MB = max(50, min(int(os.environ.get("OGA_MAX_VIDEO_MB", "2048")), 8192))
MAX_VIDEO_BYTES = MAX_VIDEO_MB * 1024 * 1024


def _admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = getattr(g, "current_user", None)
        if not user or not user.get("is_admin"):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def _user_dict() -> dict:
    user = getattr(g, "current_user", None) or {}
    return dict(user)


def _client_ip() -> str:
    return request.remote_addr or "DESCONOCIDA"


def _looks_like_mp4(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            header = fh.read(64)
        return len(header) >= 12 and b"ftyp" in header[4:32]
    except Exception:
        return False


def _relative(path: Path) -> str:
    return str(path.relative_to(DATA_DIR)).replace("\\", "/")


def _absolute_from_rel(rel: str | None) -> Path | None:
    if not rel:
        return None
    candidate = (DATA_DIR / rel).resolve()
    root = DATA_DIR.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


@bp.get("/")
def index():
    return render_template(
        "capacitaciones/index.html",
        videos=list_videos(),
        video_stats=stats(),
        worker=worker_state(),
        max_video_mb=MAX_VIDEO_MB,
        capacitaciones_page=True,
    )


@bp.post("/subir")
def upload():
    if request.content_length and request.content_length > MAX_VIDEO_BYTES + 2 * 1024 * 1024:
        flash(f"El archivo supera el máximo permitido de {MAX_VIDEO_MB} MB.", "error")
        return redirect(url_for("capacitaciones.index") + "#subir")

    nombre = (request.form.get("nombre") or "").strip()
    descripcion = (request.form.get("descripcion") or "").strip()
    file = request.files.get("video")
    if not nombre or len(nombre) > 120:
        flash("Ingrese un nombre de hasta 120 caracteres.", "error")
        return redirect(url_for("capacitaciones.index") + "#subir")
    if len(descripcion) > 600:
        flash("La descripción puede tener máximo 600 caracteres.", "error")
        return redirect(url_for("capacitaciones.index") + "#subir")
    if not file or not file.filename:
        flash("Seleccione un archivo MP4.", "error")
        return redirect(url_for("capacitaciones.index") + "#subir")

    original_name = secure_filename(Path(file.filename).name) or "video.mp4"
    if Path(original_name).suffix.lower() != ".mp4":
        flash("Solo se permiten videos en formato MP4.", "error")
        return redirect(url_for("capacitaciones.index") + "#subir")

    video_id = uuid.uuid4().hex
    target = ORIGINALS_DIR / f"{video_id}.mp4"
    try:
        file.save(target)
        size = target.stat().st_size
        if size <= 0:
            raise ValueError("El archivo está vacío.")
        if size > MAX_VIDEO_BYTES:
            raise ValueError(f"El archivo supera el máximo permitido de {MAX_VIDEO_MB} MB.")
        if not _looks_like_mp4(target):
            raise ValueError("El archivo no parece ser un MP4 válido.")

        user = _user_dict()
        create_video({
            "id": video_id,
            "nombre": nombre,
            "descripcion": descripcion,
            "archivo_original": original_name,
            "ruta_original": _relative(target),
            "tamano_origen": size,
            "subido_por_id": user.get("id"),
            "subido_por_usuario": user.get("username"),
            "subido_por_nombre": user.get("name"),
        })
        enqueue(video_id)
        audit_event("SUBIR VIDEO", "CAPACITACIONES", f"{nombre} · {original_name}", "OK", user, _client_ip())
        g.audit_logged = True
        flash("Video cargado. La transcodificación continuará en segundo plano.", "ok")
        return redirect(url_for("capacitaciones.detail", video_id=video_id))
    except Exception as exc:
        target.unlink(missing_ok=True)
        try:
            audit_event("SUBIR VIDEO", "CAPACITACIONES", f"{nombre or original_name} · {exc}", "ERROR", _user_dict(), _client_ip())
            g.audit_logged = True
        except Exception:
            pass
        flash(str(exc), "error")
        return redirect(url_for("capacitaciones.index") + "#subir")


@bp.get("/<video_id>")
def detail(video_id: str):
    video = get_video(video_id)
    if not video:
        abort(404)
    return render_template(
        "capacitaciones/detail.html",
        video=video,
        capacitaciones_page=True,
    )


@bp.get("/api/<video_id>/estado")
def status(video_id: str):
    video = get_video(video_id)
    if not video:
        return jsonify({"ok": False, "error": "Video no encontrado"}), 404
    return jsonify({
        "ok": True,
        "id": video["id"],
        "estado": video["estado"],
        "progreso": int(video.get("progreso") or 0),
        "error": video.get("error") or "",
        "listo": video["estado"] == STATUS_READY,
    })


@bp.get("/media/<video_id>/video.mp4")
def media_mp4(video_id: str):
    video = get_video(video_id)
    if not video or video.get("estado") != STATUS_READY:
        abort(404)
    path = _absolute_from_rel(video.get("ruta_mp4"))
    if not path or not path.exists():
        abort(404)
    response = send_file(path, mimetype="video/mp4", conditional=True)
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@bp.get("/media/<video_id>/poster.jpg")
def poster(video_id: str):
    video = get_video(video_id)
    if not video:
        abort(404)
    path = _absolute_from_rel(video.get("ruta_poster"))
    if not path or not path.exists():
        abort(404)
    response = send_file(path, mimetype="image/jpeg", conditional=True)
    response.headers["Cache-Control"] = "private, max-age=86400"
    return response


@bp.get("/media/<video_id>/hls/<path:filename>")
def hls(video_id: str, filename: str):
    video = get_video(video_id)
    if not video or video.get("estado") != STATUS_READY:
        abort(404)
    if Path(filename).name != filename or Path(filename).suffix.lower() not in {".m3u8", ".ts"}:
        abort(404)
    folder = MEDIA_DIR / video_id
    if not folder.exists():
        abort(404)
    mimetype = "application/vnd.apple.mpegurl" if filename.endswith(".m3u8") else "video/mp2t"
    response = send_from_directory(folder, filename, mimetype=mimetype, conditional=True)
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@bp.post("/<video_id>/eliminar")
@_admin_required
def delete(video_id: str):
    video = get_video(video_id)
    if not video:
        abort(404)
    user = _user_dict()
    cancel(video_id)
    soft_delete(video_id, user)
    original = _absolute_from_rel(video.get("ruta_original"))
    if original:
        original.unlink(missing_ok=True)
    shutil.rmtree(MEDIA_DIR / video_id, ignore_errors=True)
    shutil.rmtree(MEDIA_DIR / f".{video_id}.procesando", ignore_errors=True)
    audit_event("ELIMINAR VIDEO", "CAPACITACIONES", video.get("nombre") or video_id, "OK", user, _client_ip())
    g.audit_logged = True
    flash("Video eliminado.", "ok")
    return redirect(url_for("capacitaciones.index"))


@bp.post("/<video_id>/reintentar")
@_admin_required
def retry_video(video_id: str):
    video = get_video(video_id)
    if not video:
        abort(404)
    if video.get("estado") != STATUS_ERROR:
        flash("Solo se pueden reintentar videos con error.", "error")
    elif retry(video_id):
        flash("El video volvió a la cola de procesamiento.", "ok")
    else:
        flash("No fue posible reintentar: el MP4 original ya no está disponible.", "error")
    return redirect(url_for("capacitaciones.detail", video_id=video_id))
