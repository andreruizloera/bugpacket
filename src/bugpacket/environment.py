"""Capture environment metadata without ever touching secret values.

Rules, enforced by tests:
- Environment variable VALUES are never captured, for any variable.
- Environment variable NAMES are captured, but any name that even looks
  secret-adjacent (KEY, TOKEN, SECRET, PASSWORD, ...) is dropped too, because
  a name alone can leak information about infrastructure.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from typing import Any

SECRET_NAME_PATTERN = (
    r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|CREDENTIAL|CRED|AUTH|PRIVATE|"
    r"SESSION|COOKIE|SIGNATURE|CERT|SALT|BEARER|ACCESS|APIKEY|LICENSE"
)

_SECRET_NAME_RE = re.compile(SECRET_NAME_PATTERN, re.IGNORECASE)


def safe_env_var_names(environ: Mapping[str, str] | None = None) -> list[str]:
    """Sorted environment variable names with secret-looking names removed.

    Values are never read, let alone returned.
    """
    env = os.environ if environ is None else environ
    return sorted(name for name in env if not _SECRET_NAME_RE.search(name))


def _node_version() -> str | None:
    node = shutil.which("node")
    if node is None:
        return None
    try:
        proc = subprocess.run(  # local subprocess only; no network
            [node, "--version"], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    version = proc.stdout.strip()
    return version or None


def capture_environment(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Metadata about the machine that reproduced the failure."""
    info: dict[str, Any] = {
        "python": f"{platform.python_version()} ({platform.python_implementation()})",
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "env_var_names": safe_env_var_names(environ),
        "env_note": "names only, secret-looking names removed; values are never captured",
    }
    node = _node_version()
    if node:
        info["node"] = node
    return info
