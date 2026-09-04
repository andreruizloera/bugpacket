"""Git diff and status capture inside a temporary repository."""

import subprocess
from pathlib import Path

from bugpacket.gitcapture import capture_git, find_repo_root

GIT_ID = ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test"]


def make_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.py").write_text("old = 1\n")
    subprocess.run([*GIT_ID, "add", "."], cwd=tmp_path, check=True)
    subprocess.run([*GIT_ID, "commit", "-qm", "base"], cwd=tmp_path, check=True)
    return tmp_path


def test_outside_repo_returns_none(tmp_path):
    assert capture_git(tmp_path) is None
    assert find_repo_root(tmp_path) is None


def test_clean_repo(tmp_path):
    repo = make_repo(tmp_path)
    info = capture_git(repo)
    assert info is not None
    assert info.branch == "main"
    assert info.status == ""
    assert info.diff == ""
    assert info.changed_files == []


def test_diff_and_status_captured(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "tracked.py").write_text("new = 2\n")
    (repo / "untracked.py").write_text("fresh = 3\n")

    info = capture_git(repo)
    assert info is not None
    assert "-old = 1" in info.diff
    assert "+new = 2" in info.diff
    assert not info.diff_truncated
    assert any(line.startswith(" M") or line.startswith("M ") for line in info.status.splitlines())
    assert "?? untracked.py" in info.status
    assert info.changed_files == ["tracked.py", "untracked.py"]


def test_repo_root_found_from_subdirectory(tmp_path):
    repo = make_repo(tmp_path)
    sub = repo / "pkg"
    sub.mkdir()
    assert find_repo_root(sub) == repo.resolve()


def test_huge_diff_is_truncated(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "tracked.py").write_text("x = 1\n" * 10_000)
    info = capture_git(repo)
    assert info is not None
    assert info.diff_truncated
    assert info.diff.endswith("... [diff truncated by bugpacket]")
