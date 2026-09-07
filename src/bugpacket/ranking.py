"""Deterministic relevance ranking for files that belong in the packet.

Rank order (lower is more relevant):
  1. files named in the stack trace
  2. the failing test file(s)
  3. local modules imported by rank 1 and 2 files
  4. files touched by the current git diff
  5. the dependency manifest(s)

Within a rank, files sort by repository-relative path, so the output is
stable across runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from bugpacket.models import Frame, RankedFile
from bugpacket.resolve import FrameResolver
from bugpacket.tokens import SKIP_DIR_NAMES

_MAX_FILE_BYTES = 512_000

MANIFEST_NAMES = (
    "Cargo.toml",
    "Pipfile",
    "go.mod",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
)

_PY_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+(?P<from>[A-Za-z_][\w.]*)\s+import\s|"
    r"import\s+(?P<imp>[A-Za-z_][\w.]*(?:\s*,\s*[A-Za-z_][\w.]*)*))",
    re.MULTILINE,
)

_JS_IMPORT_RE = re.compile(
    r"""(?:require\(\s*|from\s+|import\s+)['"](?P<spec>\.{1,2}/[^'"]+)['"]"""
)

_JS_EXTS = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")


def _is_rankable(path: Path, repo_root: Path) -> bool:
    try:
        resolved = path.resolve()
        if not resolved.is_file():
            return False
        rel = resolved.relative_to(repo_root.resolve())
    except (OSError, ValueError):
        return False
    if any(part in SKIP_DIR_NAMES for part in rel.parts):
        return False
    try:
        return 0 < resolved.stat().st_size <= _MAX_FILE_BYTES
    except OSError:
        return False


def _rankable_or_none(path: Path | None, repo_root: Path) -> Path | None:
    """Keep a resolved path only if it is a file worth putting in the packet."""
    if path is None or not _is_rankable(path, repo_root):
        return None
    return path.resolve()


def _python_local_imports(file: Path, repo_root: Path) -> list[Path]:
    try:
        text = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    modules: set[str] = set()
    for match in _PY_IMPORT_RE.finditer(text):
        if match.group("from"):
            modules.add(match.group("from"))
        elif match.group("imp"):
            modules.update(m.strip() for m in match.group("imp").split(","))

    found: list[Path] = []
    bases = (repo_root, repo_root / "src", file.parent)
    for module in sorted(modules):
        parts = module.split(".")
        for base in bases:
            for candidate in (
                base.joinpath(*parts).with_suffix(".py"),
                base.joinpath(*parts) / "__init__.py",
            ):
                if _is_rankable(candidate, repo_root):
                    found.append(candidate.resolve())
                    break
            else:
                continue
            break
    return found


def _js_local_imports(file: Path, repo_root: Path) -> list[Path]:
    try:
        text = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: list[Path] = []
    for match in _JS_IMPORT_RE.finditer(text):
        base = (file.parent / match.group("spec")).resolve()
        candidates = [base] if base.suffix else []
        candidates.extend(base.with_suffix(ext) for ext in _JS_EXTS)
        candidates.extend(base / f"index{ext}" for ext in _JS_EXTS)
        for candidate in candidates:
            if _is_rankable(candidate, repo_root):
                found.append(candidate.resolve())
                break
    return found


def _go_package_siblings(file: Path, repo_root: Path) -> list[Path]:
    """The other non-test `.go` files in this file's package.

    Go has no import statement to follow here, because a Go package IS its
    directory: `pricing_test.go` and `pricing.go` are the same package and the
    test never imports the thing it tests. A `go test` failure reports only the
    test file, so without this the packet would contain the assertion and not
    the function it asserts on.

    Only non-test siblings are taken, and only from the one directory; this
    does not walk into subdirectories, which are different packages.
    """
    found: list[Path] = []
    try:
        entries = sorted(file.parent.iterdir())
    except OSError:
        return []
    for candidate in entries:
        if candidate == file or candidate.suffix != ".go":
            continue
        if candidate.name.endswith("_test.go"):
            continue
        if _is_rankable(candidate, repo_root):
            found.append(candidate.resolve())
    return found


def _find_manifests(cwd: Path, repo_root: Path) -> list[Path]:
    """Nearest manifest of each kind, searching from cwd up to the repo root."""
    found: dict[str, Path] = {}
    directory = cwd.resolve()
    root = repo_root.resolve()
    while True:
        for name in MANIFEST_NAMES:
            candidate = directory / name
            if name not in found and _is_rankable(candidate, repo_root):
                found[name] = candidate.resolve()
        if directory == root or directory.parent == directory:
            break
        directory = directory.parent
    return [found[name] for name in sorted(found)]


def rank_files(
    repo_root: Path,
    cwd: Path,
    frames: list[Frame],
    failing_test_paths: list[str],
    git_changed_files: list[str],
    resolver: FrameResolver | None = None,
    frame_reason: str | None = None,
) -> list[RankedFile]:
    """Produce the deterministic, rank-ordered file list for the packet.

    `frame_reason` renames rank 1 for a failure whose frames did not come from
    a stack trace: a compiler diagnostic names files with no stack at all.
    """
    if resolver is None:
        resolver = FrameResolver(repo_root=repo_root, cwd=cwd)
    best: dict[str, RankedFile] = {}

    def consider(path: Path, rank: int, line: int | None = None, label: str | None = None) -> None:
        rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
        entry = best.get(rel)
        if entry is None:
            entry = RankedFile(path=path.resolve(), rel=rel, rank=rank)
            best[rel] = entry
        if rank <= entry.rank:
            entry.rank = rank
            entry.reason_label = label
        if line is not None:
            entry.lines.add(line)

    # Rank 1: files named in the stack trace, or by a compiler diagnostic.
    for frame in frames:
        resolved = _rankable_or_none(resolver.resolve(frame).path, repo_root)
        if resolved is not None:
            consider(resolved, 1, frame.line, frame_reason)

    # Rank 2: the failing test file(s).
    for raw in failing_test_paths:
        resolved = _rankable_or_none(resolver.resolve_path(raw), repo_root)
        if resolved is not None:
            consider(resolved, 2)

    # Rank 3: local modules imported by rank 1 and 2 files.
    parents = [entry for entry in best.values() if entry.rank <= 2]
    for entry in sorted(parents, key=lambda e: e.rel):
        if entry.path.suffix in (".py", ".pyw"):
            imports = _python_local_imports(entry.path, repo_root)
        elif entry.path.suffix in _JS_EXTS:
            imports = _js_local_imports(entry.path, repo_root)
        elif entry.path.suffix == ".go":
            imports = _go_package_siblings(entry.path, repo_root)
        else:
            imports = []
        for imported in imports:
            consider(imported, 3)

    # Rank 4: files in the current git diff.
    for raw in git_changed_files:
        candidate = repo_root / raw
        if _is_rankable(candidate, repo_root):
            consider(candidate.resolve(), 4)

    # Rank 5: dependency manifests.
    for manifest in _find_manifests(cwd, repo_root):
        consider(manifest, 5)

    return sorted(best.values(), key=lambda e: (e.rank, e.rel))
