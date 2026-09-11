"""Parse stack traces out of raw command output.

Handles seven shapes:
- standard CPython tracebacks (`Traceback (most recent call last):` blocks)
- pytest-style tracebacks (`path.py:12: in test_x` refs and `E   Error: msg` lines)
- Node/V8 stacks (`    at func (path.js:3:11)` frames)
- Rust panics and `RUST_BACKTRACE` output
- Go panics, goroutine dumps, and `go test` failures
- JVM exceptions, including `Caused by:` chains
- compiler diagnostics from rustc, go build, and javac, which fail without
  producing a stack trace at all

The Rust, Go, and JVM state machines live in `dialects.py`, and the compiler
readers in `diagnostics.py`. This module owns the single pass over the output
and the order the readers are offered each line, which is the only place their
regexes could collide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from bugpacket import dialects
from bugpacket.diagnostics import DiagnosticState, feed_diagnostic
from bugpacket.dialects import GoState, JvmState, ParsedLines, RustState
from bugpacket.models import Frame, TraceBlock

_PY_TB_START = "Traceback (most recent call last):"

# The two lines CPython prints BETWEEN chained tracebacks. They look alike and
# mean opposite things, so they are read separately and never collapsed:
# `raise X from Y` sets `__cause__` and prints the first; an exception raised
# inside an `except` block sets `__context__` and prints the second. See
# `TraceBlock.chain`.
_PY_CAUSE_SEP = "The above exception was the direct cause of the following exception:"
_PY_CONTEXT_SEP = "During handling of the above exception, another exception occurred:"

_PY_FRAME_RE = re.compile(
    r'^\s*File "(?P<path>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>.+?))?\s*$'
)

# Bare exception line ending a CPython traceback, or standing alone in output.
_ERROR_LINE_RE = re.compile(
    r"^(?P<etype>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit|Interrupt)"
    r"(?:\s\[[\w.]+\])?)(?::\s?(?P<msg>.*))?$"
)

# pytest-style frame reference: "tests/test_x.py:14:" or "pkg/mod.py:7: in helper"
_PYTEST_REF_RE = re.compile(
    r"^(?P<path>[^\s:\"']+\.py[wi]?):(?P<line>\d+):(?:\s+in\s+(?P<func>\S+))?"
)

_PYTEST_E_RE = re.compile(r"^E\s{2,}(?P<msg>\S.*)$")

# The rule pytest draws above each failing test: `____ test_total_is_wrong ____`.
# This is the only reliable boundary between one failing test's traceback and
# the next one's. The `_ _ _ _` separator pytest draws INSIDE a traceback has
# spaces between the underscores, so requiring three consecutive ones excludes
# it.
_PYTEST_SECTION_RE = re.compile(r"^_{3,}\s+(?P<name>\S.*?)\s+_{3,}$")

_PYTEST_FAILED_RE = re.compile(
    r"^(?:FAILED|ERROR)\s+(?P<path>[^\s:]+\.py)::(?P<test>\S+)(?:\s+-\s+(?P<msg>.*))?$"
)

_NODE_FRAME_RE = re.compile(
    r"^\s+at\s+(?:(?P<func>.+?)\s+\()?(?P<path>[^()\s]+?):(?P<line>\d+):(?P<col>\d+)\)?\s*$"
)

_JS_TRACE_EXTS = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")


@dataclass(frozen=True)
class Stack:
    """One trace block's frames, reordered so the failure site is first."""

    block: TraceBlock
    frames: list[Frame]


