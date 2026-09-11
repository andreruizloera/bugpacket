"""Stack-trace parsing against realistic Python, pytest, and Node output."""

import subprocess
import sys
from pathlib import Path

import pytest

from bugpacket.stacktrace import parse_output

PYTHON_TRACEBACK = """\
Traceback (most recent call last):
  File "/app/main.py", line 10, in <module>
    run()
  File "/app/lib/runner.py", line 42, in run
    result = handler(payload)
  File "/app/lib/handlers.py", line 7, in handler
    return payload["user"]["id"]
KeyError: 'user'
"""

PYTEST_OUTPUT = """\
=================================== FAILURES ===================================
__________________________________ test_total __________________________________

    def test_total():
>       assert checkout() == 1
E       AssertionError: assert 2 == 1

tests/test_totals.py:12: AssertionError
=========================== short test summary info ============================
FAILED tests/test_totals.py::test_total - AssertionError: assert 2 == 1
"""

NODE_OUTPUT = """\
/app/src/checkout.js:12
  const total = cart.total();
                     ^

TypeError: cart.total is not a function
    at applyDiscount (/app/src/checkout.js:12:22)
    at Object.<anonymous> (/app/src/index.js:3:1)
    at Module._compile (node:internal/modules/cjs/loader:1358:14)
"""


def test_python_traceback_frames():
    parsed = parse_output(PYTHON_TRACEBACK)
    frames = parsed.unique_frames()
    assert [(f.path, f.line, f.function) for f in frames] == [
        ("/app/main.py", 10, "<module>"),
        ("/app/lib/runner.py", 42, "run"),
        ("/app/lib/handlers.py", 7, "handler"),
    ]
    assert all(f.language == "python" for f in frames)


def test_python_traceback_error_and_distilled():
    parsed = parse_output(PYTHON_TRACEBACK)
    assert parsed.error_lines[-1] == "KeyError: 'user'"
    assert parsed.distilled_failure() == "KeyError: 'user'"


def test_pytest_style_output():
    parsed = parse_output(PYTEST_OUTPUT)
    frames = parsed.unique_frames()
    assert ("tests/test_totals.py", 12) in [(f.path, f.line) for f in frames]
    assert parsed.failed_tests == [("tests/test_totals.py", "test_total")]
    assert parsed.distilled_failure() == "AssertionError: assert 2 == 1"


def test_node_frames():
    parsed = parse_output(NODE_OUTPUT)
    frames = parsed.unique_frames()
    assert frames[0].path == "/app/src/checkout.js"
    assert frames[0].line == 12
    assert frames[0].function == "applyDiscount"
    assert frames[0].language == "node"
    assert frames[1].function == "Object.<anonymous>"
    assert parsed.distilled_failure() == "TypeError: cart.total is not a function"


def test_frames_deduplicated_in_order():
    doubled = PYTHON_TRACEBACK + PYTHON_TRACEBACK
    parsed = parse_output(doubled)
    assert len(parsed.frames) == 6
    assert len(parsed.unique_frames()) == 3


def test_no_traces_means_no_failure():
    parsed = parse_output("all 12 tests passed\n")
    assert parsed.unique_frames() == []
    assert parsed.distilled_failure() is None


# ---------------------------------------------------------------------------
# Stack ordering.
#
# `unique_frames` answers "which files did this failure touch", which is what
# ranking needs. `ordered_stacks` answers "what should a reader read first",
# which is a different question, and the two disagree on purpose.
# ---------------------------------------------------------------------------

PYTEST_TWO_FAILURES = """\
=================================== FAILURES ===================================
________________________ test_total_with_percent_coupon ________________________

    def test_total_with_percent_coupon():
>       assert make_cart().checkout(coupon) == 2787

tests/test_payment.py:19:\x20
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
shop/cart.py:30: in checkout
    return total_cents(self._items, coupon)
shop/payment.py:25: in total_cents
    amount = apply_coupon(amount, coupon)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    def apply_coupon(amount_cents: int, coupon: dict) -> int:
>       percent = coupon["percentage"]
E       KeyError: 'percentage'

shop/payment.py:15: KeyError
___________________ test_bigger_coupon_never_increases_total ___________________

    def test_bigger_coupon_never_increases_total():
>       small = make_cart().checkout({"code": "SAVE10", "percent": 10})

tests/test_payment.py:23:\x20
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
shop/cart.py:30: in checkout
    return total_cents(self._items, coupon)
shop/payment.py:25: in total_cents
    amount = apply_coupon(amount, coupon)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    def apply_coupon(amount_cents: int, coupon: dict) -> int:
>       percent = coupon["percentage"]
E       KeyError: 'percentage'

shop/payment.py:15: KeyError
=========================== short test summary info ============================
FAILED tests/test_payment.py::test_total_with_percent_coupon - KeyError
FAILED tests/test_payment.py::test_bigger_coupon_never_increases_total - KeyError
"""

