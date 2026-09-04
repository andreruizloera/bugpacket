"""Token estimation.

Everything here is an estimate. BugPacket uses the common chars/4 heuristic
and always labels its numbers as estimates; it never claims exact token
counts, because tokenizers differ across models.
"""

from __future__ import annotations

import os
from pathlib import Path

ESTIMATE_NOTE = "chars/4 heuristic; these numbers are estimates, not exact token counts"

SOURCE_EXTS = {
    ".c",
    ".cfg",
    ".cjs",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".pyi",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

SKIP_DIR_NAMES = {
    ".bugpacket",
    ".eggs",
    ".git",
    ".hg",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
    "venv",
}

SKIP_FILE_NAMES = {
    "Cargo.lock",
    "go.sum",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}

_MAX_COUNTED_FILE_BYTES = 1_000_000


def estimate_tokens(text: str) -> int:
    """Estimate the token count of a string (chars/4, rounded up)."""
    if not text:
        return 0
    return (len(text) + 3) // 4


def estimate_repo_source_tokens(root: Path) -> int:
    """Estimate total tokens across the repository's source files.

    Walks the tree, skipping VCS internals, virtualenvs, caches, build output,
    and lockfiles. Files above 1 MB are ignored as generated or binary-ish.
    """
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIR_NAMES)
        for name in filenames:
            if name in SKIP_FILE_NAMES:
                continue
            if Path(name).suffix.lower() not in SOURCE_EXTS:
                continue
            fpath = Path(dirpath) / name
            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            if 0 < size <= _MAX_COUNTED_FILE_BYTES:
                total += (size + 3) // 4
    return total


def format_token_report(repo_tokens: int, packet_tokens: int) -> list[str]:
    """The three summary lines printed after every run. Labeled as estimates."""
    reduction = max(0.0, (1 - packet_tokens / repo_tokens) * 100) if repo_tokens > 0 else 0.0
    return [
        f"Repository source size: {repo_tokens:,} tokens estimated",
        f"BugPacket size: {packet_tokens:,} tokens estimated",
        f"Context reduction: {reduction:.1f}%",
    ]
