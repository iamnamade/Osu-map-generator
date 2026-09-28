"""Local FastAPI bridge for the Pulse Practice generator wizard."""

import datetime as _datetime

# Python 3.11+ exposes ``datetime.UTC``; provide the alias on 3.10 so the
# local API imports cleanly without requiring a specific interpreter.
if not hasattr(_datetime, "UTC"):
    _datetime.UTC = _datetime.timezone.utc  # type: ignore[attr-defined]

from .config import LocalApiConfig, get_local_api_config

__all__ = ["LocalApiConfig", "get_local_api_config"]
