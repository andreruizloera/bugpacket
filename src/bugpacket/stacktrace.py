"""Parse Python and Node/V8 stack traces out of raw command output.

Handles three shapes:
- standard CPython tracebacks (`Traceback (most recent call last):` blocks)
- pytest-style tracebacks (`path.py:12: in test_x` refs and `E   Error: msg` lines)
- Node/V8 stacks (`    at func (path.js:3:11)` frames)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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


@dataclass
class ParsedOutput:
    """Everything the parser could extract from a command's combined output."""

    frames: list[Frame] = field(default_factory=list)
    error_lines: list[str] = field(default_factory=list)
    pytest_error_lines: list[str] = field(default_factory=list)
    failed_tests: list[tuple[str, str]] = field(default_factory=list)  # (path, test id)

    def distilled_failure(self) -> str | None:
        """The single most useful description of what went wrong."""
        if self.error_lines:
            return self.error_lines[-1]
        if self.pytest_error_lines:
            return self.pytest_error_lines[-1]
        if self.failed_tests:
            path, test = self.failed_tests[-1]
            return f"Test failed: {path}::{test}"
        return None

    def unique_frames(self) -> list[Frame]:
        """Frames in order of appearance, deduplicated on (path, line)."""
        seen: set[tuple[str, int]] = set()
        out: list[Frame] = []
        for frame in self.frames:
            key = (frame.path, frame.line)
            if key not in seen:
                seen.add(key)
                out.append(frame)
        return out


def _looks_like_node_path(path: str) -> bool:
    return not path.endswith((".py", ".pyw", ".pyi"))


def parse_output(text: str) -> ParsedOutput:
    """Parse command output for stack traces, error lines, and failed tests."""
    result = ParsedOutput()
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

    return result
