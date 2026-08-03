"""Conservative maintenance helper for JJYB_AI智剪.

It only manages regenerated Python bytecode caches in source directories.
It never removes user media, project data, output files, databases, logs,
checkpoints, or task working directories. Run without --apply to review the
planned cleanup first.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOTS = ("backend", "frontend", "scripts", "tests")
CACHE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
CACHE_FILE_SUFFIXES = {".pyc", ".pyo"}
CACHE_FILE_NAMES = {".coverage"}


@dataclass(frozen=True)
class Candidate:
    path: Path
    is_dir: bool
    size: int


def path_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0

    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def find_candidates() -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[Path] = set()

    for root_name in SOURCE_ROOTS:
        root = PROJECT_ROOT / root_name
        if not root.is_dir():
            continue
        try:
            items = root.rglob("*")
            for item in items:
                try:
                    resolved = item.resolve()
                    resolved.relative_to(root.resolve())
                except (OSError, ValueError):
                    continue
                if resolved in seen:
                    continue
                if item.is_dir() and item.name in CACHE_DIR_NAMES:
                    seen.add(resolved)
                    candidates.append(Candidate(item, True, path_size(item)))
                elif item.is_file() and (item.suffix.lower() in CACHE_FILE_SUFFIXES or item.name in CACHE_FILE_NAMES):
                    seen.add(resolved)
                    candidates.append(Candidate(item, False, path_size(item)))
        except OSError as exc:
            print(f"[WARN] Cannot inspect {root}: {exc}")

    # A cache directory owns every bytecode file below it. Keep the directory
    # only so the report and --apply action never count the same bytes twice.
    top_level = [
        candidate
        for candidate in candidates
        if not any(
            owner.is_dir
            and owner.path != candidate.path
            and candidate.path.is_relative_to(owner.path)
            for owner in candidates
        )
    ]
    return sorted(top_level, key=lambda candidate: str(candidate.path).casefold())


def format_size(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def remove_candidate(candidate: Candidate) -> None:
    if candidate.is_dir:
        shutil.rmtree(candidate.path)
    else:
        candidate.path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Review or remove regenerated Python caches.")
    parser.add_argument("--apply", action="store_true", help="Delete the reviewed cache candidates.")
    args = parser.parse_args()

    candidates = find_candidates()
    total_size = sum(candidate.size for candidate in candidates)
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"JJYB maintenance ({mode})")
    print("Scope: backend/, frontend/, scripts/, tests/ regenerated Python caches only.")
    print("Protected: uploads/, output/, outputs/, exports/, database/, logs/, temp/, storage/.")

    if not candidates:
        print("No cache candidates found.")
        return 0

    for candidate in candidates:
        relative = candidate.path.relative_to(PROJECT_ROOT)
        kind = "DIR " if candidate.is_dir else "FILE"
        print(f"{kind} {relative} ({format_size(candidate.size)})")

    print(f"Candidates: {len(candidates)}, estimated reclaimable space: {format_size(total_size)}")
    if not args.apply:
        print("Nothing was deleted. Re-run with --apply after review.")
        return 0

    removed = 0
    for candidate in candidates:
        try:
            remove_candidate(candidate)
            removed += 1
        except OSError as exc:
            print(f"[WARN] Could not remove {candidate.path}: {exc}")
    print(f"Removed {removed}/{len(candidates)} cache candidates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
