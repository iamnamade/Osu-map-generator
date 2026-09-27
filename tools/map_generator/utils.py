from __future__ import annotations

import json
import math
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Iterable, List


class MapGeneratorError(Exception):
    """Readable user-facing failure for analysis and generation commands."""


def ensure_existing_file(path: Path, label: str) -> Path:
    if not path.exists():
        raise MapGeneratorError(f"{label} does not exist: {path}")

    if not path.is_file():
        raise MapGeneratorError(f"{label} is not a file: {path}")

    return path


def ensure_parent_directory(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise MapGeneratorError(
            f"Output directory could not be created for {path}: {error}"
        ) from error


def write_json(path: Path, data: dict[str, Any]) -> None:
    ensure_parent_directory(path)
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")

    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_path, path)
    except OSError as error:
        raise MapGeneratorError(f"Could not write JSON output to {path}: {error}") from error
    finally:
        if temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass


def copy_file(path: Path, destination: Path) -> None:
    ensure_parent_directory(destination)

    try:
        shutil.copyfile(path, destination)
    except OSError as error:
        raise MapGeneratorError(f"Could not copy {path} to {destination}: {error}") from error


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def round_ms(seconds: float) -> int:
    return int(round(seconds * 1000))


def average(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def is_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def format_seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.1f}"


def derive_browser_audio_path(audio_path: Path, project_root: Path) -> str:
    public_root = (project_root / "public").resolve()
    resolved_audio_path = audio_path.resolve()

    try:
        relative_path = resolved_audio_path.relative_to(public_root)
    except ValueError as error:
        raise MapGeneratorError(
            f"Audio path must be inside the project's public directory: {audio_path}"
        ) from error

    browser_path = "/" + relative_path.as_posix()

    if not browser_path.startswith("/"):
        raise MapGeneratorError(f"Derived browser audio path is invalid: {browser_path}")

    return browser_path


def resolve_browser_audio_path(
    *,
    audio_source_path: Path,
    project_root: Path,
    audio_browser_path_override: str | None = None,
) -> str:
    browser_path = (
        audio_browser_path_override
        if audio_browser_path_override is not None
        else derive_browser_audio_path(audio_source_path, project_root)
    )
    normalized = browser_path.strip()
    if not normalized:
        raise MapGeneratorError("Audio browser path must be a non-empty string.")
    if not normalized.startswith("/"):
        raise MapGeneratorError(f"Audio browser path must start with '/': {browser_path}")
    return normalized


def finite_number(value: float, label: str) -> float:
    if not math.isfinite(value):
        raise MapGeneratorError(f"{label} must be finite, received {value!r}.")

    return value


def shortest_angle_delta(left: float, right: float) -> float:
    delta = (right - left + math.pi) % (2 * math.pi) - math.pi
    return delta


def normalize_map_objects(objects: List[Any]) -> List[dict[str, Any]]:
    """Convert any candidate object list into standardised dictionaries.

    Handles plain dicts, objects with ``position`` sub-dicts, and class
    instances exposing ``x``, ``y``, ``time`` (or ``start_time``) attributes.
    Every returned dict contains at least ``{"id", "x", "y", "time", "type"}``
    with the numeric values cast to ``int`` / ``float``.
    """
    normalized: List[dict[str, Any]] = []
    if not isinstance(objects, list):
        return normalized
    for idx, item in enumerate(objects):
        if item is None:
            continue
        # --- coordinates ---
        x = _coerce_int(
            _cascade_value(item, ["x"], nested_key="position", nested_sub="x")
        )
        y = _coerce_int(
            _cascade_value(item, ["y"], nested_key="position", nested_sub="y")
        )
        # --- timing ---
        time_val = _coerce_float(
            _cascade_value(item, ["time", "start_time"], nested_key="timing", nested_sub="time")
        )
        # --- id ---
        raw_id = _cascade_value(item, ["id"], nested_key=None, nested_sub=None)
        obj_id = str(raw_id) if raw_id is not None else f"obj_{idx}"
        # --- type ---
        raw_type = _cascade_value(item, ["type"], nested_key=None, nested_sub=None)
        obj_type = str(raw_type) if raw_type is not None else "circle"
        normalized.append({
            "id": obj_id,
            "x": x,
            "y": y,
            "time": time_val,
            "type": obj_type,
        })
    return normalized


def _cascade_value(
    item: Any,
    keys: list[str],
    nested_key: str | None = None,
    nested_sub: str | None = None,
) -> Any:
    """Resolve a value from a dict or object instance with fallback logic."""
    # 1) Direct key lookup (for dicts)
    if isinstance(item, dict):
        for key in keys:
            if key in item:
                return item[key]
        # 2) Nested dict fallback (e.g. item["position"]["x"])
        if nested_key and nested_sub and nested_key in item:
            nested = item[nested_key]
            if isinstance(nested, dict) and nested_sub in nested:
                return nested[nested_sub]
    # 3) Attribute fallback (for class instances / dataclasses)
    for key in keys:
        val = getattr(item, key, None)
        if val is not None:
            return val
    # 4) Nested attribute fallback
    if nested_key and nested_sub:
        nested_obj = getattr(item, nested_key, None)
        if nested_obj is not None:
            val = getattr(nested_obj, nested_sub, None)
            if val is not None:
                return val
    return None


def _coerce_int(value: Any) -> int:
    """Safely cast *value* to ``int``; fall back to ``0``."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any) -> float:
    """Safely cast *value* to ``float``; fall back to ``0.0``."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