JVM_CAUSED_BY = """\
Exception in thread "main" java.lang.IllegalStateException: checkout failed
\tat com.example.shop.Checkout.run(Checkout.java:11)
\tat com.example.shop.Main.main(Main.java:10)
Caused by: java.lang.NullPointerException: coupon was null
\tat com.example.shop.Pricing.applyCoupon(Pricing.java:8)
\tat com.example.shop.Cart.checkout(Cart.java:13)
\t... 1 more
"""


def _paths(stack):
    return [(f.path, f.line) for f in stack.frames]


def test_cpython_traceback_reads_innermost_first():
    """`most recent call last` means the raise site is printed at the bottom."""
    stacks = parse_output(PYTHON_TRACEBACK).ordered_stacks()
    assert len(stacks) == 1
    assert _paths(stacks[0]) == [
        ("/app/lib/handlers.py", 7),
        ("/app/lib/runner.py", 42),
        ("/app/main.py", 10),
    ]


def test_pytest_traceback_reads_innermost_first():
    stacks = parse_output(PYTEST_OUTPUT).ordered_stacks()
    assert len(stacks) == 1
    assert stacks[0].frames[0].path == "tests/test_totals.py"


def test_two_failing_tests_are_two_stacks_not_one():
    """Flattening them produced a list whose last entry was another stack's top."""
    stacks = parse_output(PYTEST_TWO_FAILURES).ordered_stacks()
    assert len(stacks) == 2
    assert [s.block.label for s in stacks] == [
        "test_total_with_percent_coupon",
        "test_bigger_coupon_never_increases_total",
    ]


def test_each_failing_test_keeps_the_frames_it_shares_with_the_other():
    """Deduplicating across stacks left the second one a stump."""
    stacks = parse_output(PYTEST_TWO_FAILURES).ordered_stacks()
    assert _paths(stacks[0]) == [
        ("shop/payment.py", 15),
        ("shop/payment.py", 25),
        ("shop/cart.py", 30),
        ("tests/test_payment.py", 19),
    ]
    assert _paths(stacks[1]) == [
        ("shop/payment.py", 15),
        ("shop/payment.py", 25),
        ("shop/cart.py", 30),
        ("tests/test_payment.py", 23),
    ]


def test_every_stack_leads_with_the_line_that_raised():
    for stack in parse_output(PYTEST_TWO_FAILURES).ordered_stacks():
        assert stack.frames[0].path == "shop/payment.py"
        assert stack.frames[0].line == 15


def test_unique_frames_still_dedupes_across_stacks_for_ranking():
    """Ranking wants the file set, so this side must NOT change."""
    parsed = parse_output(PYTEST_TWO_FAILURES)
    assert [(f.path, f.line) for f in parsed.unique_frames()] == [
        ("tests/test_payment.py", 19),
        ("shop/cart.py", 30),
        ("shop/payment.py", 25),
        ("shop/payment.py", 15),
        ("tests/test_payment.py", 23),
    ]


def test_jvm_caused_by_chain_puts_the_root_cause_stack_first():
    """The JVM prints the wrapper first; `root_cause` calls the wrapper wrong."""
    stacks = parse_output(JVM_CAUSED_BY).ordered_stacks()
    assert len(stacks) == 2
    assert stacks[0].block.label == "java.lang.NullPointerException"
    assert stacks[1].block.label == "java.lang.IllegalStateException"


