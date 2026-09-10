"""Rust, Go, and JVM trace parsing.

The tests named `*_real_capture` run against `examples/multilang/traces/`,
which is output captured from actually running those toolchains (see
`examples/multilang/record-traces.sh`). The rest are hand-written variants of
formats those runs did not happen to produce: older release formats, JDK
frames, and shapes that need a specific failure to trigger.
"""

from pathlib import Path

import pytest

from bugpacket.dialects import is_vendored_path, jvm_path_hint
from bugpacket.stacktrace import parse_output

TRACES = Path(__file__).resolve().parents[1] / "examples" / "multilang" / "traces"


def load(name: str) -> str:
    return (TRACES / f"{name}.txt").read_text()


def frames_of(text: str, language: str):
    return [f for f in parse_output(text).unique_frames() if f.language == language]


# ------------------------------------------------------------------ Rust ---


def test_rust_real_capture_panic_location_and_message():
    parsed = parse_output(load("rust-panic"))
    assert parsed.distilled_failure() == "no entry found for key"
    first = frames_of(load("rust-panic"), "rust")[0]
    assert (first.path, first.line) == ("src/pricing.rs", 5)


def test_rust_real_capture_walks_the_backtrace_into_repository_code():
    frames = frames_of(load("rust-panic"), "rust")
    repo_frames = [(f.path, f.line, f.function) for f in frames if not f.vendored]
    assert repo_frames == [
        ("src/pricing.rs", 5, None),
        ("./src/cart.rs", 12, "shop::cart::checkout"),
        ("./src/main.rs", 10, "shop::main"),
    ]


def test_rust_real_capture_marks_standard_library_frames_vendored():
    vendored = [f.path for f in frames_of(load("rust-panic"), "rust") if f.vendored]
    assert len(vendored) == 3  # option.rs, map.rs, function.rs
    assert all("rustlib" in path for path in vendored)


def test_rust_real_capture_ignores_compiler_warning_noise():
    """The capture opens with a `warning:` block pointing at src/cart.rs:5."""
    assert "--> src/cart.rs:5:9" in load("rust-panic")
    assert not [
        f for f in frames_of(load("rust-panic"), "rust") if f.line == 5 and "cart" in f.path
    ]


def test_rust_panic_message_is_not_the_note_line():
    text = (
        "thread 'main' panicked at src/lib.rs:3:5:\n"
        "note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace\n"
    )
    parsed = parse_output(text)
    assert parsed.distilled_failure() != "note: run with `RUST_BACKTRACE=1` environment"
    assert parsed.unique_frames()[0].path == "src/lib.rs"


def test_rust_pre_1_73_panic_format_with_inline_message():
    text = "thread 'main' panicked at 'index out of bounds', src/main.rs:12:9\n"
    parsed = parse_output(text)
    assert parsed.distilled_failure() == "index out of bounds"
    frame = parsed.unique_frames()[0]
    assert (frame.path, frame.line, frame.language) == ("src/main.rs", 12, "rust")


def test_rust_real_capture_test_failure_name():
    parsed = parse_output("running 1 test\npricing::tests::percent_off_is_applied --- FAILED\n")
    assert parsed.failed_test_names == ["pricing::tests::percent_off_is_applied"]


def test_rust_older_libtest_failure_format():
    parsed = parse_output("test cart::tests::checkout_totals ... FAILED\n")
    assert parsed.failed_test_names == ["cart::tests::checkout_totals"]


def test_rust_backtrace_frame_is_not_read_as_a_node_frame():
    """`  at ./src/x.rs:5:25` has exactly the shape of a V8 frame."""
    text = "stack backtrace:\n   0: shop::boom\n             at ./src/boom.rs:5:25\n"
    frames = parse_output(text).unique_frames()
    assert [f.language for f in frames] == ["rust"]


# -------------------------------------------------------------------- Go ---


def test_go_real_capture_panic_message_and_frames():
    text = load("go-panic")
    parsed = parse_output(text)
    assert parsed.distilled_failure() == (
        "panic: runtime error: index out of range [2] with length 1"
    )
    frames = [(f.path, f.line, f.function) for f in parsed.unique_frames()]
    assert frames == [
        (
            "/private/tmp/bugpacket-build/shop/cart/cart.go",
            21,
            "github.com/example/shop/cart.Receipt",
        ),
        ("/private/tmp/bugpacket-build/shop/main.go", 13, "main.main"),
    ]


def test_go_real_capture_test_failure_names_test_and_file():
    parsed = parse_output(load("go-test"))
    assert parsed.failed_test_names == ["TestApplyCouponPercentOff"]
    assert parsed.distilled_failure() == "ApplyCoupon(1200, 10%) = 1200, want 1080"
    frame = parsed.unique_frames()[0]
    assert (frame.path, frame.line, frame.language) == ("pricing_test.go", 9, "go")


