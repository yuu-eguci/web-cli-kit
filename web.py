import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import uvicorn

# NOTE: pipenv は自動で .env を読むので、機能的には dotenv は不要。
#       ただし pipenv が .env を読むタイミングはプロセスを起動したとき。
#       dotenv であれば、リアルタイムで .env を変更できる良さがあるので、今回は採用。
from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

INDEX_HTML_PATH = Path(__file__).parent / "index.html"
ENV_PATH = Path(__file__).parent / ".env"

# 呼び出す cli スクリプト。 fork したら、あなたのスクリプト名に書き換えてください。
CLI_SCRIPT = "cli.py"

# NOTE: FastAPI の読み方は……
#       @app.get とか @app.post がルーティング定義なので、そこを見ていく。
app = FastAPI()


@app.get("/")
async def index() -> FileResponse:
    """
    まずは GET /
    Web UI のページ (html 1 枚) を返します。
    """
    return FileResponse(INDEX_HTML_PATH)


@app.get("/api/defaults")
async def defaults() -> dict[str, object]:
    """
    次に GET /api/defaults
    index.html を開いた直後に、フォームの初期値を取得するための API です。
    ただの便利機能。 .env が無くても空で返るだけなので壊れません。
    """
    env = dotenv_values(ENV_PATH)
    return {
        "message": env.get("WEB_DEFAULT_MESSAGE") or "",
        "seconds": env.get("WEB_DEFAULT_SECONDS") or "",
    }


class RunRequest(BaseModel):
    """
    POST /api/run のリクエストボディです。
    各フィールドは cli.py のコマンドライン引数に対応します。
    None (フォームの空欄) は「指定なし」で、 cli のデフォルトに任せます。
    """

    message: str | None = None
    seconds: int | None = Field(default=None, ge=0)
    dry_run: bool = False

    @model_validator(mode="after")
    def _require_message_unless_dry_run(self) -> RunRequest:
        """
        mode="before" 各フィールドに型を適用する前。 dict が渡ってくる。
        mode="after" self の中に型付きの値が入ってくる。
        そもそも型チェックでおかしかったらどーなんの? --> ここに来る前にすでに 422 で返る。

        本実行のときだけ、必須引数が揃っているか検証します。
        (dry run は UI のテスト用なので、空っぽでも通します。)
        """
        if self.dry_run:
            return self
        if self.message in (None, ""):
            raise ValueError("dry run でないなら message は必須だよ。")
        return self


@app.post("/api/run")
async def run(request: RunRequest) -> dict[str, bool]:
    """
    POST /api/run
    ジョブ (cli.py を 1 本実行) を開始します。進捗は GET /api/events の SSE で流れます。
    """
    # 【この関数読む前に coroutine を知っとけ】
    # coroutine は「誰かに駆動されるまでただの遅延オブジェクト」である。
    # coroutine が駆動されるのは……
    # - await されたとき (こいつはグローバルスコープに書けない)
    # - asyncio.run されたとき (こいつがグローバルスコープに書けて、 async 処理を「始める者」!)
    # - asyncio.create_task で「スケジュール」されて、さらに「イベントループ」で順番が来たとき

    # dataclass Job です。 GET /api/events と POST /api/run で共有するので、グローバル変数に置いています。
    global _current_job

    # asyncio.Task の done() から、「もうタスク終わった?」ってのを聞いている。
    if _current_job is not None and not _current_job.task.done():
        raise HTTPException(status_code=409, detail="ジョブが既に実行中だよ。")

    # このキューはタスクを入れるものじゃなくて、 _run_job の中で dict を積むためのもの。
    # GET /api/events のほうで dict を取り出して SSE で流すのに使います。
    queue: asyncio.Queue = asyncio.Queue()

    # 上でおさらいしたスケジュールされてイベントループで順番が来たとき (関数の return 後) 実行されるやつ。
    task = asyncio.create_task(_run_job(request, queue))

    _current_job = Job(queue=queue, task=task)

    # 画面へ JSON を返す。
    # JSONResponse を使ってもいいんだけど、 FastAPI はそこ自動なんだってさ。
    return {"started": True}


@dataclass
class Job:
    """
    実行中 (または実行済み) のジョブです。 queue には SSE で流すイベントが積まれます。
    """

    queue: asyncio.Queue
    task: asyncio.Task


# 一人用ツールなので、ジョブは同時に 1 個だけ、というシンプルな作りにしています。
# NOTE: これはシングルトンではない。シングルトンは、何回インスタンスを new しても同じオブジェクトが返るやつね。
#       このプログラムでは run ごとに新しい Job インスタンスを作らないといけないっしょ?
_current_job: Job | None = None


