from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import venv

BASE = Path(__file__).resolve().parent
LOCAL_VENV = BASE / ".venv"
REQ = BASE / "requirements.txt"
APP = BASE / "app.py"


def python_in_venv(folder: Path) -> Path:
    if os.name == "nt":
        return folder / "Scripts" / "python.exe"
    return folder / "bin" / "python"


def has_dependencies(py: Path) -> bool:
    if not py.exists():
        return False
    try:
        result = subprocess.run(
            [str(py), "-c", "import flask, openpyxl, xlrd, fitz, argon2, waitress, pandas, holidays, imageio_ffmpeg"],
            cwd=str(BASE),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        return result.returncode == 0
    except Exception:
        return False


def find_ready_python() -> Path | None:
    # 1) Entorno local de esta revisión, si ya existe.
    local = python_in_venv(LOCAL_VENV)
    if has_dependencies(local):
        return local

    # 2) El Python con el que VS Code ejecutó este lanzador.
    current = Path(sys.executable)
    if has_dependencies(current):
        return current

    # 3) Reutiliza un entorno de una revisión anterior si ya contiene todo.
    parent = BASE.parent
    for name in ("GENERADOR_RQ_REV06", "GENERADOR_RQ_REV05", "GENERADOR_RQ_REV04", "GENERADOR_RQ_REV03", "GENERADOR_RQ_REV02"):
        candidate = python_in_venv(parent / name / ".venv")
        if has_dependencies(candidate):
            return candidate
    return None


def prepare_local_environment() -> Path:
    py = python_in_venv(LOCAL_VENV)
    if not py.exists():
        print("Preparando entorno local del GENERADOR DE RQ...", flush=True)
        venv.EnvBuilder(with_pip=True, clear=False).create(LOCAL_VENV)

    if not has_dependencies(py):
        print("Instalando dependencias dentro de .venv (solo para este programa)...", flush=True)
        try:
            subprocess.check_call(
                [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQ)],
                cwd=str(BASE),
            )
        except subprocess.CalledProcessError:
            print("\nNo fue posible instalar las dependencias automáticamente.")
            print("Verifique que el computador tenga acceso a Internet y vuelva a presionar F5.")
            raise
    return py


def main() -> int:
    py = find_ready_python() or prepare_local_environment()
    print("Iniciando OGA - REV 17 - RQ / PLANOS / BIBLIOTECA / PROYECTOS DISENO / CAPACITACIONES...", flush=True)
    return subprocess.call([str(py), str(APP)], cwd=str(BASE))


if __name__ == "__main__":
    raise SystemExit(main())
