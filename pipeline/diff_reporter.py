import difflib
from pathlib import Path
from harness.protocols import FileChange


def capture_snapshot(file_paths: list[str]) -> dict[str, str]:
    """
    Captura contenido actual de los archivos ANTES de ejecutar el step.
    Solo incluye archivos que existen y son legibles.
    """
    snapshot = {}
    for path_str in file_paths:
        p = Path(path_str)
        if p.exists() and p.is_file():
            try:
                snapshot[path_str] = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
    return snapshot


def compute_diff(before: dict[str, str], after: dict[str, str]) -> str | None:
    """
    Genera diff unificado entre snapshots antes/después.
    Retorna el patch como string, o None si no hubo cambios.
    """
    patches = []
    for path in sorted(set(before) | set(after)):
        before_lines = before.get(path, "").splitlines(keepends=True)
        after_lines  = after.get(path, "").splitlines(keepends=True)
        if before_lines == after_lines:
            continue
        diff = "".join(difflib.unified_diff(
            before_lines, after_lines,
            fromfile=f"a/{path}", tofile=f"b/{path}",
        ))
        if diff:
            patches.append(diff)
    return "\n".join(patches) if patches else None


def detect_file_changes(
    before: dict[str, str],
    after:  dict[str, str],
) -> list[FileChange]:
    changes = []
    all_files = sorted(set(before) | set(after))
    for f in all_files:
        if f not in before:
            changes.append(FileChange(
                path=f, action="created",
                diff_lines=len(after[f].splitlines()),
            ))
        elif f not in after:
            changes.append(FileChange(path=f, action="deleted", diff_lines=0))
        elif before[f] != after[f]:
            added   = sum(1 for l in after[f].splitlines() if l not in before[f])
            changes.append(FileChange(path=f, action="modified", diff_lines=added))
    return changes
