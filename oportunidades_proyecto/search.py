from __future__ import annotations

import shlex
from typing import Iterable

from .db import SEARCH_FIELD_MAP


def parse_query(query: str) -> list[tuple[str | None, str]]:
    """Convierte texto libre y campo:valor en condiciones acumulativas.

    Ejemplos:
      azucar cliente:"Azucar Manuelita"
      estado:"En análisis" material:azucar
    """
    text = str(query or "").strip()
    if not text:
        return []
    try:
        parts = shlex.split(text, posix=True)
    except ValueError:
        parts = text.split()
    tokens: list[tuple[str | None, str]] = []
    for part in parts:
        if ":" in part:
            key, value = part.split(":", 1)
            normalized_key = key.strip().casefold().replace("-", "_")
            value = value.strip()
            if normalized_key in SEARCH_FIELD_MAP and value:
                tokens.append((normalized_key, value))
                continue
        if part.strip():
            tokens.append((None, part.strip()))
    return tokens


def query_help_fields() -> Iterable[str]:
    return (
        "cliente", "proyecto", "radicado", "estado", "responsable", "pais", "ciudad",
        "industria", "tipo", "subsistema", "proceso", "material", "flujo", "voltaje",
        "atex", "nec", "equipo", "entrada", "salida", "oferta", "imagen",
    )
