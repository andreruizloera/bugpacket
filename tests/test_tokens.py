"""Token estimation and the always-labeled report lines."""

from bugpacket.tokens import (
    estimate_repo_source_tokens,
    estimate_tokens,
    format_token_report,
)


def test_chars_over_four():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd" * 25) == 25
    assert estimate_tokens("abcde") == 2  # rounds up


def test_report_lines_are_labeled_as_estimates():
    lines = format_token_report(312_004, 8_412)
    assert lines[0] == "Repository source size: 312,004 tokens estimated"
    assert lines[1] == "BugPacket size: 8,412 tokens estimated"
    assert lines[2] == "Context reduction: 97.3%"
    assert "estimated" in lines[0]
    assert "estimated" in lines[1]


def test_report_handles_empty_repo():
    lines = format_token_report(0, 100)
    assert lines[2] == "Context reduction: 0.0%"


def test_repo_scan_skips_junk(tmp_path):
    (tmp_path / "keep.py").write_text("x" * 400)  # 100 tokens
    (tmp_path / "uv.lock").write_text("x" * 4000)  # lockfile: skipped
    (tmp_path / "photo.bin").write_text("x" * 4000)  # unknown ext: skipped
    junk = tmp_path / "node_modules"
    junk.mkdir()
    (junk / "dep.js").write_text("x" * 4000)  # skipped directory
    assert estimate_repo_source_tokens(tmp_path) == 100
