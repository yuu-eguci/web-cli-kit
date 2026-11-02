import json
import sys
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import web


@pytest.fixture
def client() -> Iterator[TestClient]:
    web._current_job = None
    web._server = None
    with TestClient(web.app) as test_client:
        yield test_client
    web._current_job = None
    web._server = None


def read_events(client: TestClient) -> list[dict]:
    with client.stream("GET", "/api/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line.removeprefix("data: ")) for line in response.iter_lines() if line]


def fake_command(code: str):
    """_build_command の差し替え用。本物の cli の代わりに、手元の python で code を実行します。"""
    return lambda _request: [sys.executable, "-c", code]


def test_index_は_html_を返す(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert '<form id="run-form">' in response.text


def test_defaults_は_env_の値を返す(client: TestClient, tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("WEB_DEFAULT_MESSAGE=やあ\nWEB_DEFAULT_SECONDS=5\n")
    monkeypatch.setattr(web, "ENV_PATH", env_path)
    assert client.get("/api/defaults").json() == {"message": "やあ", "seconds": "5"}


def test_defaults_は_env_が無くても空で返す(client: TestClient, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(web, "ENV_PATH", tmp_path / "missing.env")
    assert client.get("/api/defaults").json() == {"message": "", "seconds": ""}


def test_run_は_message_が無いと_422(client: TestClient) -> None:
    assert client.post("/api/run", json={"seconds": 0}).status_code == 422


def test_events_はジョブが無いと_404(client: TestClient) -> None:
    assert client.get("/api/events").status_code == 404


def test_dry_run_は_message_なしでも流れる(client: TestClient) -> None:
    assert client.post("/api/run", json={"dry_run": True}).json() == {"started": True}
    events = read_events(client)
    assert [event["type"] for event in events] == ["step_start", "log", "log", "log", "step_end", "done"]
    assert all(event["line"].startswith("[dry run] ") for event in events if event["type"] == "log")


def test_本実行は_cli_のログを_sse_で流す(client: TestClient) -> None:
    assert client.post("/api/run", json={"message": "やっほー", "seconds": 0}).json() == {"started": True}
    events = read_events(client)
    # イベントにコマンド (将来の秘密情報を含みうる) は載せない。
    assert events[0] == {"type": "step_start", "step": 1, "script": "cli.py"}
    assert events[-2:] == [{"type": "step_end", "step": 1, "script": "cli.py"}, {"type": "done"}]
    lines = [event["line"] for event in events if event["type"] == "log"]
    assert lines[0] == "受け取ったメッセージ: やっほー"
    assert "  ...進行中 (3/3)" in lines


def test_cli_が失敗したら_error_を流す(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(web, "_build_command", fake_command("print('boom'); raise SystemExit(3)"))
    client.post("/api/run", json={"message": "x"})
    events = read_events(client)
    assert {"type": "log", "step": 1, "line": "boom"} in events
    assert events[-1] == {"type": "error", "message": "cli.py が exit code 3 で失敗した。"}


def test_実行中に_run_すると_409(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(web, "_build_command", fake_command("import time; time.sleep(0.5)"))
    assert client.post("/api/run", json={"message": "x"}).status_code == 200
    assert client.post("/api/run", json={"message": "x"}).status_code == 409
    assert read_events(client)[-1] == {"type": "done"}
    # 終わったら次のジョブを開始できる。
    assert client.post("/api/run", json={"dry_run": True}).status_code == 200
    assert read_events(client)[-1] == {"type": "done"}


def test_shutdown_はサーバーに終了を伝える(client: TestClient) -> None:
    web._server = SimpleNamespace(should_exit=False)
    assert client.post("/api/shutdown").json() == {"bye": True}
    assert web._server.should_exit is True


def test_shutdown_はサーバー参照が無いと_500(client: TestClient) -> None:
    assert client.post("/api/shutdown").status_code == 500
