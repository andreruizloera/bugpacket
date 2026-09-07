"""The bugpacket command line interface."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from bugpacket import __version__, clipboard
from bugpacket.environment import capture_environment
from bugpacket.gitcapture import capture_git, find_repo_root
from bugpacket.packet import write_packet
from bugpacket.ranking import rank_files
from bugpacket.resolve import FrameResolver
from bugpacket.stacktrace import ParsedOutput, parse_output
from bugpacket.tokens import format_token_report

DEFAULT_BUDGET = 8_000
OUT_DIR_NAME = ".bugpacket"


class BugPacketError(Exception):
    """Expected failure with a clean message; no raw traceback for the user."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bugpacket",
        description=(
            "Turn a software failure into the smallest useful debugging context "
            "for an AI coding agent. Strictly local; nothing is ever uploaded."
        ),
    )
    parser.add_argument("--version", action="version", version=f"bugpacket {__version__}")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    run = sub.add_parser(
        "run",
        help="run a command and build a packet from its failure",
        description="Example: bugpacket run -- pytest tests/test_payment.py",
    )
    run.add_argument(
        "--budget",
        type=int,
        default=DEFAULT_BUDGET,
        help=f"estimated token budget for included file contents (default {DEFAULT_BUDGET})",
    )
    run.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print packet.json to stdout instead of the human summary",
    )
    run.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="the command to run, after -- (e.g. bugpacket run -- npm test)",
    )

    sub.add_parser("show", help="render the latest packet.md to the terminal")
    sub.add_parser("copy", help="copy the latest packet.md to the clipboard")
    return parser


def _find_packet_file(cwd: Path, name: str = "packet.md") -> Path:
    candidates = [cwd / OUT_DIR_NAME / name]
    root = find_repo_root(cwd)
    if root is not None and root != cwd:
        candidates.append(root / OUT_DIR_NAME / name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise BugPacketError(
        "No packet found. Run one first, for example:\n"
        "  bugpacket run -- pytest tests/test_payment.py"
    )


def _failing_test_paths(command: list[str], parsed: ParsedOutput, cwd: Path) -> list[str]:
    """Test files, from the FAILED summary plus test-looking command arguments."""
    paths = [path for path, _ in parsed.failed_tests]
    for arg in command:
        candidate = arg.split("::", 1)[0]
        name = Path(candidate).name
        if (
            candidate.endswith((".py", ".js", ".mjs", ".ts", ".go", ".rs", ".java", ".kt"))
            and ("test" in name.lower() or "spec" in name.lower())
            and (cwd / candidate).is_file()
        ):
            paths.append(candidate)
    return list(dict.fromkeys(paths))


def cmd_run(args: argparse.Namespace) -> int:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise BugPacketError("No command given. Usage: bugpacket run -- <command...>")

    cwd = Path.cwd()
    try:
        proc = subprocess.run(  # local subprocess only; no network
            command, capture_output=True, text=True, errors="replace", check=False
        )
    except FileNotFoundError:
        raise BugPacketError(f"Command not found: {command[0]}") from None
    except OSError as exc:
        raise BugPacketError(f"Could not run {command[0]}: {exc}") from None

    echo = sys.stderr if args.as_json else sys.stdout
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n", file=echo)
    if proc.stderr:
        print(proc.stderr, end="" if proc.stderr.endswith("\n") else "\n", file=echo)

    repo_root = find_repo_root(cwd) or cwd
    parsed = parse_output(proc.stdout + "\n" + proc.stderr)
    git = capture_git(cwd)
    # One resolver for the whole run, so the file list and the printed stack
    # cannot disagree about where a frame lives, and the tree is walked once.
    resolver = FrameResolver(repo_root=repo_root, cwd=cwd)
    ranked = rank_files(
        repo_root=repo_root,
        cwd=cwd,
        frames=parsed.unique_frames(),
        failing_test_paths=_failing_test_paths(command, parsed, cwd),
        git_changed_files=git.changed_files if git else [],
        resolver=resolver,
    )

    result = write_packet(
        out_dir=cwd / OUT_DIR_NAME,
        command=command,
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        parsed=parsed,
        ranked=ranked,
        git=git,
        environment=capture_environment(),
        repo_root=repo_root,
        cwd=cwd,
        budget_tokens=max(args.budget, 500),
        resolver=resolver,
    )

    if args.as_json:
        print((result.out_dir / "packet.json").read_text(encoding="utf-8"), end="")
    else:
        print()
        if proc.returncode == 0:
            print("Note: the command exited 0; the packet captures context anyway.")
        rel_out = OUT_DIR_NAME
        print(f"BugPacket written to {rel_out}/")
        print("  packet.md    (paste into your AI coding agent, or: bugpacket copy)")
        print("  packet.json  (structured)")
        count = len(result.included)
        label = "file" if count == 1 else "files"
        print(f"  files/       ({count} relevant {label})")
        print()
        for line in format_token_report(result.repo_tokens, result.packet_tokens):
            print(line)
    return 0


def cmd_show(_args: argparse.Namespace) -> int:
    packet = _find_packet_file(Path.cwd())
    print(packet.read_text(encoding="utf-8"), end="")
    return 0


def cmd_copy(_args: argparse.Namespace) -> int:
    packet = _find_packet_file(Path.cwd())
    text = packet.read_text(encoding="utf-8")
    tool = clipboard.copy_text(text)
    if tool is None:
        print(
            "No clipboard tool found (looked for pbcopy, wl-copy, xclip, xsel).\n"
            f"The packet is at {packet}",
            file=sys.stderr,
        )
        return 1
    print(f"Copied {packet} to the clipboard via {tool}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {"run": cmd_run, "show": cmd_show, "copy": cmd_copy}
    try:
        return handlers[args.subcommand](args)
    except BugPacketError as exc:
        print(f"bugpacket: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("bugpacket: interrupted", file=sys.stderr)
        return 130


def entrypoint() -> None:
    raise SystemExit(main())
