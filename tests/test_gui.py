"""The window's command line re-entry and a hidden rejoin through it."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUI = str(ROOT / "exoprobe_gui.py")
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import smoke_frozen  # noqa: E402  pylint: disable=wrong-import-position,import-error


def run(*args, cwd=None):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=cwd,
                          stdin=subprocess.DEVNULL, timeout=300, check=False)


def tk_display_available():
    """Ask a separate process, so this one never creates a Tk root of its own."""
    return run("-c", "import tkinter; tkinter.Tk().destroy()").returncode == 0


def tree(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(folder).rglob("*")) if p.is_file()}


@pytest.fixture(name="evidence")
def evidence_fixture(tmp_path):
    folder = tmp_path / "ev"
    smoke_frozen.build_evidence(ROOT, folder)
    return folder


def test_cli_reentry_prints_what_the_command_line_prints(evidence):
    direct = run(str(ROOT / "exoprobe.py"), "scan", str(evidence))
    through = run(GUI, "--cli", "scan", str(evidence))
    assert direct.returncode == through.returncode == 0, through.stderr
    assert through.stdout == direct.stdout
    assert through.stdout.count("  (v") == 3


def test_hidden_window_rejoins_what_the_command_line_rejoins(evidence, tmp_path):
    if not tk_display_available():
        pytest.skip("Tk cannot open a display here")
    result = run(GUI, "--smoke", str(evidence), str(tmp_path / "window"))
    assert result.returncode == 0, result.stderr
    assert run(str(ROOT / "exoprobe.py"), "rejoin", str(evidence), "-o", str(tmp_path / "cli")).returncode == 0
    written = tree(tmp_path / "window")
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {"exit": 0, "files": len(written)}
    assert written == tree(tmp_path / "cli")