def test_go_fatal_error_is_captured_like_a_panic():
    text = (
        "fatal error: all goroutines are asleep - deadlock!\n"
        "\ngoroutine 1 [chan receive]:\n"
        "main.main()\n"
        "\t/src/main.go:9 +0x1c\n"
    )
    parsed = parse_output(text)
    assert parsed.distilled_failure() == ("fatal error: all goroutines are asleep - deadlock!")
    assert parsed.unique_frames()[0].path == "/src/main.go"


def test_go_frames_from_the_module_cache_are_vendored():
    text = (
        "panic: boom\n\ngoroutine 1 [running]:\n"
        "github.com/x/y.Do(...)\n"
        "\t/home/u/go/pkg/mod/github.com/x/y@v1.2.3/y.go:44 +0x10\n"
        "main.main()\n"
        "\t/src/main.go:9 +0x1c\n"
    )
    frames = parse_output(text).unique_frames()
    assert [f.vendored for f in frames] == [True, False]


def test_go_goroutine_block_ends_at_a_blank_line():
    text = "goroutine 1 [running]:\nmain.main()\n\t/src/main.go:9 +0x1c\n\nsome.other.output(1)\n"
    frames = parse_output(text).unique_frames()
    assert [f.path for f in frames] == ["/src/main.go"]


# ------------------------------------------------------------------- JVM ---


def test_jvm_real_capture_reports_the_root_cause_not_the_wrapper():
    parsed = parse_output(load("java-exception"))
    assert parsed.cause_chain[0].startswith("java.lang.IllegalStateException")
    assert parsed.root_cause.startswith("java.lang.NullPointerException")
    assert parsed.distilled_failure() == parsed.root_cause


def test_jvm_real_capture_frames_carry_package_hints():
    frames = frames_of(load("java-exception"), "jvm")
    assert [(f.path, f.line) for f in frames] == [
        ("Checkout.java", 11),
        ("Main.java", 10),
        ("Pricing.java", 8),
        ("Cart.java", 13),
        ("Checkout.java", 9),
    ]
    assert frames[2].path_hint == "com/example/shop/Pricing.java"


def test_jvm_single_exception_has_no_root_cause():
    """One exception is not a chain; there is nothing to unwrap."""
    text = (
        'Exception in thread "main" java.lang.IllegalArgumentException: bad\n'
        "\tat com.example.App.run(App.java:4)\n"
    )
    parsed = parse_output(text)
    assert parsed.root_cause is None
    assert parsed.distilled_failure() == "java.lang.IllegalArgumentException: bad"


def test_jvm_deepest_cause_wins_in_a_three_deep_chain():
    text = (
        'Exception in thread "main" com.example.OuterException: outer\n'
        "\tat com.example.A.run(A.java:1)\n"
        "Caused by: com.example.MiddleException: middle\n"
        "\tat com.example.B.run(B.java:2)\n"
        "Caused by: java.lang.NullPointerException: inner\n"
        "\tat com.example.C.run(C.java:3)\n"
        "\t... 2 more\n"
    )
    parsed = parse_output(text)
    assert len(parsed.cause_chain) == 3
    assert parsed.root_cause == "java.lang.NullPointerException: inner"


def test_jvm_frames_without_a_line_number_are_skipped():
    text = (
        "java.lang.RuntimeException: x\n"
        "\tat com.example.App.native(Native Method)\n"
        "\tat com.example.App.unknown(Unknown Source)\n"
        "\tat com.example.App.real(App.java:7)\n"
    )
    frames = parse_output(text).unique_frames()
    assert [(f.path, f.line) for f in frames] == [("App.java", 7)]


def test_jvm_module_prefixed_jdk_frames_are_vendored():
    text = (
        "java.lang.RuntimeException: x\n"
        "\tat java.base/java.util.HashMap.get(HashMap.java:568)\n"
        "\tat com.example.App.run(App.java:7)\n"
    )
    frames = parse_output(text).unique_frames()
    assert [(f.path, f.vendored) for f in frames] == [
        ("HashMap.java", True),
        ("App.java", False),
    ]


def test_jvm_jdk_frame_gets_no_package_hint():
    """Nothing should go looking for `java/util/HashMap.java` in a repository."""
    text = "java.lang.RuntimeException: x\n\tat java.util.HashMap.get(HashMap.java:568)\n"
    frame = parse_output(text).unique_frames()[0]
    assert frame.vendored is True
    assert frame.path_hint is None


def test_jvm_kotlin_and_scala_files_are_recognised():
    text = (
        "java.lang.IllegalStateException: x\n"
        "\tat com.example.Svc.handle(Svc.kt:22)\n"
        "\tat com.example.Job.run(Job.scala:8)\n"
    )
    frames = parse_output(text).unique_frames()
    assert [f.path for f in frames] == ["Svc.kt", "Job.scala"]


