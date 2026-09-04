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
