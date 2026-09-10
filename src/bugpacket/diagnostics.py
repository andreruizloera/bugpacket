"""Compiler and build-error parsers for rustc, go build, and javac.

A build that fails to compile produces no stack trace at all, so everything in
`stacktrace.py` and `dialects.py` reads nothing from it. What it produces
instead is a diagnostic: a level, a message, and one or more source locations.
That is enough to build a packet from, and the locations are exactly the files
an agent needs, so they feed the same ranking a trace frame does.

Three differences from a trace shape the code here:

- A compiler reports its FIRST error first, and the errors after it are
  usually consequences of it. A traceback is the other way round: the last
  line is the exception. So diagnostics are kept in their own list and the
  first one is the failure, rather than the last.
- Warnings look exactly like errors and are not failures. Their locations must
  not be ranked into the packet, so the level is tracked and warning spans are
  swallowed.
- rustc puts the useful sentence in the label under the carets
  (``expected `u32`, found `String```), not in the header line, so the first
  primary label is folded into the message.

Every regex here was written against output captured from a real run of the
toolchain, not from memory; `examples/multilang/traces/` holds those captures
and `examples/multilang/record-traces.sh` is how they were produced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bugpacket.dialects import ParsedLines, is_vendored_path
from bugpacket.models import Frame

# `error[E0308]: mismatched types`, `warning: unused variable: `x``.
_RUSTC_DIAG_RE = re.compile(
    r"^(?P<level>error|warning)(?:\[(?P<code>[A-Z]\d{4})\])?: (?P<msg>\S.*?)\s*$"
)

# `  --> src/main.rs:10:50`, and `  ::: src/cart.rs:3:1` for a secondary file.
_RUSTC_SPAN_RE = re.compile(r"^\s*(?:-->|:::) (?P<path>\S+?):(?P<line>\d+):(?P<col>\d+)\s*$")

# The label under the carets. Secondary spans on the same line are underlined
# with dashes, so the carets are not necessarily first:
# `   |            --------------         ^^^^^^^ expected `&HashMap<..>``
_RUSTC_LABEL_RE = re.compile(r"^\s*\|[^|]*\^+ (?P<label>\S.*?)\s*$")

# cargo's own tally lines, which name no location and add nothing.
_RUSTC_SUMMARY_RE = re.compile(r"^(?:aborting due to|could not compile\b)")

# `./main.go:12:45: cannot use coupon (variable of type map[string]float64) ...`
# Anchored at column zero, which is what keeps it off `go test`'s indented
# failure locations; those are already `dialects.feed_go`'s.
_GO_BUILD_RE = re.compile(
    r"^(?P<path>\.{0,2}/?[\w./-]+\.go):(?P<line>\d+)(?::(?P<col>\d+))?: (?P<msg>\S.*?)\s*$"
)

# `src/main/java/com/example/shop/Pricing.java:8: error: incompatible types: ...`
_JAVAC_RE = re.compile(
    r"^(?P<path>[\w./$-]+\.(?:java|kt|scala)):(?P<line>\d+): "
    r"(?P<level>error|warning): (?P<msg>\S.*?)\s*$"
)


@dataclass
class DiagnosticState:
    """What the rustc reader needs to carry between lines.

    go build and javac each print one self-contained line per diagnostic, so
    only rustc, whose diagnostic is a block, needs any state at all.
    """

    level: str | None = None
    """Level of the rustc diagnostic being read, so its spans are attributed."""
    message_index: int | None = None
    """Where in `out.diagnostics` the current error's message went."""
    label_taken: bool = False
    """The first primary label has already been folded into that message."""
    pending: tuple[str, str] | None = None
    """A bare `error:`/`warning:` header waiting to see a span on the next line.

    A header with a code (`error[E0308]:`) is unmistakably rustc. A bare one is
    not: plenty of tools print `error: something`. Claiming those would change
    what the packet reports as the failure for every such tool, so a bare
    header only becomes a diagnostic when a rustc span follows it.
    """


def _record(out: ParsedLines, path: str, line: int, language: str) -> None:
    if out.diagnostic_block is None:
        out.diagnostic_block = out.open_block(
            language, innermost_first=True, label="compiler diagnostics"
        )
    out.frames.append(
        Frame(
            path=path,
            line=line,
            function=None,
            language=language,
            vendored=is_vendored_path(path),
            block=out.diagnostic_block,
        )
    )


def _feed_rustc(line: str, state: DiagnosticState, out: ParsedLines) -> bool:
    pending, state.pending = state.pending, None

    span = _RUSTC_SPAN_RE.match(line)
    if span:
        if pending is not None:
            _open(state, out, pending[0], pending[1])
        if state.level is None:
            return False
        if state.level == "error":
            _record(out, span.group("path"), int(span.group("line")), "rust")
        return True

    header = _RUSTC_DIAG_RE.match(line)
    if header:
        level, code = header.group("level"), header.group("code")
        message = header.group("msg")
        if code is None:
            if level == "error" and _RUSTC_SUMMARY_RE.match(message):
                state.level = None
                state.message_index = None
                return True
            state.pending = (level, f"{level}: {message}")
            return False
        _open(state, out, level, f"{level}[{code}]: {message}")
        return True

    if state.level == "error" and state.message_index is not None and not state.label_taken:
        label = _RUSTC_LABEL_RE.match(line)
        if label is not None and label.group("label").strip("- "):
            out.diagnostics[state.message_index] += f": {label.group('label')}"
            state.label_taken = True
            return True
    return False


def _open(state: DiagnosticState, out: ParsedLines, level: str, message: str) -> None:
    """Start reading a new rustc diagnostic at `level`."""
    state.level = level
    state.message_index = None
    state.label_taken = False
    if level == "error":
        out.diagnostics.append(message)
        state.message_index = len(out.diagnostics) - 1


def _feed_go_build(line: str, out: ParsedLines) -> bool:
    match = _GO_BUILD_RE.match(line)
    if match is None:
        return False
    out.diagnostics.append(match.group("msg"))
    _record(out, match.group("path"), int(match.group("line")), "go")
    return True


def _feed_javac(line: str, out: ParsedLines) -> bool:
    match = _JAVAC_RE.match(line)
    if match is None:
        return False
    if match.group("level") == "error":
        out.diagnostics.append(match.group("msg"))
        _record(out, match.group("path"), int(match.group("line")), "jvm")
    return True


def feed_diagnostic(line: str, state: DiagnosticState, out: ParsedLines) -> bool:
    """Consume one line as compiler output. Returns True if it was claimed."""
    return _feed_rustc(line, state, out) or _feed_go_build(line, out) or _feed_javac(line, out)
