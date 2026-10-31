"""Playability analysis that runs on generated coordinates before packaging."""

from __future__ import annotations

from .cursor_physics import (
    MAX_CURSOR_VELOCITY_PX_PER_MS,
    AutoPlaySimulator,
)
from .qa_pipeline import run_qa

__all__ = [
    "MAX_CURSOR_VELOCITY_PX_PER_MS",
    "AutoPlaySimulator",
    "run_qa",
]
