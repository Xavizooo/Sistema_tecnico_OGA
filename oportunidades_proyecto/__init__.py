"""Oportunidades de Proyecto (OD)."""

from .db import ensure_database

try:
    from .routes import bp
except ModuleNotFoundError as exc:
    if exc.name != "flask":
        raise
    bp = None

__all__ = ["bp", "ensure_database"]