@dataclass
class ParsedOutput:
    """Everything the parser could extract from a command's combined output."""

    frames: list[Frame] = field(default_factory=list)
    blocks: list[TraceBlock] = field(default_factory=list)
    """Every stack found, in the order the runtime printed them."""
    error_lines: list[str] = field(default_factory=list)
    pytest_error_lines: list[str] = field(default_factory=list)
    failed_tests: list[tuple[str, str]] = field(default_factory=list)  # (path, test id)
    failed_test_names: list[str] = field(default_factory=list)
    """Failing test ids that name no file: Go's `--- FAIL: TestX` and Rust's
    `module::tests::x --- FAILED` both identify a test without a path."""
    cause_chain: list[str] = field(default_factory=list)
    """An exception chain, OUTERMOST FIRST, when one was printed.

    The JVM fills this as it reads `Caused by:`, which is already outermost
    first. CPython prints a `raise X from Y` chain the other way round, cause
    first, so `parse_output` reverses it into this list's order rather than
    keeping two conventions. A `During handling of the above exception` run is
    deliberately NOT a cause chain and does not appear here: the last exception
    is the failure, not a wrapper around an earlier one.
    """
    diagnostics: list[str] = field(default_factory=list)
    """Compiler errors, in the order the compiler reported them.

    Kept apart from `error_lines` because they are read from the other end: a
    compiler's first error is the one to fix and the rest are usually its
    consequences, where a traceback's LAST line is the exception."""

    @property
    def root_cause(self) -> str | None:
        """The innermost exception of a wrapping chain.

        A wrapped JVM failure reports the wrapper first, and the wrapper is
        almost never where the bug is: `IllegalStateException: checkout failed`
        is a rethrow, and the `NullPointerException` two frames down is the
        thing to fix. Reporting the wrapper as the failure sends an agent to
        the catch block.

        Python has exactly the same problem and used to be exempt from this by
        accident. `raise RuntimeError("service failed to start") from exc` ends
        the output with the RuntimeError, so falling back to `error_lines[-1]`
        reported the rethrow and dropped the `FileNotFoundError` that says what
        is actually wrong. `parse_output` now fills `cause_chain` for CPython
        too, so both runtimes reach this.
        """
        if len(self.cause_chain) < 2:
            return None
        return self.cause_chain[-1]

    def distilled_failure(self) -> str | None:
        """The single most useful description of what went wrong."""
        root = self.root_cause
        if root is not None:
            return root
        if self.diagnostics:
            return self.diagnostics[0]
        if self.error_lines:
            return self.error_lines[-1]
        if self.pytest_error_lines:
            return self.pytest_error_lines[-1]
        if self.failed_tests:
            path, test = self.failed_tests[-1]
            return f"Test failed: {path}::{test}"
        if self.failed_test_names:
            return f"Test failed: {self.failed_test_names[-1]}"
        return None

    def unique_frames(self) -> list[Frame]:
        """Every frame, deduplicated on (path, line), in order of appearance.

        This is the set of files the failure touched, which is what ranking
        wants. It is deliberately NOT what the packet prints: flattening every
        block into one list produces adjacent entries that never called each
        other. `ordered_stacks` is the reading order.

        Paths are compared with `./` and backslashes folded, because one Rust
        panic prints its location as `src/pricing.rs` and the backtrace under
        it prints the same file as `./src/pricing.rs`.
        """
        return _dedupe(self.frames)

    def ordered_stacks(self) -> list[Stack]:
        """The stacks, each with its failure site first, root cause first.

        Two reorderings happen here, and they are different problems:

        1. WITHIN a block, frames are reversed when the runtime printed them
           outermost-first. Only CPython and pytest do; Rust, Go, the JVM and
           V8 already lead with the failure site.
        2. ACROSS blocks, a chained run is reordered so the block a reader
           should start at leads. Which block that is depends on the link type,
           and `TraceBlock.chain` records it per link rather than assuming one
           runtime's convention. See `_order_run`.

        Frames are deduplicated within a block, never across blocks. Two
        failing tests share most of their stack, and removing the shared part
        from the second one leaves a stump rather than a stack.
        """
        by_block: dict[int, list[Frame]] = {}
        for frame in self.frames:
            by_block.setdefault(frame.block, []).append(frame)

        stacks: list[Stack] = []
        for block in self.blocks:
            frames = _dedupe(by_block.pop(block.index, []))
            if not frames:
                continue
            stacks.append(Stack(block, frames if block.innermost_first else list(reversed(frames))))
        for index in sorted(by_block):  # frames whose block was never registered
            frames = _dedupe(by_block[index])
            if frames:
                stacks.append(Stack(TraceBlock(index, frames[0].language, True), frames))

        runs: list[list[Stack]] = []
        for stack in stacks:
            if runs and stack.block.chain:
                runs[-1].append(stack)
            else:
                runs.append([stack])
        return [stack for run in runs for stack in _order_run(run)]


