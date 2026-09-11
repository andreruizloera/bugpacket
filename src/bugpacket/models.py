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
    chain: str = ""
    """How this block relates to the block printed immediately before it.

    This is what distinguishes a continued exception chain from a second,
    unrelated failure in the same output, and the three chained values are not
    interchangeable: they disagree about which END of the chain the reader
    wants.

    - `""`: unrelated. A second failing test, a second panic.
    - `"cause"`: this block IS the previous block's cause. A JVM `Caused by:`
      line. The runtime printed the wrapper first, so the LAST block of the run
      is the root cause.
    - `"wrapped"`: the previous block is THIS block's cause. CPython's `The
      above exception was the direct cause of the following exception:`, which
      is what `raise X from Y` prints. The runtime printed the cause first, so
      the FIRST block of the run is the root cause. Same relation as `"cause"`,
      printed in the opposite order.
    - `"context"`: the previous block was merely being handled when this one
      was raised. CPython's `During handling of the above exception, another
      exception occurred:`. NOT a cause: the last block is the failure and the
      ones before it are background.
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
