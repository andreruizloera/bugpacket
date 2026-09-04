"""Capture git state (diff, status, branch) for the repository, if any."""

from __future__ import annotations

import subprocess
from pathlib import Path

from bugpacket.models import GitInfo

_MAX_DIFF_CHARS = 20_000


def _git(cwd: Path, *args: str) -> str | None:
    """Run a git command; return stripped stdout, or None on any failure."""
    try:
        proc = subprocess.run(  # local subprocess only; no network
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.rstrip("\n")


def find_repo_root(cwd: Path) -> Path | None:
    """The git worktree root containing cwd, or None outside a repo."""
    top = _git(cwd, "rev-parse", "--show-toplevel")
    if top:
        return Path(top)
    return None


def capture_git(cwd: Path) -> GitInfo | None:
    """Capture branch, commit, porcelain status, and the current diff.

    The diff covers staged plus unstaged changes (`git diff HEAD` when HEAD
    exists). Returns None when cwd is not inside a git repository.
    """
    root = find_repo_root(cwd)
    if root is None:
        return None

    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or "(no commits yet)"
    commit = _git(cwd, "rev-parse", "--short", "HEAD") or "(no commits yet)"
    status = _git(cwd, "status", "--porcelain") or ""

    diff = _git(cwd, "diff", "HEAD")
    if diff is None:  # no HEAD yet (empty repository)
        diff = _git(cwd, "diff") or ""

    truncated = False
    if len(diff) > _MAX_DIFF_CHARS:
        diff = diff[:_MAX_DIFF_CHARS] + "\n... [diff truncated by bugpacket]"
        truncated = True

    changed: set[str] = set()
    names = _git(cwd, "diff", "HEAD", "--name-only")
    if names is None:
        names = _git(cwd, "diff", "--name-only")
    if names:
        changed.update(n for n in names.splitlines() if n.strip())
    for line in status.splitlines():
        if len(line) > 3:
            changed.add(line[3:].strip().strip('"'))

    return GitInfo(
        root=str(root),
        branch=branch,
        commit=commit,
        status=status,
        diff=diff,
        diff_truncated=truncated,
        changed_files=sorted(changed),
    )
