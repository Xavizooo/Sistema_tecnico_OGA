from __future__ import annotations

from pathlib import Path
from queue import Queue, Empty
import os
import re
import shutil
import subprocess
import threading
import time
from typing import Any

from .db import (
    BASE_DIR, DATA_DIR, MEDIA_DIR, ORIGINALS_DIR,
    STATUS_DELETED, STATUS_PENDING,
    ensure_database, get_video, mark_error, mark_pending, mark_processing,
    mark_ready, pending_video_ids, update_video,
)

_QUEUE: Queue[str] = Queue()
_QUEUED: set[str] = set()
_RUNNING: dict[str, subprocess.Popen] = {}
_LOCK = threading.RLock()
_STARTED = False
_WORKERS: list[threading.Thread] = []

DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
VIDEO_SIZE_RE = re.compile(r"Video:.*?(\d{2,5})x(\d{2,5})(?:[\s,])")


def _creationflags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))


def ffmpeg_executable() -> str:
    candidates = [
        BASE_DIR / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
        BASE_DIR / "tools" / "ffmpeg" / "ffmpeg.exe",
        BASE_DIR / "tools" / "ffmpeg" / "bin" / "ffmpeg",
        BASE_DIR / "tools" / "ffmpeg" / "ffmpeg",
    ]
    for item in candidates:
        if item.exists():
            return str(item)
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError(
            "FFmpeg no está disponible. Ejecute nuevamente INICIAR.py con acceso a Internet para instalar imageio-ffmpeg."
        ) from exc


def _probe(input_file: Path) -> tuple[float | None, int | None, int | None]:
    ffmpeg = ffmpeg_executable()
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(input_file)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=45,
        creationflags=_creationflags(),
    )
    text = proc.stderr or ""
    duration = None
    width = height = None
    match = DURATION_RE.search(text)
    if match:
        duration = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    match = VIDEO_SIZE_RE.search(text)
    if match:
        width, height = int(match.group(1)), int(match.group(2))
    return duration, width, height


def _run_with_progress(video_id: str, cmd: list[str], duration: float | None, start_pct: int, end_pct: int) -> None:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        bufsize=1,
        creationflags=_creationflags(),
    )
    with _LOCK:
        _RUNNING[video_id] = proc
    last_update = 0.0
    last_pct = start_pct
    stderr_lines: list[str] = []

    def collect_stderr():
        if proc.stderr is None:
            return
        for line in proc.stderr:
            if line:
                stderr_lines.append(line.rstrip())
                if len(stderr_lines) > 80:
                    del stderr_lines[:-80]

    stderr_thread = threading.Thread(target=collect_stderr, daemon=True)
    stderr_thread.start()
    try:
        if proc.stdout is not None:
            for raw in proc.stdout:
                line = raw.strip()
                if line.startswith("out_time_ms=") and duration and duration > 0:
                    try:
                        seconds = int(line.split("=", 1)[1]) / 1_000_000.0
                        ratio = max(0.0, min(seconds / duration, 1.0))
                        pct = int(start_pct + (end_pct - start_pct) * ratio)
                    except Exception:
                        pct = last_pct
                    now = time.monotonic()
                    if pct > last_pct and (now - last_update > 0.7 or pct >= end_pct):
                        update_video(video_id, progreso=pct)
                        last_update = now
                        last_pct = pct
                current = get_video(video_id, include_deleted=True)
                if current and current.get("estado") == STATUS_DELETED:
                    proc.terminate()
                    raise RuntimeError("Procesamiento cancelado porque el video fue eliminado.")
        code = proc.wait()
        stderr_thread.join(timeout=1)
        if code != 0:
            detail = "\n".join(stderr_lines[-16:]).strip()
            raise RuntimeError(detail or f"FFmpeg terminó con código {code}")
    finally:
        with _LOCK:
            _RUNNING.pop(video_id, None)


def _safe_rel(path: Path) -> str:
    return str(path.relative_to(DATA_DIR)).replace("\\", "/")


def _output_size(folder: Path) -> int:
    total = 0
    if folder.exists():
        for item in folder.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
    return total


