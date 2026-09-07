"""Compiler and build-error parsing for rustc, go build, and javac.

The tests named `*_real_capture` run against `examples/multilang/traces/`,
which is output captured from actually running those compilers on a broken
copy of the example projects (see `examples/multilang/record-traces.sh`). The
rest are hand-written shapes those particular failures did not produce:
warnings, cargo's tally lines, and the bare `error:` header that other tools
also print.
"""

from pathlib import Path

from bugpacket.stacktrace import parse_output

TRACES = Path(__file__).resolve().parents[1] / "examples" / "multilang" / "traces"


def load(name: str) -> str:
    return (TRACES / f"{name}.txt").read_text()


def located(text: str) -> list[tuple[str, int, str]]:
    return [(f.path, f.line, f.language) for f in parse_output(text).unique_frames()]


# ----------------------------------------------------------------- rustc ---


def test_rustc_real_capture_folds_the_caret_label_into_the_message():
    """The header alone says "mismatched types"; the label says which types."""
    parsed = parse_output(load("rust-compile-error"))
    assert parsed.diagnostics == [
        "error[E0308]: mismatched types: expected `&HashMap<String, u32>`, "
        "found `&HashMap<String, {float}>`"
    ]
    assert parsed.distilled_failure() == parsed.diagnostics[0]


def test_rustc_real_capture_keeps_both_files_the_diagnostic_named():
    """The second location comes from the `note: function defined here` block.

    It is the other half of the type error and the file an agent has to read
    to decide which side is wrong, so a reader that stopped at the primary
    span would drop it.
    """
    assert located(load("rust-compile-error")) == [
        ("src/main.rs", 10, "rust"),
        ("src/cart.rs", 10, "rust"),
    ]


def test_rustc_real_capture_produces_no_stack_frames_or_error_lines():
    parsed = parse_output(load("rust-compile-error"))
    assert parsed.error_lines == []
    assert parsed.failed_tests == []


def test_rustc_cargo_tally_lines_are_not_diagnostics():
    text = (
        "error[E0308]: mismatched types\n"
        "  --> src/main.rs:10:50\n"
        "\n"
        "error: aborting due to 1 previous error\n"
        'error: could not compile `shop` (bin "shop") due to 1 previous error\n'
    )
    assert parse_output(text).diagnostics == ["error[E0308]: mismatched types"]


def test_rustc_warning_locations_are_not_ranked():
    """A warning is not a failure, so its file must not enter the packet."""
    text = "warning: unused variable: `x`\n  --> src/unused.rs:3:9\n"
    parsed = parse_output(text)
    assert parsed.diagnostics == []
    assert parsed.unique_frames() == []


def test_rustc_real_capture_of_a_panic_swallows_its_warning_span():
    """The recorded panic starts with a dead-code warning and its `-->` line."""
    frames = [f.path for f in parse_output(load("rust-panic")).unique_frames()]
    assert "src/cart.rs" not in frames  # only the backtrace's ./src/cart.rs
    assert parse_output(load("rust-panic")).diagnostics == []


def test_a_bare_error_line_with_no_span_is_left_alone():
    """Plenty of tools print `error: ...`; only rustc follows it with a span.

    Claiming those would change what the packet calls the failure for every
    one of them, so a bare header only counts when a span follows it.
    """
    text = (
        "Traceback (most recent call last):\n"
        '  File "a.py", line 1, in f\n'
        "KeyError: 'k'\n"
        "error: build step failed\n"
    )
    parsed = parse_output(text)
    assert parsed.diagnostics == []
    assert parsed.distilled_failure() == "KeyError: 'k'"


def test_a_bare_error_line_followed_by_a_span_is_a_diagnostic():
    text = "error: expected one of `!` or `::`, found `fn`\n  --> src/lib.rs:4:1\n"
    parsed = parse_output(text)
    assert parsed.diagnostics == ["error: expected one of `!` or `::`, found `fn`"]
    assert located(text) == [("src/lib.rs", 4, "rust")]


# -------------------------------------------------------------- go build ---


def test_go_build_real_capture():
    parsed = parse_output(load("go-build-error"))
    assert parsed.diagnostics == [
        "cannot use coupon (variable of type map[string]float64) as "
        "map[string]int value in argument to cart.Checkout"
    ]
    assert located(load("go-build-error")) == [("./main.go", 12, "go")]


def test_go_test_failure_locations_still_belong_to_the_trace_reader():
    """`go test` indents its failure locations; `go build` starts at column 0.

    That indentation is the whole difference between the two, so a go test
    capture must still parse as a test failure and not as a build error.
    """
    parsed = parse_output(load("go-test"))
    assert parsed.diagnostics == []
    assert parsed.failed_test_names == ["TestApplyCouponPercentOff"]


# ----------------------------------------------------------------- javac ---


def test_javac_real_capture_reports_the_first_error_as_the_failure():
    """javac reported two; the second is a consequence of the first."""
    parsed = parse_output(load("javac-error"))
    assert parsed.diagnostics == [
        "incompatible types: Integer cannot be converted to String",
        "bad operand types for binary operator '*'",
    ]
    assert parsed.distilled_failure() == parsed.diagnostics[0]


def test_javac_real_capture_keeps_every_location():
    assert located(load("javac-error")) == [
        ("src/main/java/com/example/shop/Pricing.java", 8, "jvm"),
        ("src/main/java/com/example/shop/Pricing.java", 9, "jvm"),
    ]


def test_javac_warnings_are_not_diagnostics():
    text = (
        "src/Main.java:4: warning: [deprecation] readLine() in DataInputStream "
        "has been deprecated\n"
    )
    parsed = parse_output(text)
    assert parsed.diagnostics == []
    assert parsed.unique_frames() == []


def test_a_jvm_exception_is_not_read_as_a_javac_error():
    text = "java.lang.IllegalStateException: nope\n\tat com.example.App.run(App.java:8)\n"
    parsed = parse_output(text)
    assert parsed.diagnostics == []
    assert parsed.distilled_failure() == "java.lang.IllegalStateException: nope"
