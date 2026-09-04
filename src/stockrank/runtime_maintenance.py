"""Bounded runtime file inventory and cleanup; database retention stays in Storage."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PROTECTED_REPORTS = frozenset({"latest.md", "research_template.json"})
CLEANUP_FOLDERS = ("reports", "tmp", "cache/sec")


@dataclass(frozen=True)
class RuntimeFile:
    path: Path
    size: int
    modified_ns: int


@dataclass(frozen=True)
class CleanupEntry:
    file: RuntimeFile
    cutoff: datetime


@dataclass(frozen=True)
class CleanupPlan:
    root: Path
    entries: tuple[CleanupEntry, ...]


def runtime_sizes(root: Path, database: Path) -> dict[str, int]:
    """Preserve recursive size reporting, independently of direct-child cleanup."""
    sizes = {
        "database": sum(
            path.stat().st_size if path.exists() else 0
            for path in (Path(str(database) + suffix) for suffix in ("", "-wal", "-shm"))
        )
    }
    for label, folder in (
        ("reports", "reports"),
        ("sec_cache", "cache/sec"),
        ("logs", "logs"),
        ("temporary", "tmp"),
    ):
        sizes[label] = sum(
            path.stat().st_size for path in (root / folder).glob("**/*") if path.is_file()
        )
    return sizes


def _folder(root: Path, path: Path) -> str:
    for folder in CLEANUP_FOLDERS:
        if path.parent == root / folder:
            return folder
    raise ValueError(f"File is not a direct child of a cleanup directory: {path}")


def _check_path(root: Path, path: Path) -> None:
    folder = _folder(root, path)
    if folder == "reports" and path.name.casefold() in PROTECTED_REPORTS:
        raise ValueError(f"Protected report: {path}")
    # Resolve again at apply time: a directory may have been replaced by a link.
    if root.resolve() != root or path.resolve() != path or path.is_symlink():
        raise ValueError(f"Linked or redirected cleanup path: {path}")
    if not path.is_file():
        raise ValueError(f"Cleanup candidate is no longer a file: {path}")


def scan_cleanup_files(root: Path) -> tuple[RuntimeFile, ...]:
    """Read only the existing three cleanup directories; never recurse for deletion."""
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError("Cleanup root must be an absolute resolved path")
    files = []
    for folder in CLEANUP_FOLDERS:
        directory = root / folder
        if directory.resolve() != directory or directory.is_symlink():
            raise ValueError(f"Linked or redirected cleanup directory: {directory}")
        if not directory.exists():
            continue
        for path in directory.iterdir():
            if folder == "reports" and path.name.casefold() in PROTECTED_REPORTS:
                continue
            if path.is_symlink():
                raise ValueError(f"Linked cleanup candidate: {path}")
            if path.is_file():
                _check_path(root, path)
                stat = path.stat()
                files.append(RuntimeFile(path, stat.st_size, stat.st_mtime_ns))
    return tuple(files)


def plan_cleanup(
    root: Path,
    files: tuple[RuntimeFile, ...],
    *,
    report_cutoff: datetime,
    temporary_cutoff: datetime,
    sec_cache_cutoff: datetime,
) -> CleanupPlan:
    """Pure selection from captured metadata and explicit aware cutoff instants."""
    cutoffs = dict(zip(CLEANUP_FOLDERS, (report_cutoff, temporary_cutoff, sec_cache_cutoff)))
    if any(value.tzinfo is None or value.utcoffset() is None for value in cutoffs.values()):
        raise ValueError("Cleanup cutoffs must be timezone-aware")
    entries = []
    for file in files:
        folder = _folder(root, file.path)
        if folder == "reports" and file.path.name.casefold() in PROTECTED_REPORTS:
            continue
        cutoff = cutoffs[folder]
        if file.modified_ns / 1_000_000_000 < cutoff.timestamp():
            entries.append(CleanupEntry(file, cutoff))
    return CleanupPlan(root, tuple(entries))


def validate_cleanup_plan(plan: CleanupPlan, root: Path) -> None:
    """Refuse an unsafe or changed plan before any planned file is removed."""
    if not root.is_absolute() or root.resolve() != root or plan.root != root:
        raise ValueError("Cleanup plan does not match the resolved runtime root")
    if len({entry.file.path for entry in plan.entries}) != len(plan.entries):
        raise ValueError("Cleanup plan contains duplicate files")
    for entry in plan.entries:
        _validate_entry(entry, root)


def _validate_entry(entry: CleanupEntry, root: Path) -> None:
    _check_path(root, entry.file.path)
    stat = entry.file.path.stat()
    if (stat.st_size, stat.st_mtime_ns) != (entry.file.size, entry.file.modified_ns):
        raise ValueError(f"Cleanup candidate changed since planning: {entry.file.path}")
    if entry.cutoff.tzinfo is None or entry.cutoff.utcoffset() is None:
        raise ValueError("Cleanup cutoffs must be timezone-aware")
    if stat.st_mtime_ns / 1_000_000_000 >= entry.cutoff.timestamp():
        raise ValueError(f"Cleanup candidate is not expired: {entry.file.path}")


def apply_cleanup_plan(plan: CleanupPlan, root: Path) -> None:
    """Recheck the whole plan, then each path immediately before unlinking it.

    This is not an atomic filesystem transaction; a concurrent change or I/O error
    can still interrupt apply after earlier files were removed.
    """
    validate_cleanup_plan(plan, root)
    for entry in plan.entries:
        _validate_entry(entry, root)
        entry.file.path.unlink()
