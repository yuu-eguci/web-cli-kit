import subprocess
import sys


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "cli.py", *args], capture_output=True, text=True, check=False)


def test_cli_はメッセージを出して正常終了する() -> None:
    result = run_cli("--message", "やっほー", "--seconds", "0")
    assert result.returncode == 0
    assert "やっほー" in result.stderr
    assert "(3/3)" in result.stderr


def test_cli_は_message_が無いとエラー() -> None:
    result = run_cli("--seconds", "0")
    assert result.returncode == 2
