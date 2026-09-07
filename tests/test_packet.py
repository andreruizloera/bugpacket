"""packet.md structure, budget behavior, and output writing."""

import json
from pathlib import Path

from bugpacket.environment import capture_environment
from bugpacket.models import RankedFile
from bugpacket.packet import render_markdown, select_files, write_packet
from bugpacket.resolve import FrameResolver
from bugpacket.stacktrace import parse_output

SECTIONS = [
    "# BugPacket",
    "## Failure",
    "## Reproduction",
    "## Relevant stack",
    "## Relevant files",
    "## Current diff",
    "## Environment",
]

TRACEBACK = """\
Traceback (most recent call last):
  File "app.py", line 2, in <module>
    boom()
  File "app.py", line 5, in boom
    raise ValueError("bad input")
ValueError: bad input
"""


def make_repo(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text("def boom():\n    raise ValueError('bad input')\n")
    return tmp_path


def build(tmp_path: Path, budget: int = 8000):
    repo = make_repo(tmp_path)
    parsed = parse_output(TRACEBACK)
    ranked = [RankedFile(path=repo / "app.py", rel="app.py", rank=1, lines={2, 5})]
    return write_packet(
        out_dir=repo / ".bugpacket",
        command=["python", "app.py"],
        exit_code=1,
        stdout="",
        stderr=TRACEBACK,
        parsed=parsed,
        ranked=ranked,
        git=None,
        environment=capture_environment({"HOME": "/x", "MY_TOKEN": "secret-value"}),
        repo_root=repo,
        cwd=repo,
        budget_tokens=budget,
    )


def test_sections_present_in_order(tmp_path):
    result = build(tmp_path)
    text = (result.out_dir / "packet.md").read_text()
    positions = [text.index(section) for section in SECTIONS]
    assert positions == sorted(positions)


def test_packet_contents(tmp_path):
    result = build(tmp_path)
    text = (result.out_dir / "packet.md").read_text()
    assert "ValueError: bad input" in text
    assert "$ python app.py" in text
    assert "exit code: 1" in text
    assert "app.py:5 in boom" in text
    assert "rank 1: stack trace" in text
    assert "Not a git repository." in text
    assert "secret-value" not in text
    assert "MY_TOKEN" not in text


def test_files_and_json_written(tmp_path):
    result = build(tmp_path)
    assert (result.out_dir / "files" / "app.py").is_file()
    doc = json.loads((result.out_dir / "packet.json").read_text())
    assert doc["exit_code"] == 1
    assert doc["failure"] == "ValueError: bad input"
    assert doc["files"][0]["path"] == "app.py"
    assert "estimates" in doc["token_stats"]["note"]
    assert doc["token_stats"]["packet_tokens_estimated"] == result.packet_tokens


def test_budget_whole_then_trim_then_omit(tmp_path):
    small = tmp_path / "small.py"
    small.write_text("a" * 400)  # ~100 tokens
    big = tmp_path / "big.py"
    big.write_text("line = 1\n" * 3000)  # ~6750 tokens
    extra = tmp_path / "extra.py"
    extra.write_text("b" * 2000)  # ~500 tokens: too big for what remains
    ranked = [
        RankedFile(path=small, rel="small.py", rank=1),
        RankedFile(path=big, rel="big.py", rank=2, lines={10}),
        RankedFile(path=extra, rel="extra.py", rank=4),
    ]
    included, omitted = select_files(ranked, budget_tokens=450)
    assert [i.ranked.rel for i in included] == ["small.py", "big.py"]
    assert not included[0].trimmed
    assert included[1].trimmed
    assert included[1].content.endswith("[trimmed by bugpacket to fit the token budget]")
    assert [o.rel for o in omitted] == ["extra.py"]


def test_trimmed_file_marked_in_markdown(tmp_path):
    repo = make_repo(tmp_path)
    big = repo / "big.py"
    big.write_text("line = 1\n" * 3000)
    parsed = parse_output(TRACEBACK)
    ranked = [RankedFile(path=big, rel="big.py", rank=1, lines={100})]
    markdown = render_markdown(
        command=["python", "app.py"],
        exit_code=1,
        parsed=parsed,
        included=select_files(ranked, 600)[0],
        omitted=[],
        git=None,
        environment=capture_environment({"HOME": "/x"}),
        repo_root=repo,
        resolver=FrameResolver(repo_root=repo, cwd=repo),
    )
    assert "trimmed to fit budget" in markdown


JVM_TRACE = """\
Exception in thread "main" java.lang.IllegalStateException: checkout failed
\tat com.example.shop.Checkout.run(Checkout.java:11)
Caused by: java.lang.NullPointerException: coupon was null
\tat com.example.shop.Pricing.applyCoupon(Pricing.java:8)
\t... 1 more
"""


def make_java_repo(tmp_path: Path) -> Path:
    target = tmp_path / "src/main/java/com/example/shop/Pricing.java"
    target.parent.mkdir(parents=True)
    target.write_text("package com.example.shop;\n")
    (target.parent / "Checkout.java").write_text("package com.example.shop;\n")
    return tmp_path


def render(repo: Path, parsed, included=(), omitted=()):
    return render_markdown(
        command=["java", "-cp", "out", "com.example.shop.Main"],
        exit_code=1,
        parsed=parsed,
        included=list(included),
        omitted=list(omitted),
        git=None,
        environment=capture_environment({"HOME": "/x"}),
        repo_root=repo,
        resolver=FrameResolver(repo_root=repo, cwd=repo),
    )


def test_markdown_reports_root_cause_and_names_the_wrapper():
    repo = Path(__file__).parent
    text = render(repo, parse_output(JVM_TRACE))
    assert "java.lang.NullPointerException: coupon was null" in text
    assert "root cause of a chain of 2 exceptions" in text
    assert "java.lang.IllegalStateException: checkout failed" in text
    # The wrapper must not be presented as the failure itself.
    assert text.index("NullPointerException") < text.index("IllegalStateException")


def test_markdown_marks_a_frame_that_was_matched_by_file_name(tmp_path):
    repo = make_java_repo(tmp_path)
    text = render(repo, parse_output(JVM_TRACE))
    assert "src/main/java/com/example/shop/Pricing.java:8" in text
    assert "(jvm)" in text
    assert "[matched by file name; the trace gave no usable path]" in text


def test_markdown_names_the_candidates_of_an_ambiguous_frame(tmp_path):
    for pkg in ("alpha", "beta"):
        (tmp_path / pkg).mkdir()
        (tmp_path / pkg / "Pricing.java").write_text("class Pricing {}\n")
    trace = "java.lang.RuntimeException: x\n\tat Pricing.applyCoupon(Pricing.java:8)\n"
    text = render(tmp_path, parse_output(trace))
    assert "matched several files and was not included" in text
    assert "alpha/Pricing.java" in text
    assert "beta/Pricing.java" in text


def test_markdown_distinguishes_no_trace_from_an_unplaceable_trace(tmp_path):
    empty = render(tmp_path, parse_output("just some output\n"))
    assert "No stack trace detected in the output." in empty

    trace = "java.lang.RuntimeException: x\n\tat com.other.App.run(Nowhere.java:8)\n"
    unplaced = render(tmp_path, parse_output(trace))
    assert "A stack trace was parsed, but none of its frames" in unplaced


def test_json_records_how_each_frame_was_resolved(tmp_path):
    repo = make_java_repo(tmp_path)
    parsed = parse_output(JVM_TRACE)
    result = write_packet(
        out_dir=repo / ".bugpacket",
        command=["java", "Main"],
        exit_code=1,
        stdout="",
        stderr=JVM_TRACE,
        parsed=parsed,
        ranked=[],
        git=None,
        environment=capture_environment({"HOME": "/x"}),
        repo_root=repo,
        cwd=repo,
        budget_tokens=8000,
    )
    doc = json.loads((result.out_dir / "packet.json").read_text())
    assert doc["root_cause"] == "java.lang.NullPointerException: coupon was null"
    assert len(doc["cause_chain"]) == 2
    stack = {entry["path"]: entry for entry in doc["stack"]}
    assert stack["Pricing.java"]["resolution"] == "suffix"
    assert stack["Pricing.java"]["resolved"] == "src/main/java/com/example/shop/Pricing.java"
    assert stack["Pricing.java"]["language"] == "jvm"


def test_go_test_names_appear_as_failing_tests(tmp_path):
    parsed = parse_output("--- FAIL: TestTotals (0.00s)\n    x_test.go:9: boom\n")
    text = render(tmp_path, parsed)
    assert "Failing tests:" in text
    assert "- TestTotals" in text
