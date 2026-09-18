"""Módulo compartido de capacitaciones en video."""

from .transcoder import ensure_worker_started
from .db import ensure_database

try:
    from .routes import bp
except ModuleNotFoundError as exc:  # facilita pruebas del motor sin Flask instalado
    if exc.name != "flask":
        raise
    bp = None

__all__ = ["bp", "ensure_worker_started", "ensure_database"]
