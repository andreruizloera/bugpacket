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
    block: int = 0
    """Which `TraceBlock` this frame was printed inside.

    One command's output routinely holds several stacks: pytest prints one per
    failing test, and a JVM `Caused by:` chain prints one per exception. Without
    this, they concatenate into a single list that is not any of them."""


@dataclass(frozen=True)
class TraceBlock:
    """One stack as the runtime printed it, before any reordering.

    Blocks exist because "the stack" is the wrong unit. A run with two failing
    tests has two stacks, and flattening them produces a list whose adjacent
    entries never called each other.
    """

    index: int
    language: str
    innermost_first: bool
    """True when the runtime printed the failure site FIRST.

    Rust, Go, the JVM and V8 do. A CPython traceback does not: `most recent
    call last` means the frame that raised is at the bottom.
    """
    caused_by: bool = False
    """True when this block continues the previous block's exception chain.

    Only the JVM sets it, and it is what distinguishes `Caused by:` from a
    second, unrelated exception in the same output.
    """
    label: str = ""
    """The test name or exception this block belongs to, when one was printed."""


RANK_REASONS: dict[int, str] = {
    1: "stack trace",
    2: "failing test",
    3: "imported by, or in the same package as, a relevant file",
    4: "in git diff",
    5: "dependency manifest",
}

DIAGNOSTIC_REASON = "compiler diagnostic"
"""Rank 1 for a build failure, which named its files without any stack."""


@dataclass
class RankedFile:
    """A repository file selected for the packet, with its relevance rank."""

    path: Path  # absolute
    rel: str  # repo-relative POSIX path
    rank: int  # 1 (most relevant) to 5
    lines: set[int] = field(default_factory=set)  # lines referenced by stack frames
    reason_label: str | None = None
    """Overrides the rank's usual wording, for a rank the failure reached by a
    route the default text would describe wrongly."""

    @property
    def reason(self) -> str:
        return self.reason_label or RANK_REASONS[self.rank]


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
