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
    language: str  # "python" or "node"


RANK_REASONS: dict[int, str] = {
    1: "stack trace",
    2: "failing test",
    3: "imported by a relevant file",
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
