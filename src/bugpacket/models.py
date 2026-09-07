"""Shared data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Frame:
    """One stack frame parsed from command output."""

    path: str
    line: int
    function: str | None
    language: str  # "python", "node", "rust", "go", or "jvm"
    path_hint: str | None = None
    """A better path than `path`, when the dialect knows one.

    A JVM frame names only `Pricing.java`, but its fully-qualified class name
    carries the package, so the hint is `com/example/shop/Pricing.java`. The
    resolver tries the hint first because it is far harder to match by accident.
    """
    vendored: bool = False
    """True when the frame is known to be in a toolchain or dependency.

    A `RUST_BACKTRACE` dump is mostly standard library, and a JVM trace is
    mostly `java.base`. Those frames are worth printing as context but must
    never be searched for in the repository: a project with its own `map.rs`
    would otherwise have it pulled into the packet because the panic passed
    through `std`'s `HashMap`."""


RANK_REASONS: dict[int, str] = {
    1: "stack trace",
    2: "failing test",
    3: "imported by, or in the same package as, a relevant file",
    4: "in git diff",
    5: "dependency manifest",
}


@dataclass
class RankedFile:
    """A repository file selected for the packet, with its relevance rank."""

    path: Path  # absolute
    rel: str  # repo-relative POSIX path
    rank: int  # 1 (most relevant) to 5
    lines: set[int] = field(default_factory=set)  # lines referenced by stack frames

    @property
    def reason(self) -> str:
        return RANK_REASONS[self.rank]


@dataclass
class GitInfo:
    """Captured git state for the repository."""

    root: str
    branch: str
    commit: str
    status: str  # `git status --porcelain` output
    diff: str
    diff_truncated: bool
    changed_files: list[str]
