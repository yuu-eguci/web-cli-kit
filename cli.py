import argparse
import logging
import time

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """
    コマンドライン引数の定義です。
    NOTE: web.py はこの cli を subprocess で呼び出すだけなので、引数を増やしたいときは
          ここと、 web.py の RunRequest / _build_command、 index.html のフォームを一緒に直します。
    """
    parser = argparse.ArgumentParser(
        description="web-cli-kit のデフォルト cli. メッセージを受け取って数秒スリープするだけのサンプルです。",
    )
    parser.add_argument(
        "--message",
        required=True,
        help="表示するメッセージ。 fork したら、あなたのツールに必要な引数へ書き換えてください。",
    )
    parser.add_argument(
        "--seconds",
        default=3,
        type=int,
        help="スリープする秒数。 (このサンプルが「時間のかかる処理」のフリをするための引数です。)",
    )
    return parser


def main() -> int:
    # NOTE: logging は標準では stderr に出ます。 web.py 側は stderr を stdout にまとめて拾うので、
    #       ここで print ではなく logger を使っても、ちゃんと SSE でブラウザまで流れていきます。
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args()

    logger.info("受け取ったメッセージ: %s", args.message)
    logger.info("%d 秒かけて、何か重たい処理をするフリをするよ。", args.seconds)

    # seconds を 3 分割して、途中経過を出しながらスリープします。
    # (SSE で一行ずつログが流れる様子を体感してもらうための演出です。)
    total_steps = 3
    seconds_per_step = args.seconds / total_steps
    for step in range(1, total_steps + 1):
        time.sleep(seconds_per_step)
        logger.info("  ...進行中 (%d/%d)", step, total_steps)

    logger.info("処理おわり！ メッセージをもう一度どうぞ: %s", args.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
