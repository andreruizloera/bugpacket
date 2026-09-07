"""Stack-trace parsers for Rust, Go, and JVM output.

Each dialect is a small state machine driven one line at a time by
`stacktrace.parse_output`. They are pure: text in, frames and failure lines
out, no filesystem and no subprocess. Resolving the paths they produce onto
real repository files is `resolve.py`'s job, and it has to be, because none of
these three runtimes prints a path a reader can just open:

- Rust prints paths relative to the crate root (`./src/pricing.rs`), plus
  standard-library paths pointing into the toolchain.
- Go prints the absolute path recorded when the binary was BUILT, and its test
  failures print a bare file name relative to the package directory.
- The JVM prints no directory at all, only `Pricing.java`.

Every regex here was written against output captured from a real run of the
toolchain in question, not from memory; the fixtures in
`tests/fixtures/traces/` are those captures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bugpacket.models import Frame

# Path segments that mean "this file belongs to a toolchain or a dependency,
# not to the repository being debugged". Each was taken from a real trace.
VENDOR_MARKERS = (
    "/.cargo/registry/",
    "/.rustup/",
    "/dist-packages/",
    "/go/pkg/mod/",
    "/node_modules/",
    "/rustlib/",
    "/site-packages/",
    "/usr/local/go/src/",
    "/usr/lib/go-",
)

# JVM platform modules; a frame from one of these is never repository code.
_JDK_MODULE_PREFIXES = ("java.", "jdk.", "javafx.", "sun.", "com.sun.")


def is_vendored_path(path: str) -> bool:
    """True when a trace path points into a toolchain or dependency tree."""
    normalized = path.replace("\\", "/")
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    if not normalized.endswith("/"):
        normalized += "/"
    return any(marker in normalized for marker in VENDOR_MARKERS)


# --------------------------------------------------------------------------
# Rust
# --------------------------------------------------------------------------

# Rust 1.73 and newer: the location is on the panic line and the message
# follows on the next line. Rust 1.87+ also prints a thread id in parens.
_RUST_PANIC_NEW_RE = re.compile(
    r"^thread '(?P<thread>[^']*)'(?: \(\d+\))? panicked at "
    r"(?P<path>[^\s:][^\s]*?):(?P<line>\d+):(?P<col>\d+):\s*$"
)

# Rust before 1.73: message quoted inline, location last.
_RUST_PANIC_OLD_RE = re.compile(
    r"^thread '(?P<thread>[^']*)' panicked at '(?P<msg>.*)', "
    r"(?P<path>[^\s:][^\s]*?):(?P<line>\d+):(?P<col>\d+)\s*$"
)

# A backtrace location line: `             at ./src/pricing.rs:5:25`
_RUST_BT_AT_RE = re.compile(r"^\s+at (?P<path>\S+?):(?P<line>\d+)(?::(?P<col>\d+))?\s*$")

# A backtrace frame header: `   5: shop::pricing::apply_coupon`
_RUST_BT_FRAME_RE = re.compile(r"^\s*(?P<idx>\d+):\s+(?P<func>\S.*?)\s*$")

# `pricing::tests::percent_off_is_applied --- FAILED` (current libtest) and
# `test pricing::tests::x ... FAILED` (older libtest).
_RUST_TEST_FAIL_RE = re.compile(
    r"^(?:test\s+)?(?P<test>[A-Za-z_][\w:]*)\s+(?:---|\.\.\.)\s+FAILED\s*$"
)


@dataclass
class RustState:
    in_backtrace: bool = False
    pending_function: str | None = None
    awaiting_message: bool = False


def feed_rust(line: str, state: RustState, out: ParsedLines) -> bool:
    """Consume one line as Rust output. Returns True if it was claimed."""
    if state.awaiting_message:
        state.awaiting_message = False
        text = line.strip()
        if text and not text.startswith("note:"):
            out.error_lines.append(text)
            return True

    match = _RUST_PANIC_NEW_RE.match(line)
    if match:
        out.frames.append(
            Frame(
                path=match.group("path"),
                line=int(match.group("line")),
                function=None,
                language="rust",
            )
        )
        state.awaiting_message = True
        state.in_backtrace = False
        return True

    match = _RUST_PANIC_OLD_RE.match(line)
    if match:
        out.frames.append(
            Frame(
                path=match.group("path"),
                line=int(match.group("line")),
                function=None,
                language="rust",
            )
        )
        out.error_lines.append(match.group("msg").strip())
        state.in_backtrace = False
        return True

    if line.strip() == "stack backtrace:":
        state.in_backtrace = True
        state.pending_function = None
        return True

    if state.in_backtrace:
        at_match = _RUST_BT_AT_RE.match(line)
        if at_match:
            path = at_match.group("path")
            out.frames.append(
                Frame(
                    path=path,
                    line=int(at_match.group("line")),
                    function=state.pending_function,
                    language="rust",
                    vendored=is_vendored_path(path),
                )
            )
            state.pending_function = None
            return True
        frame_match = _RUST_BT_FRAME_RE.match(line)
        if frame_match:
            state.pending_function = frame_match.group("func")
            return True
        if not line.strip() or line.startswith("note:"):
            state.in_backtrace = False
        return False

    match = _RUST_TEST_FAIL_RE.match(line)
    if match and "::" in match.group("test"):
        out.failed_test_names.append(match.group("test"))
        return True

    return False


# --------------------------------------------------------------------------
# Go
# --------------------------------------------------------------------------

_GO_PANIC_RE = re.compile(r"^(?P<kind>panic|fatal error):\s*(?P<msg>.*)$")

_GO_GOROUTINE_RE = re.compile(r"^goroutine \d+ \[[^\]]*\]:\s*$")

# `\t/build/src/cart/cart.go:21 +0x178`, the tab-indented location line that
# follows every function line inside a goroutine trace.
_GO_LOC_RE = re.compile(r"^\t(?P<path>\S.*?\.go):(?P<line>\d+)(?:\s+\+0x[0-9a-f]+)?\s*$")

# The function line above it: `github.com/example/shop/cart.Receipt(...)`
_GO_FUNC_RE = re.compile(r"^(?P<func>[\w./@*()\[\]-]+\.[\w.*()\[\]-]+)\((?P<args>.*)\)\s*$")

_GO_TEST_FAIL_RE = re.compile(r"^\s*--- FAIL: (?P<test>[^\s(]+)")

# `    pricing_test.go:9: ApplyCoupon(1200, 10%) = 1200, want 1080`
_GO_TEST_LOC_RE = re.compile(r"^\s{2,}(?P<path>[\w./-]+\.go):(?P<line>\d+): (?P<msg>\S.*)$")


@dataclass
class GoState:
    in_goroutine: bool = False
    pending_function: str | None = None


def feed_go(line: str, state: GoState, out: ParsedLines) -> bool:
    """Consume one line as Go output. Returns True if it was claimed."""
    if _GO_GOROUTINE_RE.match(line):
        state.in_goroutine = True
        state.pending_function = None
        return True

    if state.in_goroutine:
        loc_match = _GO_LOC_RE.match(line)
        if loc_match:
            path = loc_match.group("path")
            out.frames.append(
                Frame(
                    path=path,
                    line=int(loc_match.group("line")),
                    function=state.pending_function,
                    language="go",
                    vendored=is_vendored_path(path),
                )
            )
            state.pending_function = None
            return True
        func_match = _GO_FUNC_RE.match(line)
        if func_match:
            state.pending_function = func_match.group("func")
            return True
        if not line.strip():
            state.in_goroutine = False
            return False

    match = _GO_PANIC_RE.match(line)
    if match:
        message = match.group("msg").strip()
        if message:
            out.error_lines.append(f"{match.group('kind')}: {message}")
        return True

    match = _GO_TEST_FAIL_RE.match(line)
    if match:
        out.failed_test_names.append(match.group("test"))
        return True

    match = _GO_TEST_LOC_RE.match(line)
    if match:
        out.frames.append(
            Frame(
                path=match.group("path"),
                line=int(match.group("line")),
                function=None,
                language="go",
            )
        )
        out.error_lines.append(match.group("msg").strip())
        return True

    return False


# --------------------------------------------------------------------------
# JVM (Java, Kotlin, Scala; they all print this shape)
# --------------------------------------------------------------------------

_JVM_HEADER_RE = re.compile(
    r"^(?:Exception in thread \"[^\"]*\"\s+)?"
    r"(?P<cls>[a-z][\w.]*\.[\w$]*(?:Exception|Error|Throwable))"
    r"(?::\s?(?P<msg>.*))?$"
)

_JVM_CAUSED_BY_RE = re.compile(r"^Caused by:\s+(?P<cls>[\w.$]+)(?::\s?(?P<msg>.*))?$")

# `\tat com.example.shop.Pricing.applyCoupon(Pricing.java:8)`, optionally with
# a module or classloader prefix: `at java.base/java.util.Map.get(Map.java:1)`.
_JVM_FRAME_RE = re.compile(
    r"^\s+at\s+(?:(?P<module>[\w.@/-]+)/)?(?P<fq>[\w.$<>]+)\((?P<loc>[^)]*)\)\s*$"
)

_JVM_LOC_RE = re.compile(r"^(?P<file>[\w$-]+\.(?:java|kt|scala|groovy)):(?P<line>\d+)$")

_JVM_MORE_RE = re.compile(r"^\s+\.\.\.\s+\d+\s+more\s*$")


def jvm_path_hint(fq_method: str, file_name: str) -> str | None:
    """Turn `com.example.shop.Pricing.applyCoupon` + `Pricing.java` into a path.

    A JVM frame names no directory, but the fully-qualified method name carries
    the package, and by convention the package is the directory structure. The
    class segment is dropped in favour of the file name from the frame, because
    an inner class `Cart$1` still lives in `Cart.java` and the frame says so.
    """
    parts = fq_method.split(".")
    if len(parts) < 3:
        return None  # no package, so nothing better than the bare file name
    package = parts[:-2]  # drop the method and the class
    if not all(part and not part[0].isupper() for part in package):
        return None  # not a conventional lowercase package; do not guess
    return "/".join([*package, file_name])


@dataclass
class JvmState:
    seen_frame: bool = False
    seen_header: bool = False


def feed_jvm(line: str, state: JvmState, out: ParsedLines) -> bool:
    """Consume one line as JVM output. Returns True if it was claimed."""
    match = _JVM_FRAME_RE.match(line)
    if match:
        state.seen_frame = True
        loc = _JVM_LOC_RE.match(match.group("loc"))
        if loc:  # `Native Method` and `Unknown Source` carry no location
            file_name = loc.group("file")
            module = match.group("module") or ""
            fq = match.group("fq")
            vendored = module.startswith(_JDK_MODULE_PREFIXES) or fq.startswith(
                _JDK_MODULE_PREFIXES
            )
            out.frames.append(
                Frame(
                    path=file_name,
                    line=int(loc.group("line")),
                    function=fq,
                    language="jvm",
                    path_hint=None if vendored else jvm_path_hint(fq, file_name),
                    vendored=vendored,
                )
            )
        return True

    if _JVM_MORE_RE.match(line):
        return True

    match = _JVM_CAUSED_BY_RE.match(line)
    if match:
        text = match.group("cls")
        if match.group("msg"):
            text += f": {match.group('msg')}"
        out.error_lines.append(text)
        out.cause_chain.append(text)
        return True

    # A header must carry a package-qualified class name, so a bare Python
    # `KeyError: 'user'` is never mistaken for one.
    match = _JVM_HEADER_RE.match(line)
    if match:
        text = match.group("cls")
        if match.group("msg"):
            text += f": {match.group('msg')}"
        out.error_lines.append(text)
        out.cause_chain.append(text)
        state.seen_header = True
        return True
    return False


# --------------------------------------------------------------------------
# Shared accumulator
# --------------------------------------------------------------------------


@dataclass
class ParsedLines:
    """The mutable bag the dialect state machines append into.

    `stacktrace.ParsedOutput` is built from one of these; keeping the parsers
    writing to a plain accumulator is what lets each dialect stay a pure
    function of (line, its own state).
    """

    frames: list[Frame] = field(default_factory=list)
    error_lines: list[str] = field(default_factory=list)
    failed_test_names: list[str] = field(default_factory=list)
    cause_chain: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
