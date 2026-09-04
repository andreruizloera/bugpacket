"""CLI behavior: run --json, show, copy, and errors when no packet exists."""

import json
import sys

import pytest

from bugpacket import cli


def test_show_without_packet(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["show"]) == 1
    assert "No packet found" in capsys.readouterr().err


def test_copy_without_packet(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["copy"]) == 1
    assert "No packet found" in capsys.readouterr().err


def test_run_without_command(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["run", "--"]) == 1
    assert "No command given" in capsys.readouterr().err


def test_run_with_unknown_command(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["run", "--", "definitely-not-a-real-binary-xyz"]) == 1
    assert "Command not found" in capsys.readouterr().err


@pytest.fixture
def failing_project(tmp_path, monkeypatch):
    (tmp_path / "boom.py").write_text('raise ValueError("boom")\n')
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_run_json_prints_structured_packet(failing_project, capsys):
    rc = cli.main(["run", "--json", "--", sys.executable, "boom.py"])
    assert rc == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["exit_code"] == 1
    assert doc["failure"] == "ValueError: boom"
    assert "estimates" in doc["token_stats"]["note"]


def test_run_then_show(failing_project, capsys):
    assert cli.main(["run", "--", sys.executable, "boom.py"]) == 0
    out = capsys.readouterr().out
    assert "Repository source size:" in out
    assert "BugPacket size:" in out
    assert "Context reduction:" in out
    assert "tokens estimated" in out

    assert cli.main(["show"]) == 0
    shown = capsys.readouterr().out
    assert shown.startswith("# BugPacket")
    assert "ValueError: boom" in shown


def test_copy_without_clipboard_tool(failing_project, capsys, monkeypatch):
    assert cli.main(["run", "--", sys.executable, "boom.py"]) == 0
    capsys.readouterr()
    monkeypatch.setattr(cli.clipboard.shutil, "which", lambda _name: None)
    assert cli.main(["copy"]) == 1
    err = capsys.readouterr().err
    assert "No clipboard tool found" in err
    assert "packet.md" in err


def test_copy_with_clipboard_tool(failing_project, capsys, monkeypatch):
    assert cli.main(["run", "--", sys.executable, "boom.py"]) == 0
    capsys.readouterr()
    copied: dict[str, str] = {}

    def fake_copy(text: str) -> str:
        copied["text"] = text
        return "pbcopy"

    monkeypatch.setattr(cli.clipboard, "copy_text", fake_copy)
    assert cli.main(["copy"]) == 0
    assert "Copied" in capsys.readouterr().out
    assert copied["text"].startswith("# BugPacket")
