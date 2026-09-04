"""End to end: run bugpacket against the shopapp fixture with the bug applied."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "shopapp"
GIT_ID = ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test"]


def prepare_fixture(tmp_path: Path) -> Path:
    dest = tmp_path / "shopapp"
    shutil.copytree(
        FIXTURE,
        dest,
        ignore=shutil.ignore_patterns(".bugpacket", "__pycache__", ".pytest_cache", ".venv"),
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=dest, check=True)
    subprocess.run([*GIT_ID, "add", "."], cwd=dest, check=True)
    subprocess.run([*GIT_ID, "commit", "-qm", "working version"], cwd=dest, check=True)

    # Introduce the bug the demo uses: read the coupon field under the wrong name.
    payment = dest / "shop" / "payment.py"
    payment.write_text(payment.read_text().replace('coupon["percent"]', 'coupon["percentage"]'))
    return dest


def test_end_to_end(tmp_path):
    project = prepare_fixture(tmp_path)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "bugpacket",
            "run",
            "--",
            sys.executable,
            "-m",
            "pytest",
            "tests/test_payment.py",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr

    out = proc.stdout
    assert "Repository source size:" in out
    assert "BugPacket size:" in out
    assert "Context reduction:" in out
    assert "tokens estimated" in out

    packet_dir = project / ".bugpacket"
    markdown = (packet_dir / "packet.md").read_text()
    assert "KeyError: 'percentage'" in markdown
    assert "shop/payment.py" in markdown
    assert "tests/test_payment.py" in markdown
    assert "## Current diff" in markdown
    assert '+    percent = coupon["percentage"]' in markdown

    # Irrelevant modules stay out of the packet files.
    assert (packet_dir / "files" / "shop" / "payment.py").is_file()
    assert not (packet_dir / "files" / "shop" / "shipping.py").exists()

    doc = json.loads((packet_dir / "packet.json").read_text())
    assert doc["exit_code"] == 1
    assert doc["failure"] == "KeyError: 'percentage'"
    included = [f["path"] for f in doc["files"] if f["included"]]
    assert "shop/payment.py" in included
    assert "shop/cart.py" in included
    ranks = {f["path"]: f["rank"] for f in doc["files"]}
    assert ranks["shop/payment.py"] == 1
    assert doc["token_stats"]["repository_source_tokens_estimated"] > 0
