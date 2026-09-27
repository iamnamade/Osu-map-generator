from __future__ import annotations

from pathlib import Path
from typing import Any

from ..analysis_io import load_json_file
from ..utils import MapGeneratorError


def compare_hybrid_reports(*, hybrids_dir: Path) -> str:
    if not hybrids_dir.exists() or not hybrids_dir.is_dir():
        raise MapGeneratorError(f"Hybrids directory does not exist: {hybrids_dir}")
    rows: list[dict[str, Any]] = []
    for report_path in sorted(hybrids_dir.glob("*-assembly.json")):
        raw_data = load_json_file(report_path, "Hybrid assembly report")
        if not isinstance(raw_data, dict):
            raise MapGeneratorError(f"Hybrid assembly report must be an object: {report_path}")
        scores = raw_data.get("scores")
        promotion = raw_data.get("promotion")
        if not isinstance(scores, dict) or not isinstance(promotion, dict):
            raise MapGeneratorError(f"Hybrid assembly report is malformed: {report_path}")
        rows.append(
            {
                "difficulty": raw_data.get("difficulty", report_path.stem),
                "overall": _as_number(scores.get("overallHybridScore")),
                "python": _as_number(scores.get("finalPythonQuality")),
                "promoted": bool(promotion.get("promoted", False)),
                "path": report_path.as_posix(),
            }
        )
    rows.sort(key=lambda row: (-row["overall"], row["difficulty"]))
    if not rows:
        return "No hybrid assembly reports were found."
    lines = ["Hybrid comparison", ""]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. {row['difficulty']}: hybrid {row['overall']:.1f}, python {row['python']:.1f}, promoted {'yes' if row['promoted'] else 'no'}"
        )
    lines.extend(["", "Reports:"])
    lines.extend(row["path"] for row in rows)
    return "\n".join(lines)


def _as_number(value: Any) -> float:
    if not isinstance(value, (int, float)):
        raise MapGeneratorError("Hybrid report score must be numeric.")
    return float(value)