def _order_run(run: list[Stack]) -> list[Stack]:
    """One chained run of stacks, reordered so the block to read first leads.

    A chain is printed in whichever order its runtime prefers, and the three
    link types in `TraceBlock.chain` disagree about which end is useful:

    - `"cause"` (JVM `Caused by:`) prints the wrapper first, so the run is
      REVERSED and the deepest cause leads.
    - `"wrapped"` (CPython `raise X from Y`) prints the cause first, so the run
      is LEFT ALONE. That is the same answer this function's predecessor gave,
      but it gave it by never having heard of Python chains, which is why
      `During handling` got it too.
    - `"context"` (CPython, an exception raised while handling another) is not
      a cause link at all. Everything printed before the last such link was
      merely in progress when the real failure hit, so the run is cut there and
      the part after the cut leads. The background is kept, last, because it is
      still how execution got there.

    A run may mix them: `Z`, `During handling`, `Y`, `direct cause`, `X` is one
    run of three, and the answer is `[Y, X, Z]`. Y is the root cause of the
    failure, X is its wrapper, Z is background.
    """
    cut = 0
    for index, stack in enumerate(run):
        if stack.block.chain == "context":
            cut = index
    failure, background = run[cut:], run[:cut]
    if any(stack.block.chain == "cause" for stack in failure):
        failure = list(reversed(failure))
    return failure + background


def _label_chained_python_blocks(
    blocks: list[TraceBlock], errors: dict[int, str]
) -> list[TraceBlock]:
    """Name each traceback in a CPython chain after the exception that ended it.

    A chain prints several tracebacks in a row, and the packet prints them one
    after another. Without a label they run together into what looks like one
    long stack whose middle two lines never called each other, which is the
    problem blocks exist to solve. The JVM reader already labels its blocks
    with the exception class; CPython's label is only knowable once the block
    has ended, so it is attached here rather than at `open_block`.

    Only blocks in a chain are labelled. A lone traceback is printed without a
    header today and gains nothing from one.
    """
    chained = {
        index
        for index, block in enumerate(blocks)
        if block.chain or (index + 1 < len(blocks) and blocks[index + 1].chain)
    }
    return [
        replace(block, label=errors[index])
        if index in chained and index in errors and not block.label
        else block
        for index, block in enumerate(blocks)
    ]


def _python_cause_chain(blocks: list[TraceBlock], errors: dict[int, str]) -> list[str]:
    """The exception lines of the last CPython `raise X from Y` run.

    Returned OUTERMOST FIRST, matching what the JVM reader builds, so
    `root_cause` and the packet's prose need only one convention. CPython
    prints such a run cause first, so this reverses it.

    Only an unbroken run of `"wrapped"` links counts. A `"context"` link ends
    the run because the exception before it is not a cause of anything, and an
    unchained block ends it because a second, unrelated traceback is not part
    of the first one's chain.
    """
    run: list[int] = []
    for block in blocks:
        if block.language != "python":
            run = []
        elif block.chain == "wrapped" and run:
            run.append(block.index)
        else:
            run = [block.index]
    lines = [errors[index] for index in run if index in errors]
    return list(reversed(lines)) if len(lines) > 1 else []


def _dedupe(frames: list[Frame]) -> list[Frame]:
    """Frames in order, deduplicated on (path, line) with `./` folded."""
    seen: set[tuple[str, int]] = set()
    out: list[Frame] = []
    for frame in frames:
        path = frame.path.replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        key = (path, frame.line)
        if key not in seen:
            seen.add(key)
            out.append(frame)
    return out


def _looks_like_node_path(path: str) -> bool:
    """True for paths a V8 frame would carry.

    This used to be "anything that is not Python", which was fine when Python
    and Node were the only dialects. It is not fine now: a Rust backtrace line
    (`  at ./src/pricing.rs:5:25`) has the exact shape of a Node frame, and
    would be recorded as Node.
    """
    if path.startswith("node:"):
        return True
    lowered = path.lower()
    if lowered.endswith(_JS_TRACE_EXTS):
        return True
    tail = lowered.rsplit("/", 1)[-1]
    return "." not in tail  # an extensionless internal module id


