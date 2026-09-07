"""Map a stack-frame path onto a real file in the repository.

Python and Node traces name files in a way that usually works directly: an
absolute path that still exists, or a path relative to the working directory.
Rust, Go, and JVM traces frequently do not.

- A JVM frame is `at com.example.shop.Pricing.applyCoupon(Pricing.java:8)`.
  It carries a file NAME and no directory at all. The package from the
  fully-qualified class name is the only thing that says where the file lives.
- A `go test` failure line is `pricing_test.go:9: ...`, named relative to the
  package directory, which is not the directory the command ran in.
- A Go panic frame carries an absolute path recorded when the binary was
  BUILT. Anything built in a container or on CI names a directory that does
  not exist on the machine reading the trace.

So resolution falls back to searching the repository for a file whose path
ends with the frame's path. That search can be wrong, and a wrong file in a
packet is worse than a missing one: an agent handed the wrong `Pricing.java`
will confidently edit it. The rule here is therefore that a suffix match
resolves only when it is UNIQUE. Two candidates mean BugPacket does not know,
and the packet says so and names them rather than picking one.

This module is pure apart from reading the directory tree; it decides nothing
about ranking or rendering, and it is the single place both of those ask, so
the "Relevant stack" section and the file list cannot disagree.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from bugpacket.dialects import is_vendored_path
from bugpacket.models import Frame
from bugpacket.tokens import SKIP_DIR_NAMES

_MAX_INDEXED_FILES = 40_000


@dataclass(frozen=True)
class Resolution:
    """What resolving one frame produced."""

    path: Path | None = None
    how: str = "unresolved"
    """One of: "direct" (the path opened as given), "suffix" (found by a unique
    suffix match), "ambiguous" (several files matched, so none was chosen),
    "vendored" (a toolchain or dependency file), "outside-repo" (a real file
    that is not part of this repository), or "unresolved"."""
    candidates: tuple[str, ...] = ()  # repo-relative, only when ambiguous

    @property
    def found(self) -> bool:
        return self.path is not None


def _normalize(raw: str) -> PurePosixPath:
    """A frame path as POSIX parts, with Windows separators and `./` folded."""
    text = raw.replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return PurePosixPath(text)


@dataclass
class FrameResolver:
    """Resolves frame paths against one repository, indexing it lazily."""

    repo_root: Path
    cwd: Path
    _index: dict[str, list[str]] | None = field(default=None, init=False, repr=False)
    _truncated: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.repo_root = self.repo_root.resolve()
        self.cwd = self.cwd.resolve()

    @property
    def index_truncated(self) -> bool:
        """True when the repository was larger than the index cap."""
        self._build_index()
        return self._truncated

    def _build_index(self) -> dict[str, list[str]]:
        """Map file name to the repo-relative paths carrying that name."""
        if self._index is not None:
            return self._index
        index: dict[str, list[str]] = {}
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.repo_root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIR_NAMES)
            for name in sorted(filenames):
                if count >= _MAX_INDEXED_FILES:
                    self._truncated = True
                    break
                rel = (Path(dirpath) / name).relative_to(self.repo_root).as_posix()
                index.setdefault(name, []).append(rel)
                count += 1
            if self._truncated:
                break
        self._index = index
        return index

    def _is_repo_file(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            if not resolved.is_file():
                return False
            rel = resolved.relative_to(self.repo_root)
        except (OSError, ValueError):
            return False
        return not any(part in SKIP_DIR_NAMES for part in rel.parts)

    def _direct(self, raw: str) -> Path | None:
        """The original rule: an absolute path, or one relative to cwd or root."""
        path = Path(raw)
        candidates = [path] if path.is_absolute() else [self.cwd / path, self.repo_root / path]
        for candidate in candidates:
            if self._is_repo_file(candidate):
                return candidate.resolve()
        return None

    def _suffix_matches(self, hint: PurePosixPath) -> tuple[list[str], int]:
        """Repo files whose path ends with the longest matching suffix of `hint`.

        Returns the matching repo-relative paths and how many trailing path
        segments had to agree. A longer agreement is stronger evidence, so the
        search starts from the whole hint and shortens until something matches.
        """
        index = self._build_index()
        by_name = index.get(hint.name, [])
        if not by_name:
            return [], 0
        parts = hint.parts
        for depth in range(len(parts), 0, -1):
            needle = "/".join(parts[len(parts) - depth :])
            hits = [rel for rel in by_name if rel == needle or rel.endswith("/" + needle)]
            if hits:
                return sorted(hits), depth
        return [], 0

    def resolve(self, frame: Frame) -> Resolution:
        """Resolve one frame to a repository file, refusing to guess."""
        direct = self._direct(frame.path)
        if direct is not None:
            return Resolution(path=direct, how="direct")

        # Two ways a frame is known to be outside this repository, both of
        # which must stop the suffix search rather than merely fail it.
        if frame.vendored or is_vendored_path(frame.path):
            return Resolution(how="vendored")
        raw = Path(frame.path)
        if raw.is_absolute() and raw.exists():
            # The path resolved to a real file that is not in the repository.
            # Searching for something with the same name inside the repository
            # would answer a question nobody asked.
            return Resolution(how="outside-repo")

        # A frame may carry a stronger hint than its own path. A JVM frame
        # knows its package, so `Pricing.java` becomes `com/example/shop/Pricing.java`.
        hints = []
        if frame.path_hint:
            hints.append(_normalize(frame.path_hint))
        hints.append(_normalize(frame.path))

        for hint in hints:
            hits, _depth = self._suffix_matches(hint)
            if len(hits) == 1:
                candidate = self.repo_root / hits[0]
                if self._is_repo_file(candidate):
                    return Resolution(path=candidate.resolve(), how="suffix")
            elif len(hits) > 1:
                return Resolution(how="ambiguous", candidates=tuple(hits))
        return Resolution(how="unresolved")

    def resolve_path(self, raw: str) -> Path | None:
        """Resolve a bare path string (a failing test file, not a frame)."""
        return self.resolve(Frame(path=raw, line=0, function=None, language="unknown")).path
