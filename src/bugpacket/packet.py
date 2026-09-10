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
from bugpacket.resolve import FrameResolver
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
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".py": "python",
    ".pyi": "python",
    ".rs": "rust",
    ".scala": "scala",
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


_LANGUAGE_TAGS = {"node": " (node)", "rust": " (rust)", "go": " (go)", "jvm": " (jvm)"}


def _display_frames(
    frames: list[Frame], repo_root: Path, resolver: FrameResolver
) -> tuple[list[str], list[str]]:
    """Frames formatted for the packet, plus notes about ones it could not place.

    Returns (stack lines, notes). A frame that resolved by suffix search says
    so, because that is an inference rather than a path the runtime gave; a
    frame whose name matched several repository files is reported with the
    candidates instead of being silently dropped.
    """
    lines: list[str] = []
    notes: list[str] = []
    for frame in frames:
        resolution = resolver.resolve(frame)
        if not resolution.found:
            if resolution.how == "ambiguous":
                shown = ", ".join(resolution.candidates[:4])
                if len(resolution.candidates) > 4:
                    shown += f", and {len(resolution.candidates) - 4} more"
                notes.append(
                    f"{frame.path}:{frame.line} matched several files and was not included: {shown}"
                )
            continue
        try:
            rel = resolution.path.relative_to(repo_root.resolve()).as_posix()  # type: ignore[union-attr]
        except ValueError:
            continue
        text = f"{rel}:{frame.line}"
        if frame.function:
            text += f" in {frame.function}"
        text += _LANGUAGE_TAGS.get(frame.language, "")
        if resolution.how == "suffix":
            text += "  [matched by file name; the trace gave no usable path]"
        lines.append(text)
    return lines, notes


_MAX_STACKS = 3
"""How many stacks the packet prints. A suite with forty failing tests prints
forty of them, and past the first few they stop earning their tokens. Whatever
is dropped is counted in the packet, never dropped silently."""

_DIRECTION_NOTE = "Innermost frame first: the top line of each stack is where the failure happened."


def _render_stacks(
    parsed: ParsedOutput, repo_root: Path, resolver: FrameResolver
) -> tuple[list[str], list[str]]:
    """The `Relevant stack` section: one block per stack, failure site on top.

    One command's output holds one stack per failing test, and a JVM failure
    holds one per exception in its `Caused by:` chain. They are printed
    separately because concatenating them produces a list whose adjacent lines
    never called each other.
    """
    stacks = parsed.ordered_stacks()
    rendered: list[tuple[str, list[str]]] = []
    notes: list[str] = []
    for stack in stacks:
        lines, stack_notes = _display_frames(stack.frames, repo_root, resolver)
        notes.extend(stack_notes)
        if lines:
            rendered.append((stack.block.label, lines))

    if not rendered:
        if parsed.unique_frames():
            return [
                "A stack trace was parsed, but none of its frames could be tied to a "
                "file in this repository.",
                "",
            ], notes
        return ["No stack trace detected in the output.", ""], notes

    shown, dropped = rendered[:_MAX_STACKS], rendered[_MAX_STACKS:]
    parts = [_DIRECTION_NOTE, ""]
    if len(rendered) > 1:
        parts[0] = (
            f"{len(rendered)} stacks, each printed innermost frame first: the top "
            "line of each is where that failure happened."
        )
    for label, lines in shown:
        if len(shown) > 1 and label:
            parts.append(f"{label}:")
            parts.append("")
        parts += ["```", *lines, "```", ""]
    if dropped:
        parts.append(
            f"{len(dropped)} further stack(s) not printed: "
            + ", ".join(label or "unnamed" for label, _ in dropped)
        )
        parts.append("")
    return parts, notes


def render_markdown(
    command: list[str],
    exit_code: int,
    parsed: ParsedOutput,
    included: list[IncludedFile],
    omitted: list[RankedFile],
    git: GitInfo | None,
    environment: dict[str, Any],
    repo_root: Path,
    resolver: FrameResolver,
) -> str:
    parts: list[str] = ["# BugPacket", ""]

    parts += ["## Failure", ""]
    failure = parsed.distilled_failure() or f"Command exited with code {exit_code}."
    parts += ["```", failure, "```", ""]
    if parsed.root_cause is not None:
        parts.append(
            f"That is the root cause of a chain of {len(parsed.cause_chain)} exceptions. "
            "The outermost, which is where the trace starts and usually not where "
            "the bug is:"
        )
        parts += ["", "```", parsed.cause_chain[0], "```", ""]
    if len(parsed.diagnostics) > 1:
        parts.append(
            f"The compiler reported {len(parsed.diagnostics)} errors. That is the first "
            "one, because the ones after it are usually consequences of it; every "
            "location they named is below."
        )
        parts.append("")
    if parsed.failed_tests or parsed.failed_test_names:
        parts.append("Failing tests:")
        parts.extend(f"- {path}::{test}" for path, test in dict.fromkeys(parsed.failed_tests))
        parts.extend(f"- {name}" for name in dict.fromkeys(parsed.failed_test_names))
        parts.append("")

    parts += ["## Reproduction", ""]
    parts += ["```", f"$ {shlex.join(command)}", f"exit code: {exit_code}", "```", ""]

    diagnosed = bool(parsed.diagnostics)
    parts += ["## Reported locations" if diagnosed else "## Relevant stack", ""]
    if diagnosed:
        # Not a stack: the compiler's own order is the useful one, and the
        # first error is the one to fix.
        frame_lines, frame_notes = _display_frames(parsed.unique_frames(), repo_root, resolver)
        if frame_lines:
            parts += ["```", *frame_lines, "```", ""]
        elif parsed.unique_frames():
            parts += [
                "A compiler diagnostic was parsed, but none of the files it named "
                "could be tied to this repository.",
                "",
            ]
        else:
            parts += ["No stack trace detected in the output.", ""]
    else:
        stack_parts, frame_notes = _render_stacks(parsed, repo_root, resolver)
        parts += stack_parts
    if frame_notes:
        parts.extend(f"- {note}" for note in frame_notes)
        parts.append("")

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


def _resolved_rel(frame: Frame, repo_root: Path, resolver: FrameResolver) -> str | None:
    """The frame's repo-relative file, or None when it could not be placed."""
    resolution = resolver.resolve(frame)
    if resolution.path is None:
        return None
    try:
        return resolution.path.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return None


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
    repo_root: Path,
    resolver: FrameResolver,
) -> dict[str, Any]:
    return {
        "bugpacket_version": __version__,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "command": command,
        "exit_code": exit_code,
        "failure": parsed.distilled_failure(),
        "root_cause": parsed.root_cause,
        "cause_chain": parsed.cause_chain,
        "diagnostics": list(parsed.diagnostics),
        "failed_tests": [f"{path}::{test}" for path, test in parsed.failed_tests]
        + list(parsed.failed_test_names),
        "stack": [
            {
                "path": frame.path,
                "line": frame.line,
                "function": frame.function,
                "language": frame.language,
                "vendored": frame.vendored,
                "resolved": _resolved_rel(frame, repo_root, resolver),
                "resolution": resolver.resolve(frame).how,
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
    resolver: FrameResolver | None = None,
) -> PacketResult:
    """Write packet.md, packet.json, and files/ under out_dir."""
    if resolver is None:
        resolver = FrameResolver(repo_root=repo_root, cwd=cwd)
    included, omitted = select_files(ranked, budget_tokens)

    markdown = render_markdown(
        command, exit_code, parsed, included, omitted, git, environment, repo_root, resolver
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
        repo_root,
        resolver,
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
