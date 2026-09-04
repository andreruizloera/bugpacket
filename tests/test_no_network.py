"""Enforce the privacy claim structurally: zero network code in the source."""

from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "bugpacket"

FORBIDDEN = [
    "aiohttp",
    "ftplib",
    "http",
    "requests",
    "smtplib",
    "socket",
    "urllib",
    "websocket",
]


def test_source_contains_no_network_code():
    assert SRC.is_dir()
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text().lower()
        offenders.extend(f"{path.name}: {token}" for token in FORBIDDEN if token in text)
    assert offenders == []
