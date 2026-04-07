"""Bundled dataset JSON files for quality-test presets (e.g. osteon guide)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from gardener_gopedia.schemas import DatasetCreate

# Repo root: .../gardener_gopedia/dataset/presets.py -> parents[2] == project root
_REPO_ROOT: Final = Path(__file__).resolve().parent.parent.parent

# Preset key (API) -> path under repo dataset/
PRESET_JSON_PATHS: Final[dict[str, Path]] = {
    "osteon": _REPO_ROOT / "dataset" / "sample_osteon_guide_30_v2.json",
}


def list_quality_preset_names() -> list[str]:
    return sorted(PRESET_JSON_PATHS.keys())


def load_quality_preset(name: str) -> DatasetCreate:
    key = (name or "").strip().lower()
    path = PRESET_JSON_PATHS.get(key)
    if path is None:
        known = ", ".join(list_quality_preset_names()) or "(none)"
        raise FileNotFoundError(f"unknown quality_preset {name!r}; known: {known}")
    if not path.is_file():
        raise FileNotFoundError(f"preset file missing for {key!r}: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return DatasetCreate.model_validate(raw)
