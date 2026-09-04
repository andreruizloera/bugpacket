"""Stack-trace parsing against realistic Python, pytest, and Node output."""

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
