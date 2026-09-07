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
from dataclasses import dataclass, field

from bugpacket import dialects
from bugpacket.diagnostics import DiagnosticState, feed_diagnostic
from bugpacket.dialects import GoState, JvmState, ParsedLines, RustState
from bugpacket.models import Frame

_PY_TB_START = "Traceback (most recent call last):"

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

_PYTEST_FAILED_RE = re.compile(
    r"^(?:FAILED|ERROR)\s+(?P<path>[^\s:]+\.py)::(?P<test>\S+)(?:\s+-\s+(?P<msg>.*))?$"
)

_NODE_FRAME_RE = re.compile(
    r"^\s+at\s+(?:(?P<func>.+?)\s+\()?(?P<path>[^()\s]+?):(?P<line>\d+):(?P<col>\d+)\)?\s*$"
)

_JS_TRACE_EXTS = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")


@dataclass
class ParsedOutput:
    """Everything the parser could extract from a command's combined output."""

    frames: list[Frame] = field(default_factory=list)
    error_lines: list[str] = field(default_factory=list)
    pytest_error_lines: list[str] = field(default_factory=list)
    failed_tests: list[tuple[str, str]] = field(default_factory=list)  # (path, test id)
    failed_test_names: list[str] = field(default_factory=list)
    """Failing test ids that name no file: Go's `--- FAIL: TestX` and Rust's
    `module::tests::x --- FAILED` both identify a test without a path."""
    cause_chain: list[str] = field(default_factory=list)
    """A JVM exception chain, outermost first, when `Caused by:` appeared."""
    diagnostics: list[str] = field(default_factory=list)
    """Compiler errors, in the order the compiler reported them.

    Kept apart from `error_lines` because they are read from the other end: a
    compiler's first error is the one to fix and the rest are usually its
    consequences, where a traceback's LAST line is the exception."""

    @property
    def root_cause(self) -> str | None:
        """The innermost exception of a `Caused by:` chain.

        A wrapped JVM failure reports the wrapper first, and the wrapper is
        almost never where the bug is: `IllegalStateException: checkout failed`
        is a rethrow, and the `NullPointerException` two frames down is the
        thing to fix. Reporting the wrapper as the failure sends an agent to
        the catch block.
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
        """Frames in order of appearance, deduplicated on (path, line).

        Paths are compared with `./` and backslashes folded, because one Rust
        panic prints its location as `src/pricing.rs` and the backtrace under
        it prints the same file as `./src/pricing.rs`.
        """
        seen: set[tuple[str, int]] = set()
        out: list[Frame] = []
        for frame in self.frames:
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

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")

        if _PY_TB_START in line:
            in_py_traceback = True
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
                    )
                )
                continue
            if line.startswith((" ", "\t")) or not line.strip():
                continue  # source context line inside the traceback
            error_match = _ERROR_LINE_RE.match(line)
            if error_match:
                result.error_lines.append(line.strip())
            in_py_traceback = False
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
            result.frames.append(
                Frame(
                    path=ref_match.group("path"),
                    line=int(ref_match.group("line")),
                    function=ref_match.group("func"),
                    language="python",
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
            result.frames.append(
                Frame(
                    path=node_match.group("path"),
                    line=int(node_match.group("line")),
                    function=func.strip() if func else None,
                    language="node",
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
    return result