def parse_output(text: str) -> ParsedOutput:
    """Parse command output for stack traces, error lines, and failed tests."""
    result = ParsedOutput()
    acc = ParsedLines()
    rust, go, jvm = RustState(), GoState(), JvmState()
    diags = DiagnosticState()
    in_py_traceback = False
    py_block: int | None = None
    py_next_chain = ""  # set by a chain separator, consumed by the next traceback
    py_block_errors: dict[int, str] = {}  # block index -> the line that ended it
    pytest_block: int | None = None
    node_block: int | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        # Node frames are consecutive and carry no header, so a V8 stack ends
        # at the first line that is not one of its frames.
        prev_node_block, node_block = node_block, None

        if _PY_TB_START in line:
            in_py_traceback = True
            py_block = acc.open_block("python", innermost_first=False, chain=py_next_chain)
            py_next_chain = ""
            continue

        if in_py_traceback:
            frame_match = _PY_FRAME_RE.match(line)
            if frame_match:
                result.frames.append(
                    Frame(
                        path=frame_match.group("path"),
                        line=int(frame_match.group("line")),
                        function=frame_match.group("func"),
                        language="python",
                        block=py_block or 0,
                    )
                )
                continue
            if line.startswith((" ", "\t")) or not line.strip():
                continue  # source context line inside the traceback
            error_match = _ERROR_LINE_RE.match(line)
            if error_match:
                result.error_lines.append(line.strip())
                if py_block is not None:
                    py_block_errors[py_block] = line.strip()
            in_py_traceback = False
            continue

        # Between two chained CPython tracebacks. Checked here, straight after
        # the traceback body, because that is the only place either line can
        # appear; further down they would reach the dialect readers, and the
        # word "exception" in both of them is the kind of thing a header regex
        # is built to match.
        stripped = line.strip()
        if stripped == _PY_CAUSE_SEP:
            py_next_chain = "wrapped"
            continue
        if stripped == _PY_CONTEXT_SEP:
            py_next_chain = "context"
            continue

        section_match = _PYTEST_SECTION_RE.match(line)
        if section_match:
            pytest_block = acc.open_block(
                "python", innermost_first=False, label=section_match.group("name")
            )
            continue

        failed_match = _PYTEST_FAILED_RE.match(line)
        if failed_match:
            result.failed_tests.append((failed_match.group("path"), failed_match.group("test")))
            continue

        e_match = _PYTEST_E_RE.match(line)
        if e_match:
            result.pytest_error_lines.append(e_match.group("msg"))
            continue

        ref_match = _PYTEST_REF_RE.match(line)
        if ref_match:
            if pytest_block is None:  # a bare `path.py:12: in f` with no section rule
                pytest_block = acc.open_block("python", innermost_first=False)
            result.frames.append(
                Frame(
                    path=ref_match.group("path"),
                    line=int(ref_match.group("line")),
                    function=ref_match.group("func"),
                    language="python",
                    block=pytest_block,
                )
            )
            continue

        # Rust first: a backtrace `at path:line:col` line is shaped exactly
        # like a Node frame, and only the Rust state machine knows it is inside
        # a `stack backtrace:` block.
        if dialects.feed_rust(line, rust, acc):
            continue
        if dialects.feed_go(line, go, acc):
            continue
        if dialects.feed_jvm(line, jvm, acc):
            continue
        if feed_diagnostic(line, diags, acc):
            continue

        node_match = _NODE_FRAME_RE.match(line)
        if node_match and _looks_like_node_path(node_match.group("path")):
            func = node_match.group("func")
            node_block = (
                prev_node_block
                if prev_node_block is not None
                else acc.open_block("node", innermost_first=True)
            )
            result.frames.append(
                Frame(
                    path=node_match.group("path"),
                    line=int(node_match.group("line")),
                    function=func.strip() if func else None,
                    language="node",
                    block=node_block,
                )
            )
            continue

        error_match = _ERROR_LINE_RE.match(line.strip())
        if error_match and not line.startswith((" ", "\t")):
            result.error_lines.append(line.strip())

    result.frames.extend(acc.frames)
    result.error_lines.extend(acc.error_lines)
    result.failed_test_names.extend(acc.failed_test_names)
    result.cause_chain.extend(acc.cause_chain)
    result.diagnostics.extend(acc.diagnostics)
    result.blocks.extend(_label_chained_python_blocks(acc.blocks, py_block_errors))
    if not result.cause_chain:
        # Only when no JVM chain was read. A single output holding both is not
        # a thing this has seen, and merging two chains into one list would
        # produce a `root_cause` belonging to neither.
        result.cause_chain.extend(_python_cause_chain(result.blocks, py_block_errors))
    return result
