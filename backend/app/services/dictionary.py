"""Loads the configurable plastics terminology dictionary (app/data/material_dictionary.yaml).
An override file can be supplied with MATERIAL_DICTIONARY_PATH."""
import os
import re
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "material_dictionary.yaml"


@lru_cache
def get_dictionary() -> dict:
    path = Path(os.environ.get("MATERIAL_DICTIONARY_PATH", DEFAULT_PATH))
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


@lru_cache
def compiled() -> dict:
    d = get_dictionary()
    out = {}
    for section in ("polymers", "grades", "applications", "forms", "business_types", "intent"):
        out[section] = {k: _compile(v) for k, v in (d.get(section) or {}).items()}
    out["colours"] = re.compile(r"\b(" + "|".join(d.get("colours", [])) + r")\b", re.IGNORECASE)
    return out


def reload_dictionary() -> None:
    get_dictionary.cache_clear()
    compiled.cache_clear()