async def _run_job(request: RunRequest, queue: asyncio.Queue) -> None:
    """
    ジョブ全体を実行して、最後に done か error のイベントを積みます。
    """
    try:
        if request.dry_run:
            await _run_dry(queue)
        else:
            await _run_real(request, queue)
    except Exception as exception:
        logger.exception("ジョブが失敗した。")
        await queue.put({"type": "error", "message": str(exception)})
    else:
        await queue.put({"type": "done"})


async def _run_dry(queue: asyncio.Queue) -> None:
    """
    UI テスト用のドライランです。 subprocess の代わりに sleep しながら、本物と同じ形のイベントを流します。
    """
    fake_lines = [
        "受け取ったメッセージ (のフリ): hello",
        "重たい処理をするフリ中……",
        "処理おわりのフリ！",
    ]
    await queue.put({"type": "step_start", "step": 1, "script": CLI_SCRIPT})
    for line in fake_lines:
        await asyncio.sleep(0.6)
        await queue.put({"type": "log", "step": 1, "line": f"[dry run] {line}"})
    await queue.put({"type": "step_end", "step": 1, "script": CLI_SCRIPT})


async def _run_real(request: RunRequest, queue: asyncio.Queue) -> None:
    """
    cli.py を 1 本、 subprocess で実行します。
    NOTE: スクリプトを 001 → 002 → 003 のように増やしたくなったら、ここでループを回して
          _run_script を複数回呼べば OK。 (discord-messages はそういう作りでした。)
    """
    command = _build_command(request)
    await _run_script(queue, step=1, script=CLI_SCRIPT, command=command)


def _build_command(request: RunRequest) -> list[str]:
    """
    cli.py のコマンドを組み立てます。 fork して引数が増えたら、ここも一緒に足してください。
    NOTE: "--message=値" の形にしているのは、 "-" で始まる値をオプションと間違われないようにするためです。
    """
    command = [sys.executable, CLI_SCRIPT, f"--message={request.message}"]
    if request.seconds is not None:
        command.append(f"--seconds={request.seconds}")
    return command


async def _run_script(queue: asyncio.Queue, step: int, script: str, command: list[str]) -> None:
    """
    スクリプトを 1 本実行して、出力を一行ずつイベントとして queue に積みます。
    NOTE: イベントに command は入れません。将来 token などの秘密情報を引数で渡すとき、 SSE に漏れてしまうので。
    """
    await queue.put({"type": "step_start", "step": step, "script": script})
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert process.stdout is not None
    while line := await process.stdout.readline():
        await queue.put({"type": "log", "step": step, "line": line.decode(errors="replace").rstrip()})
    exit_code = await process.wait()
    if exit_code != 0:
        raise RuntimeError(f"{script} が exit code {exit_code} で失敗した。")
    await queue.put({"type": "step_end", "step": step, "script": script})


@app.get("/api/events")
async def events() -> StreamingResponse:
    """
    GET /api/events
    実行中のジョブの進捗イベントを SSE で流します。 done か error を流したら接続を閉じます。
    """
    if _current_job is None:
        raise HTTPException(status_code=404, detail="ジョブがまだ開始されてないよ。")

    # グローバル変数のほうは POST /api/run の中でいつ変わるとも分からない。
    # なのでこの時点での Job インスタンスの参照を握っておきます。
    job = _current_job

    async def stream() -> AsyncIterator[str]:
        while True:
            # queue に次のモノが put されるまで止まってるやつ。
            event = await job.queue.get()
            # SSE の形式は「data: (中身)」+ 空行。これだけで動く素朴なプロトコルです。
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event["type"] in ("done", "error"):
                return

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/shutdown")
async def shutdown() -> dict[str, bool]:
    """
    POST /api/shutdown
    サーバー自身を終了します。 run --rm で起動していれば、コンテナごと消えて終わりです。
    """
    if _server is None:
        raise HTTPException(status_code=500, detail="サーバーの参照が無い。 main() 以外から起動された?")
    # should_exit を立てると、 uvicorn はこのレスポンスを返し終えたあと、行儀よく終了してくれます。
    _server.should_exit = True
    return {"bye": True}


# shutdown エンドポイントから uvicorn を止めるために、 Server インスタンスをグローバルに握っておきます。
# NOTE: uvicorn.run(app) はお手軽だけど、 Server を内部で作って隠しちゃうので、外から止められません。
_server: uvicorn.Server | None = None


def main() -> int:
    global _server
    logging.basicConfig(level=logging.INFO)
    # NOTE: 0.0.0.0 で待ち受けます。 127.0.0.1 だとコンテナの外 (ホストのブラウザ) から届きません。
    config = uvicorn.Config(app, host="0.0.0.0", port=8000)
    _server = uvicorn.Server(config)
    _server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