@pytest.mark.parametrize(
    ("fq", "file_name", "expected"),
    [
        ("com.example.shop.Pricing.applyCoupon", "Pricing.java", "com/example/shop/Pricing.java"),
        # An inner class still lives in the outer class's file, and the frame
        # says which file, so the class segment is dropped rather than used.
        ("com.example.Cart$1.run", "Cart.java", "com/example/Cart.java"),
        ("com.example.Foo.lambda$bar$0", "Foo.java", "com/example/Foo.java"),
        # No package at all: there is nothing better than the bare file name.
        ("Main.main", "Main.java", None),
        # An unconventional capitalised package is not turned into a directory.
        ("Com.Example.Foo.bar", "Foo.java", None),
    ],
)
def test_jvm_path_hint_cases(fq, file_name, expected):
    assert jvm_path_hint(fq, file_name) == expected


# ------------------------------------------------------- cross-dialect ---


def test_python_traceback_is_unaffected_by_the_new_dialects():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/app/main.py", line 10, in <module>\n'
        "    run()\n"
        "KeyError: 'user'\n"
    )
    parsed = parse_output(text)
    assert parsed.distilled_failure() == "KeyError: 'user'"
    assert parsed.cause_chain == []
    assert [f.language for f in parsed.unique_frames()] == ["python"]


def test_a_bare_python_error_is_not_read_as_a_jvm_header():
    """A JVM header must carry a package-qualified class name."""
    parsed = parse_output("ValueError: bad input\n")
    assert parsed.cause_chain == []
    assert parsed.root_cause is None
    assert parsed.distilled_failure() == "ValueError: bad input"


def test_node_frames_are_still_recognised():
    text = (
        "TypeError: cart.total is not a function\n"
        "    at applyDiscount (/app/src/checkout.js:12:22)\n"
        "    at Module._compile (node:internal/modules/cjs/loader:1358:14)\n"
    )
    frames = parse_output(text).unique_frames()
    assert [f.language for f in frames] == ["node", "node"]


def test_a_rust_path_is_not_claimed_by_the_node_frame_rule():
    """Outside a backtrace block, `at file.rs:1:1` is claimed by nobody."""
    frames = parse_output("    at ./src/thing.rs:1:1\n").unique_frames()
    assert [f.language for f in frames] != ["node"]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/home/u/go/pkg/mod/github.com/x/y@v1/y.go", True),
        ("/u/.cargo/registry/src/index/foo-1.0/src/lib.rs", True),
        ("/opt/rust/lib/rustlib/src/rust/library/core/src/option.rs", True),
        ("/app/node_modules/left-pad/index.js", True),
        ("/usr/lib/python3.12/site-packages/requests/api.py", True),
        ("src/pricing.rs", False),
        ("/home/u/project/cart/cart.go", False),
    ],
)
def test_vendor_marker_detection(path, expected):
    assert is_vendored_path(path) is expected


# ------------------------------------------------------- ordering controls ---
#
# Rust, Go and the JVM already print the failure site first WITHIN one stack,
# so grouping must leave their frame order exactly as captured. These run
# against the real captures so a regression shows up as a diff against
# toolchain output, not against a hand-written guess.


def test_rust_real_capture_order_is_unchanged_by_grouping():
    parsed = parse_output(load("rust-panic"))
    stacks = parsed.ordered_stacks()
    assert len(stacks) == 1
    assert [(f.path, f.line) for f in stacks[0].frames] == [
        (f.path, f.line) for f in parsed.unique_frames()
    ]
    assert stacks[0].frames[0].path == "src/pricing.rs"


def test_go_real_capture_panic_order_is_unchanged_by_grouping():
    parsed = parse_output(load("go-panic"))
    stacks = parsed.ordered_stacks()
    assert len(stacks) == 1
    assert [(f.path, f.line) for f in stacks[0].frames] == [
        (f.path, f.line) for f in parsed.unique_frames()
    ]
    assert stacks[0].frames[0].path.endswith("cart/cart.go")


def test_jvm_real_capture_leads_with_the_root_cause_frame():
    parsed = parse_output(load("java-exception"))
    stacks = parsed.ordered_stacks()
    assert len(stacks) == 2
    assert (stacks[0].frames[0].path, stacks[0].frames[0].line) == ("Pricing.java", 8)
    assert parsed.root_cause is not None
    assert parsed.root_cause.startswith("java.lang.NullPointerException")


def test_compiler_diagnostics_keep_first_error_first():
    """Diagnostics are not a stack and must never be reversed."""
    parsed = parse_output(load("javac-error"))
    stacks = parsed.ordered_stacks()
    assert len(stacks) == 1
    assert [(f.path, f.line) for f in stacks[0].frames] == [
        (f.path, f.line) for f in parsed.unique_frames()
    ]
