from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from ..utils import MapGeneratorError

ARCHIVE_POLICIES: tuple[str, ...] = ("champion", "top3", "top5", "all")


def validate_archive_policy(policy: str) -> str:
    normalized = policy.strip().lower()
    if normalized not in ARCHIVE_POLICIES:
        allowed = ", ".join(ARCHIVE_POLICIES)
        raise MapGeneratorError(
            f'Unsupported archive policy "{policy}". Expected one of: {allowed}.'
        )
    return normalized


def retained_candidate_count(policy: str, candidate_count: int) -> int:
    if policy == "champion":
        return 1
    if policy == "top3":
        return min(3, candidate_count)
    if policy == "top5":
        return min(5, candidate_count)
    return candidate_count


def apply_archive_policy(
    *,
    candidates_root: Path,
    ranked_candidate_indices: list[int],
    policy: str,
    dry_run: bool = True,
) -> list[int]:
    """Keep only the top candidates per the archive policy.

    Non-retained candidate directories are moved into an ``archived/``
    subdirectory so the leaderboard stays complete while old candidates are
    preserved on disk. Returns the retained candidate indices.
    """
    policy = validate_archive_policy(policy)
    retain_count = retained_candidate_count(policy, len(ranked_candidate_indices))
    retained = ranked_candidate_indices[:retain_count]
    retained_set = set(retained)

    archived_root = candidates_root / "archived"
    for candidate_index in ranked_candidate_indices:
        if candidate_index in retained_set:
            continue
        candidate_dir = candidates_root / f"candidate-{candidate_index:03d}"
        if not candidate_dir.exists():
            continue
        if dry_run:
            continue
        destination = archived_root / candidate_dir.name
        if destination.exists():
            shutil.rmtree(destination)
        if candidate_dir.is_dir():
            shutil.move(str(candidate_dir), str(destination))
    return retained


def archive_status_line(policy: str, retained_count: int, candidate_count: int) -> str:
    if policy == "all":
        return f"Archive policy: all {candidate_count} candidates preserved."
    return (
        f"Archive policy: {policy} keeps the top {retained_count} of "
        f"{candidate_count} candidates; the rest move to archived/."
    )