def _transcode(video_id: str) -> None:
    video = get_video(video_id, include_deleted=True)
    if not video or video.get("estado") == STATUS_DELETED:
        return
    original_rel = video.get("ruta_original")
    if not original_rel:
        mark_error(video_id, "No se encontró la ruta del MP4 original.")
        return
    source = DATA_DIR / original_rel
    if not source.exists():
        mark_error(video_id, "El archivo MP4 original ya no existe.")
        return

    output_dir = MEDIA_DIR / video_id
    temp_dir = MEDIA_DIR / f".{video_id}.procesando"
    shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    playback = temp_dir / "video.mp4"
    playlist = temp_dir / "stream.m3u8"
    poster = temp_dir / "poster.jpg"

    try:
        duration, width, height = _probe(source)
        mark_processing(video_id, duration=duration, width=width, height=height)
        ffmpeg = ffmpeg_executable()

        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
            "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-maxrate", "3000k", "-bufsize", "6000k",
            "-threads", str(max(1, min(int(os.environ.get("OGA_VIDEO_FFMPEG_THREADS", "2")), 4))),
        ]
        if height and height > 720:
            cmd += ["-vf", "scale=-2:720"]
        cmd += [
            "-force_key_frames", "expr:gte(t,n_forced*6)",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2",
            "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats",
            str(playback),
        ]
        _run_with_progress(video_id, cmd, duration, 2, 88)
        update_video(video_id, progreso=90)

        hls_cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
            "-i", str(playback),
            "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
            "-hls_time", "6", "-hls_playlist_type", "vod",
            "-hls_flags", "independent_segments",
            "-hls_segment_filename", str(temp_dir / "segment_%05d.ts"),
            str(playlist),
        ]
        _run_with_progress(video_id, hls_cmd, duration, 90, 97)

        try:
            shot_at = 1.0 if not duration else max(0.1, min(2.0, duration * 0.15))
            subprocess.run(
                [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", f"{shot_at:.2f}", "-i", str(playback),
                    "-frames:v", "1", "-vf", "scale=640:-2", str(poster),
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90,
                creationflags=_creationflags(),
            )
        except Exception:
            pass

        current = get_video(video_id, include_deleted=True)
        if not current or current.get("estado") == STATUS_DELETED:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return

        shutil.rmtree(output_dir, ignore_errors=True)
        temp_dir.replace(output_dir)
        playback_final = output_dir / "video.mp4"
        playlist_final = output_dir / "stream.m3u8"
        poster_final = output_dir / "poster.jpg"
        mark_ready(
            video_id,
            mp4_rel=_safe_rel(playback_final),
            hls_rel=_safe_rel(playlist_final),
            poster_rel=_safe_rel(poster_final) if poster_final.exists() else None,
            output_size=_output_size(output_dir),
        )
        # El original deja de ser necesario una vez existe la versión optimizada.
        # Esto evita duplicar el consumo de disco del servidor.
        try:
            source.unlink(missing_ok=True)
            update_video(video_id, ruta_original=None)
        except Exception:
            pass
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        current = get_video(video_id, include_deleted=True)
        if current and current.get("estado") != STATUS_DELETED:
            mark_error(video_id, str(exc))


def _worker_loop(worker_number: int) -> None:
    while True:
        try:
            video_id = _QUEUE.get(timeout=1)
        except Empty:
            continue
        try:
            with _LOCK:
                _QUEUED.discard(video_id)
            video = get_video(video_id, include_deleted=True)
            if video and video.get("estado") == STATUS_PENDING:
                _transcode(video_id)
        finally:
            _QUEUE.task_done()


def enqueue(video_id: str) -> bool:
    with _LOCK:
        if video_id in _QUEUED or video_id in _RUNNING:
            return False
        video = get_video(video_id, include_deleted=True)
        if not video or video.get("estado") != STATUS_PENDING:
            return False
        _QUEUED.add(video_id)
        _QUEUE.put(video_id)
        return True


def cancel(video_id: str) -> None:
    with _LOCK:
        proc = _RUNNING.get(video_id)
    if proc and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass


def retry(video_id: str) -> bool:
    video = get_video(video_id, include_deleted=True)
    if not video or video.get("estado") == STATUS_DELETED:
        return False
    if not video.get("ruta_original") or not (DATA_DIR / video["ruta_original"]).exists():
        return False
    mark_pending(video_id)
    return enqueue(video_id)


def worker_state() -> dict[str, Any]:
    with _LOCK:
        return {
            "workers": len(_WORKERS),
            "queued": len(_QUEUED),
            "running": list(_RUNNING.keys()),
        }


def ensure_worker_started() -> None:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return
        ensure_database()
        workers = max(1, min(int(os.environ.get("OGA_VIDEO_WORKERS", "1")), 2))
        _STARTED = True
        for number in range(workers):
            thread = threading.Thread(
                target=_worker_loop,
                args=(number + 1,),
                name=f"capacitaciones-transcoder-{number + 1}",
                daemon=True,
            )
            _WORKERS.append(thread)
            thread.start()
    for video_id in pending_video_ids():
        enqueue(video_id)
