"""Relevance ranking: order, deduplication, and determinism."""

from pathlib import Path

from bugpacket.models import Frame
from bugpacket.ranking import rank_files


def make_repo(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "main.py").write_text(
        "from app.helpers import helper\n\ndef run():\n    return helper()\n"
    )
    (tmp_path / "app" / "helpers.py").write_text("def helper():\n    return 1\n")
    (tmp_path / "tests" / "test_main.py").write_text(
        "from app.main import run\n\ndef test_run():\n    assert run() == 1\n"
    )
    (tmp_path / "changed.py").write_text("x = 1\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    return tmp_path


def test_rank_order(tmp_path):
    repo = make_repo(tmp_path)
    ranked = rank_files(
        repo_root=repo,
        cwd=repo,
        frames=[Frame("app/main.py", 3, "run", "python")],
        failing_test_paths=["tests/test_main.py"],
        git_changed_files=["changed.py", "app/main.py"],
    )
    assert [(r.rel, r.rank) for r in ranked] == [
        ("app/main.py", 1),
        ("tests/test_main.py", 2),
        ("app/helpers.py", 3),
        ("changed.py", 4),
        ("pyproject.toml", 5),
    ]


def test_best_rank_wins_when_file_appears_twice(tmp_path):
    repo = make_repo(tmp_path)
    ranked = rank_files(
        repo_root=repo,
        cwd=repo,
        frames=[Frame("app/main.py", 3, "run", "python")],
        failing_test_paths=["app/main.py"],
        git_changed_files=["app/main.py"],
    )
    entry = next(r for r in ranked if r.rel == "app/main.py")
    assert entry.rank == 1
    assert sum(1 for r in ranked if r.rel == "app/main.py") == 1


def test_stack_lines_recorded(tmp_path):
    repo = make_repo(tmp_path)
    ranked = rank_files(
        repo_root=repo,
        cwd=repo,
        frames=[
            Frame("app/main.py", 3, "run", "python"),
            Frame("app/main.py", 4, "run", "python"),
        ],
        failing_test_paths=[],
        git_changed_files=[],
    )
    entry = next(r for r in ranked if r.rel == "app/main.py")
    assert entry.lines == {3, 4}


def test_missing_files_ignored(tmp_path):
    repo = make_repo(tmp_path)
    ranked = rank_files(
        repo_root=repo,
        cwd=repo,
        frames=[Frame("/nonexistent/elsewhere.py", 1, None, "python")],
        failing_test_paths=["tests/does_not_exist.py"],
        git_changed_files=["ghost.py"],
    )
    assert [r.rel for r in ranked] == ["pyproject.toml"]


def test_deterministic(tmp_path):
    repo = make_repo(tmp_path)
    args = {
        "repo_root": repo,
        "cwd": repo,
        "frames": [Frame("app/main.py", 3, "run", "python")],
        "failing_test_paths": ["tests/test_main.py"],
        "git_changed_files": ["changed.py"],
    }
    first = [(r.rel, r.rank) for r in rank_files(**args)]
    second = [(r.rel, r.rank) for r in rank_files(**args)]
    assert first == second


def test_go_package_siblings_rank_third(tmp_path):
    """A `go test` failure names only the test file; its package is the subject."""
    (tmp_path / "pricing").mkdir()
    (tmp_path / "pricing" / "pricing_test.go").write_text("package pricing\n")
    (tmp_path / "pricing" / "pricing.go").write_text("package pricing\n")
    (tmp_path / "pricing" / "helper_test.go").write_text("package pricing\n")
    (tmp_path / "cart").mkdir()
    (tmp_path / "cart" / "cart.go").write_text("package cart\n")
    frames = [Frame(path="pricing_test.go", line=9, function=None, language="go")]
    ranked = rank_files(tmp_path, tmp_path, frames, [], [])
    by_rank = {entry.rel: entry.rank for entry in ranked}
    assert by_rank["pricing/pricing_test.go"] == 1
    assert by_rank["pricing/pricing.go"] == 3
    # Another package is not the subject of this test, and a second test file
    # is not the code under test.
    assert "cart/cart.go" not in by_rank
    assert "pricing/helper_test.go" not in by_rank


def test_jvm_frames_rank_first_through_their_package_hint(tmp_path):
    target = tmp_path / "src/main/java/com/example/shop/Pricing.java"
    target.parent.mkdir(parents=True)
    target.write_text("package com.example.shop;\n")
    frames = [
        Frame(
            path="Pricing.java",
            line=8,
            function="com.example.shop.Pricing.applyCoupon",
            language="jvm",
            path_hint="com/example/shop/Pricing.java",
        )
    ]
    ranked = rank_files(tmp_path, tmp_path, frames, [], [])
    assert [(e.rel, e.rank) for e in ranked] == [("src/main/java/com/example/shop/Pricing.java", 1)]
    assert ranked[0].lines == {8}


def test_an_ambiguous_frame_ranks_no_file_at_all(tmp_path):
    for pkg in ("alpha", "beta"):
        (tmp_path / pkg).mkdir()
        (tmp_path / pkg / "util_test.go").write_text("package x\n")
    frames = [Frame(path="util_test.go", line=3, function=None, language="go")]
    ranked = rank_files(tmp_path, tmp_path, frames, [], [])
    assert ranked == []


def test_a_vendored_frame_never_ranks_a_same_named_repository_file(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "option.rs").write_text("// ours\n")
    frames = [
        Frame(
            path="/tc/lib/rustlib/src/rust/library/core/src/option.rs",
            line=969,
            function="core::option::expect_failed",
            language="rust",
            vendored=True,
        )
    ]
    assert rank_files(tmp_path, tmp_path, frames, [], []) == []
