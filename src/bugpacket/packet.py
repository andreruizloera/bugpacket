"""Assemble and write the packet: packet.md, packet.json, and files/."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bugpacket import __version__
from bugpacket.models import Frame, GitInfo, RankedFile
from bugpacket.stacktrace import ParsedOutput
from bugpacket.tokens import ESTIMATE_NOTE, estimate_repo_source_tokens, estimate_tokens

_MAX_OUTPUT_CHARS = 20_000
_MIN_TRIM_TOKENS = 300
_TRIM_CONTEXT_LINES = 30

_FENCE_LANGUAGES = {
    ".cjs": "javascript",
    ".js": "javascript",
    ".json": "json",
    ".jsx": "jsx",
    ".mjs": "javascript",
    ".py": "python",
    ".pyi": "python",
    ".sh": "bash",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".yaml": "yaml",
    ".yml": "yaml",
}


@dataclass
class IncludedFile:
    ranked: RankedFile
    content: str
    trimmed: bool
    tokens: int


@dataclass
class PacketResult:
    out_dir: Path
    repo_tokens: int
    packet_tokens: int
    included: list[IncludedFile] = field(default_factory=list)
    omitted: list[RankedFile] = field(default_factory=list)

    @property
    def reduction_percent(self) -> float:
        if self.repo_tokens <= 0:
            return 0.0
        return max(0.0, (1 - self.packet_tokens / self.repo_tokens) * 100)


def _fence_for(rel: str) -> str:
    return _FENCE_LANGUAGES.get(Path(rel).suffix.lower(), "")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _trim_to_budget(content: str, lines: set[int], budget_tokens: int) -> str:
    """Cut a file down to windows around referenced lines, within the budget."""
    all_lines = content.splitlines()
    if lines:
        keep: set[int] = set()
        for line_no in sorted(lines):
            lo = max(1, line_no - _TRIM_CONTEXT_LINES)
            hi = min(len(all_lines), line_no + _TRIM_CONTEXT_LINES)
            keep.update(range(lo, hi + 1))
        chunks: list[str] = []
        previous = 0
        for idx in sorted(keep):
            if idx > len(all_lines):
                break
            if previous and idx != previous + 1:
                chunks.append("... [lines omitted] ...")
            chunks.append(all_lines[idx - 1])
            previous = idx
        excerpt = "\n".join(chunks)
    else:
        excerpt = content

    max_chars = max(budget_tokens * 4 - 80, 200)
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars]
    return excerpt + "\n... [trimmed by bugpacket to fit the token budget]"


def select_files(
    ranked: list[RankedFile], budget_tokens: int
) -> tuple[list[IncludedFile], list[RankedFile]]:
    """Fill the budget with whole files in rank order, then trim, then omit."""
    included: list[IncludedFile] = []
    omitted: list[RankedFile] = []
    remaining = budget_tokens
    for entry in ranked:
        try:
            content = _read(entry.path)
        except OSError:
            continue
        cost = estimate_tokens(content)
        if cost <= remaining:
            included.append(IncludedFile(entry, content, trimmed=False, tokens=cost))
            remaining -= cost
        elif remaining >= _MIN_TRIM_TOKENS:
            excerpt = _trim_to_budget(content, entry.lines, remaining)
            cost = estimate_tokens(excerpt)
            included.append(IncludedFile(entry, excerpt, trimmed=True, tokens=cost))
            remaining = max(0, remaining - cost)
        else:
            omitted.append(entry)
    return included, omitted


def _display_frames(frames: list[Frame], repo_root: Path, cwd: Path) -> list[str]:
    """Frames formatted for the packet, restricted to files inside the repo."""
    lines: list[str] = []
    for frame in frames:
        path = Path(frame.path)
        resolved = None
        for candidate in [path] if path.is_absolute() else [cwd / path, repo_root / path]:
            if candidate.is_file():
                resolved = candidate.resolve()
                break
        if resolved is None:
            continue
        try:
            rel = resolved.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            continue
        text = f"{rel}:{frame.line}"
        if frame.function:
            text += f" in {frame.function}"
        if frame.language == "node":
            text += " (node)"
        lines.append(text)
    return lines


def render_markdown(
    command: list[str],
    exit_code: int,
    parsed: ParsedOutput,
    included: list[IncludedFile],
    omitted: list[RankedFile],
    git: GitInfo | None,
    environment: dict[str, Any],
    repo_root: Path,
    cwd: Path,
) -> str:
    parts: list[str] = ["# BugPacket", ""]

    parts += ["## Failure", ""]
    failure = parsed.distilled_failure() or f"Command exited with code {exit_code}."
    parts += ["```", failure, "```", ""]
    if parsed.failed_tests:
        parts.append("Failing tests:")
        parts.extend(f"- {path}::{test}" for path, test in dict.fromkeys(parsed.failed_tests))
        parts.append("")

    parts += ["## Reproduction", ""]
    parts += ["```", f"$ {shlex.join(command)}", f"exit code: {exit_code}", "```", ""]

    parts += ["## Relevant stack", ""]
    frame_lines = _display_frames(parsed.unique_frames(), repo_root, cwd)
    if frame_lines:
        parts += ["```", *frame_lines, "```", ""]
    else:
        parts += ["No stack trace detected in the output.", ""]

    parts += ["## Relevant files", ""]
    if included:
        for item in included:
            suffix = ", trimmed to fit budget" if item.trimmed else ""
            parts.append(
                f"### {item.ranked.rel} (rank {item.ranked.rank}: {item.ranked.reason}{suffix})"
            )
            parts += ["", f"```{_fence_for(item.ranked.rel)}", item.content.rstrip("\n"), "```", ""]
    else:
        parts += ["No repository files could be tied to this failure.", ""]
    if omitted:
        parts.append("Omitted because the token budget ran out:")
        parts.extend(f"- {entry.rel} (rank {entry.rank}: {entry.reason})" for entry in omitted)
        parts.append("")

    parts += ["## Current diff", ""]
    if git is None:
        parts += ["Not a git repository.", ""]
    else:
        parts += [f"Branch `{git.branch}` at `{git.commit}`.", ""]
        if git.status:
            parts += ["```", git.status, "```", ""]
        if git.diff:
            parts += ["```diff", git.diff, "```", ""]
        elif not git.status:
            parts += ["Working tree clean.", ""]

    parts += ["## Environment", ""]
    parts.append(f"- python: {environment.get('python', 'unknown')}")
    if "node" in environment:
        parts.append(f"- node: {environment['node']}")
    parts.append(f"- platform: {environment.get('platform', 'unknown')}")
    names = environment.get("env_var_names", [])
    shown = ", ".join(names[:60])
    if len(names) > 60:
        shown += f", and {len(names) - 60} more"
    parts.append(
        "- environment variable names (values are never captured; "
        f"secret-looking names removed): {shown}"
    )
    parts.append("")
    return "\n".join(parts)


def _truncate_output(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return text[:_MAX_OUTPUT_CHARS] + "\n... [truncated by bugpacket]"


def build_json(
    command: list[str],
    exit_code: int,
    stdout: str,
    stderr: str,
    parsed: ParsedOutput,
    included: list[IncludedFile],
    omitted: list[RankedFile],
    git: GitInfo | None,
    environment: dict[str, Any],
    repo_tokens: int,
    packet_tokens: int,
    reduction: float,
) -> dict[str, Any]:
    return {
        "bugpacket_version": __version__,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "command": command,
        "exit_code": exit_code,
        "failure": parsed.distilled_failure(),
        "failed_tests": [f"{path}::{test}" for path, test in parsed.failed_tests],
        "stack": [
            {
                "path": frame.path,
                "line": frame.line,
                "function": frame.function,
                "language": frame.language,
            }
            for frame in parsed.unique_frames()
        ],
        "files": [
            {
                "path": item.ranked.rel,
                "rank": item.ranked.rank,
                "reason": item.ranked.reason,
                "included": True,
                "trimmed": item.trimmed,
                "tokens_estimated": item.tokens,
            }
            for item in included
        ]
        + [
            {
                "path": entry.rel,
                "rank": entry.rank,
                "reason": entry.reason,
                "included": False,
                "trimmed": False,
                "tokens_estimated": None,
            }
            for entry in omitted
        ],
        "git": None
        if git is None
        else {
            "root": git.root,
            "branch": git.branch,
            "commit": git.commit,
            "status": git.status,
            "diff": git.diff,
            "diff_truncated": git.diff_truncated,
            "changed_files": git.changed_files,
        },
        "environment": environment,
        "stdout": _truncate_output(stdout),
        "stderr": _truncate_output(stderr),
        "token_stats": {
            "repository_source_tokens_estimated": repo_tokens,
            "packet_tokens_estimated": packet_tokens,
            "context_reduction_percent": round(reduction, 1),
            "note": ESTIMATE_NOTE,
        },
    }


def write_packet(
    out_dir: Path,
    command: list[str],
    exit_code: int,
    stdout: str,
    stderr: str,
    parsed: ParsedOutput,
    ranked: list[RankedFile],
    git: GitInfo | None,
    environment: dict[str, Any],
    repo_root: Path,
    cwd: Path,
    budget_tokens: int,
) -> PacketResult:
    """Write packet.md, packet.json, and files/ under out_dir."""
    included, omitted = select_files(ranked, budget_tokens)

    markdown = render_markdown(
        command, exit_code, parsed, included, omitted, git, environment, repo_root, cwd
    )
    packet_tokens = estimate_tokens(markdown)
    repo_tokens = estimate_repo_source_tokens(repo_root)
    reduction = max(0.0, (1 - packet_tokens / repo_tokens) * 100) if repo_tokens > 0 else 0.0

    doc = build_json(
        command,
        exit_code,
        stdout,
        stderr,
        parsed,
        included,
        omitted,
        git,
        environment,
        repo_tokens,
        packet_tokens,
        reduction,
    )

    files_dir = out_dir / "files"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "packet.md").write_text(markdown, encoding="utf-8")
    (out_dir / "packet.json").write_text(
        json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    for item in included:
        dest = files_dir / item.ranked.rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_read(item.ranked.path), encoding="utf-8")

    return PacketResult(
        out_dir=out_dir,
        repo_tokens=repo_tokens,
        packet_tokens=packet_tokens,
        included=included,
        omitted=omitted,
    )
