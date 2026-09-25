from __future__ import annotations

import json
import shlex
from typing import Iterable

from .db import ADVANCED_FILTER_FIELD_MAP, SEARCH_FIELD_MAP


def parse_query(query: str) -> list[tuple[str | None, str]]:
    """Convierte texto libre y campo:valor en condiciones acumulativas.

    Ejemplos:
      azucar cliente:"Azucar Manuelita"
      material:azucar flujo:5000
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


def parse_advanced_filters(raw: str | None) -> list[dict[str, str]]:
    """Lee el parámetro URL ``f`` del constructor Clave -> Valor.

    Se aceptan como máximo 20 filtros válidos para evitar URLs o consultas
    accidentales excesivas. Los filtros inválidos se ignoran de forma segura.
    """
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    filters: list[dict[str, str]] = []
    for item in payload[:20]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        value = str(item.get("value") or "").strip()
        if key in ADVANCED_FILTER_FIELD_MAP and value:
            filters.append({"key": key, "value": value})
    return filters


def query_help_fields() -> Iterable[str]:
    # Compatibilidad con el buscador textual histórico campo:valor.
    return (
        "cliente", "proyecto", "responsable", "pais", "ciudad",
        "industria", "tipo", "subsistema", "proceso", "material", "flujo", "voltaje",
        "atex", "nec", "equipo", "entrada", "salida", "oferta", "imagen",
    )
