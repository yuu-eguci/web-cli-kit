web-cli-kit
===

## このオモチャが目指すもの

- discord-messages repository の、こんな方式↓が結構気に入った
    - `docker compose run --rm --service-ports web` って感じで web を起動する
    - `open http://localhost:8000` って感じで画面を見る
    - 画面にあるのは、 cli のコマンドライン引数を入力できるフォーム
    - フォームをバックエンドへ送信すると、バリデーションして、それをコマンドライン引数として cli を実行する
    - 実行が終わったら SSE で結果を画面へ返し、画面では「終わったよ閉じていいよ」的なボタンを出す
- ようは、「本当にやりたいことは cli なんだが、コマンドライン引数をもっとラクに入力したいんだよな」っていうニーズを叶える構成なのだ
- また別の cli を作るとき、あらかじめ cli.py web.py index.html だけあって、 fork してその中を書き換えればそのセットになる、というキットがあったらいいな……それが web-cli-kit
- デフォルトの cli は、ただ簡単なコマンドライン引数を受け取って、数秒スリープして終わるだけ
    - デフォルトの web は、「送信」ボタンでその cli を呼び出し、 cli が終わったら「終わったよ閉じていいよ」的なボタンを出す
- discord-messages repository のよいところを継承
    - 理解のため、コメントをちゃんと書いている
    - cli 単体でも起動できる (そりゃそうだ)
    - ruff と pytest と CI 導入済み
    - README の "コミット前確認" らへんに dev への気遣いが見える

## ファイル構成

- cli.py
    - キットの主役。引数を受け取って数秒スリープするだけのサンプル。ここを書き換えて自分のツールにする。
- web.py
    - cli.py をブラウザから呼ぶための FastAPI サーバ。フォーム送信を受けて cli を subprocess 実行し、出力を SSE で画面へ流す。
- index.html
    - web.py が返す 1 枚もののフロント。フォームと、実行ログの表示エリアと、「終わったよ閉じていいよ」ボタン。
- tests/
    - pytest。 cli と web の動きを確認します。 subprocess は手元の python だけで完結します。
- そのほか
    - Dockerfile / compose.yaml (Docker ジョブ実行型)、 Pipfile (依存)、 pyproject.toml (ruff, pytest)、 .env.example (web UI のフォーム初期値)、 .github/workflows/ci.yml (main への push と PR で下のコミット前確認を回す)。

## How to start

```bash
# 最初のセットアップ。
# up -d --build じゃなくて build だけでいいのは、常駐サービスではなく単発ジョブ実行型だから。
# (最初は Pipfile.lock が無いので、下の 3 手で lock を作ってから使い始めます。 lock コミット済みならこの 3 手は build だけで OK。)
docker compose build
docker compose run --rm app pipenv lock
docker compose build

# Ruff を動かしてみる
docker compose run --rm app pipenv run ruff check .
docker compose run --rm app pipenv run ruff check --fix .

# 自慢の web UI はこちら。
(sleep 2 && open http://localhost:8000) & docker compose run --rm --service-ports web
# もしポートが埋まってたら↓
# (sleep 2 && open http://localhost:8000) & docker compose run --rm -p 8080:8000 --service-ports web

# cli 単体でも動きます (そりゃそうだ)
docker compose run --rm app pipenv run python cli.py --help
docker compose run --rm app pipenv run python cli.py --message "やっほー相棒" --seconds 3
```

## fork して自分のツールにする

やりたい cli があるなら、だいたいこのへんを触ればいい。

- cli.py の build_parser に、自分のツールに必要な引数を足す (本体の処理も書く)
- web.py の RunRequest と _build_command に、同じ引数を足す (バリデーションもここ)
    - 値は `--name=値` の形で渡すと、 `-` で始まる値もオプションと間違われません
    - フォームの空欄は None で届くため、引数ごと省いて cli のデフォルトに任せます
- index.html のフォームに、同じ入力欄を足す
- tests/ のテストも、自分の引数と出力に合わせて直します
- cli を 001 → 002 → 003 のように複数本つなげたくなったら、 web.py の _run_real でループを回して _run_script を複数回呼ぶ (元ネタの discord-messages がその作り)

秘密情報 (token など) は .env ではなくコマンドライン引数で渡す思想です。 .env は web UI のフォーム初期値専用。

## コミット前確認

CI でも同じ内容を実行します。

```bash
docker compose run --rm app pipenv run ruff check .
docker compose run --rm app pipenv run ruff format --check .
docker compose run --rm app pipenv run pytest
```
