"""Copy text to the system clipboard when a local tool is available."""

from __future__ import annotations

import shutil
import subprocess

# Checked in order; the first tool found on PATH wins.
CLIPBOARD_TOOLS: list[tuple[str, list[str]]] = [
    ("pbcopy", ["pbcopy"]),
    ("wl-copy", ["wl-copy"]),
    ("xclip", ["xclip", "-selection", "clipboard"]),
    ("xsel", ["xsel", "--clipboard", "--input"]),
]


def copy_text(text: str) -> str | None:
    """Copy text to the clipboard. Returns the tool used, or None if none exists."""
    for name, argv in CLIPBOARD_TOOLS:
        if shutil.which(name) is None:
            continue
        try:
            proc = subprocess.run(  # local subprocess only; no network
                argv, input=text, text=True, capture_output=True, timeout=10, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0:
            return name
    return None