def test_jvm_top_frame_agrees_with_the_root_cause_the_packet_names():
    """The defect: the prose named the NPE and the stack led with the rethrow."""
    parsed = parse_output(JVM_CAUSED_BY)
    assert parsed.root_cause == "java.lang.NullPointerException: coupon was null"
    top = parsed.ordered_stacks()[0].frames[0]
    assert (top.path, top.line) == ("Pricing.java", 8)


def test_reversing_direction_alone_would_not_have_fixed_the_jvm():
    """Both printed directions bury the root-cause frame in the middle.

    This is why the fix is per-block grouping and not a global flip.
    """
    parsed = parse_output(JVM_CAUSED_BY)
    flat = [(f.path, f.line) for f in parsed.unique_frames()]
    assert flat.index(("Pricing.java", 8)) == 2
    assert list(reversed(flat)).index(("Pricing.java", 8)) == 1
    assert len(flat) == 4


def test_two_unrelated_jvm_exceptions_keep_their_printed_order():
    """Only a `Caused by:` run reverses. Two separate throws are not a chain."""
    text = (
        'Exception in thread "one" com.example.FirstException: first\n'
        "\tat com.example.A.run(A.java:1)\n"
        'Exception in thread "two" com.example.SecondException: second\n'
        "\tat com.example.B.run(B.java:2)\n"
    )
    stacks = parse_output(text).ordered_stacks()
    assert [s.block.label for s in stacks] == [
        "com.example.FirstException",
        "com.example.SecondException",
    ]


def test_three_deep_jvm_chain_reverses_all_the_way_down():
    text = (
        'Exception in thread "main" com.example.OuterException: outer\n'
        "\tat com.example.A.run(A.java:1)\n"
        "Caused by: com.example.MiddleException: middle\n"
        "\tat com.example.B.run(B.java:2)\n"
        "Caused by: java.lang.NullPointerException: inner\n"
        "\tat com.example.C.run(C.java:3)\n"
    )
    stacks = parse_output(text).ordered_stacks()
    assert [s.frames[0].path for s in stacks] == ["C.java", "B.java", "A.java"]


def test_node_stack_is_left_alone_because_v8_already_leads_with_the_throw():
    stacks = parse_output(NODE_OUTPUT).ordered_stacks()
    assert len(stacks) == 1
    assert _paths(stacks[0]) == [
        ("/app/src/checkout.js", 12),
        ("/app/src/index.js", 3),
        ("node:internal/modules/cjs/loader", 1358),
    ]


# ---------------------------------------------------------------------------
# CPython exception chains.
#
# These run against `examples/multilang/traces/python-*-chain.txt`, which is
# output CPython actually printed (see `examples/multilang/record-traces.sh`),
# and `test_the_recorded_chains_still_match_what_cpython_prints` re-runs the
# example live so a fixture cannot quietly stop being true.
#
# The two separator lines CPython prints between chained tracebacks look alike
# and mean opposite things, and before this the parser had never heard of
# either. Measured on the shipped code, that left each shape wrong on exactly
# one of the two axes: `raise X from Y` ordered its stacks right and reported
# the RETHROW as the failure, and `During handling` reported the failure right
# and ordered its stacks backwards.
# ---------------------------------------------------------------------------

CHAINS = Path(__file__).resolve().parents[1] / "examples" / "multilang" / "traces"
EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "multilang" / "python"


def chain(name: str) -> str:
    return (CHAINS / f"python-{name}-chain.txt").read_text()


def _shape(parsed):
    """(chain link per block, leading function of each stack), for comparison."""
    stacks = parsed.ordered_stacks()
    return (
        [s.block.chain for s in stacks],
        [s.frames[0].function for s in stacks],
        parsed.distilled_failure(),
    )


def test_direct_cause_chain_reports_the_cause_not_the_rethrow():
    """`error_lines[-1]` is the wrapper, which is the JVM bug in Python clothes."""
    parsed = parse_output(chain("cause"))
    assert parsed.root_cause == "KeyError: 'GBP'"
    assert parsed.distilled_failure() == "KeyError: 'GBP'"
    assert parsed.cause_chain == [
        "LookupError: no exchange rate for GBP",
        "KeyError: 'GBP'",
    ]


