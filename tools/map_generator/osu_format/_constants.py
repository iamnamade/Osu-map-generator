from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def load_osu_interop_constants() -> dict[str, Any]:
    constants_path = Path(__file__).resolve().parents[3] / "src" / "shared" / "osuInteropConstants.json"
    with constants_path.open("r", encoding="utf-8") as handle:
        raw_data = json.load(handle)
    if not isinstance(raw_data, dict):
        raise ValueError("Shared osu interop constants must be a JSON object.")
    return raw_data