def test_direct_cause_chain_keeps_cpython_printed_order():
    """CPython prints the cause first, so this run is the one NOT reversed."""
    parsed = parse_output(chain("cause"))
    stacks = parsed.ordered_stacks()
    assert [s.block.chain for s in stacks] == ["", "wrapped"]
    assert stacks[0].frames[0].function == "rate_for"
    assert stacks[1].frames[0].function == "convert_cents"


def test_handling_chain_leads_with_the_exception_that_actually_escaped():
    """`During handling` is not a cause link: the LAST traceback is the failure."""
    parsed = parse_output(chain("context"))
    stacks = parsed.ordered_stacks()
    assert [s.block.chain for s in stacks] == ["context", ""]
    assert stacks[0].frames[0].function == "fallback_line"
    assert stacks[1].frames[0].function == "rate_for"


def test_handling_chain_is_not_a_cause_chain():
    """Calling it one would report the KeyError, which nothing is asking about."""
    parsed = parse_output(chain("context"))
    assert parsed.cause_chain == []
    assert parsed.root_cause is None
    assert parsed.distilled_failure() == (
        'TypeError: can only concatenate str (not "NoneType") to str'
    )


def test_the_two_separators_are_not_interchangeable():
    """The defect in one sentence: identical treatment, opposite meanings."""
    cause, context = parse_output(chain("cause")), parse_output(chain("context"))
    assert [s.block.chain for s in cause.ordered_stacks()] == ["", "wrapped"]
    assert [s.block.chain for s in context.ordered_stacks()] == ["context", ""]
    assert cause.root_cause is not None and context.root_cause is None


def test_both_separators_in_one_output_cut_at_the_handling_link():
    """A cause chain that was itself being handled is background, not the bug."""
    parsed = parse_output(chain("both"))
    stacks = parsed.ordered_stacks()
    assert [s.block.chain for s in stacks] == ["context", "", "wrapped"]
    assert stacks[0].frames[0].function == "fallback_line"
    # The background keeps CPython's order, cause before rethrow: `rate_for`
    # raised the KeyError and `convert_cents` is the line that wrapped it.
    assert [s.frames[0].function for s in stacks[1:]] == ["rate_for", "convert_cents"]
    assert parsed.cause_chain == []
    assert parsed.distilled_failure() == (
        'TypeError: can only concatenate str (not "NoneType") to str'
    )


def test_an_unchained_second_traceback_is_not_reordered():
    """Two unrelated tracebacks in one log are two failures, not a chain."""
    text = chain("cause").replace(
        "The above exception was the direct cause of the following exception:",
        "the next command also failed:",
    )
    stacks = parse_output(text).ordered_stacks()
    assert [s.block.chain for s in stacks] == ["", ""]
    assert [s.frames[0].function for s in stacks] == ["rate_for", "convert_cents"]
    assert parse_output(text).cause_chain == []


@pytest.mark.parametrize("shape", ["cause", "context", "both"])
def test_the_recorded_chains_still_match_what_cpython_prints(shape):
    """Re-run the example and parse the live output.

    Paths and line numbers differ between the recording directory and this
    one, so the recorded TEXT cannot be compared. What must match is every
    conclusion drawn from it, which is the part a fixture going stale would
    silently change.
    """
    result = subprocess.run(
        [sys.executable, "chained.py", shape],
        cwd=EXAMPLE,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert _shape(parse_output(result.stderr)) == _shape(parse_output(chain(shape)))


def test_each_traceback_in_a_chain_is_labelled_with_its_exception():
    """Unlabelled, two stacks print as one whose middle never called itself."""
    stacks = parse_output(chain("cause")).ordered_stacks()
    assert [s.block.label for s in stacks] == [
        "KeyError: 'GBP'",
        "LookupError: no exchange rate for GBP",
    ]


def test_a_lone_traceback_is_not_labelled():
    """There is nothing to tell it apart from, so a header would be noise."""
    stacks = parse_output(PYTHON_TRACEBACK).ordered_stacks()
    assert [s.block.label for s in stacks] == [""]


def test_labelling_does_not_overwrite_a_pytest_test_name():
    stacks = parse_output(PYTEST_TWO_FAILURES).ordered_stacks()
    assert [s.block.label for s in stacks] == [
        "test_total_with_percent_coupon",
        "test_bigger_coupon_never_increases_total",
    ]
