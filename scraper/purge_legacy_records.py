"""旧ルールで収集された Notion のレコードをまとめてゴミ箱へ移す。

判定基準:
  - トピックDB    : 「制作状況」が未設定のもの（＝スコア刷新より前に作られたカード）
  - YouTube動画DB : 「再生数」が未設定のもの（＝統計取得を入れる前に作られた行）

Notion API に一括削除は無いため1件ずつ archived=true を送る。
API は概ね毎秒3リクエストが上限なので、それに合わせて間隔を空ける。

削除といっても Notion のゴミ箱へ移すだけで、約30日は画面から復元できる。

使い方:
    python purge_legacy_records.py --dry-run        # 対象件数を数えるだけ
    python purge_legacy_records.py --limit 5        # 5件だけ実際に削除して動作確認
    python purge_legacy_records.py --apply          # 全件削除
"""

import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from dotenv import load_dotenv

from notion_utils import notion_request

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv(os.path.join(BASE_DIR, "../.env.local"))

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
TOPIC_DB = os.getenv("NOTION_INTELLIGENCE_DB_ID")
VIDEO_DB = os.getenv("NOTION_DATABASE_ID")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


def fetch_all_pages(db_id):
    """データベースの全ページを取得する（100件ずつページング）。"""
    pages = []
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        res = notion_request(
            "POST",
            f"https://api.notion.com/v1/databases/{db_id}/query",
            HEADERS,
            json=body,
            timeout=30,
        )
        if res is None or res.status_code != 200:
            detail = res.text[:200] if res is not None else "no response"
            print(f"  [Error] 一覧の取得に失敗しました: {detail}")
            break
        data = res.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        time.sleep(0.34)
    return pages


def is_legacy_topic(page):
    """スコア刷新より前のトピックカードか（「制作状況」が入っていない）。"""
    return (page.get("properties", {}).get("制作状況") or {}).get("select") is None


def is_legacy_video(page):
    """統計取得より前の動画行か（「再生数」が入っていない）。"""
    return (page.get("properties", {}).get("再生数") or {}).get("number") is None


class RateLimiter:
    """送信の間隔を空けて、Notion の毎秒3リクエスト上限を超えないようにする。

    1件ずつ順番に送ると1件あたり往復1秒以上かかり、上限の2割程度しか使えない。
    複数スレッドで並行して送りつつ、送信の開始間隔だけをここで揃える。
    """

    def __init__(self, min_interval):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            start_at = max(now, self._next_at)
            self._next_at = start_at + self.min_interval
        delay = start_at - now
        if delay > 0:
            time.sleep(delay)


limiter = RateLimiter(0.34)


def archive_page(page_id):
    limiter.wait()
    res = notion_request(
        "PATCH",
        f"https://api.notion.com/v1/pages/{page_id}",
        HEADERS,
        json={"archived": True},
        timeout=20,
    )
    return res is not None and res.status_code == 200


def purge(label, db_id, predicate, limit=None, apply=False):
    """該当レコードが無くなるまで、取得と削除を繰り返す。

    Notion のクエリは1万件までしか辿れず、それ以上あっても has_more=False を返す。
    そのため「全件取得してから消す」ができない。1万件ずつ消しては取り直す。
    """
    if not db_id:
        print(f"\n=== {label}: データベースIDが未設定のためスキップ ===")
        return 0, 0

    print(f"\n=== {label} ===")
    total_done = total_failed = 0

    for rnd in range(1, 60):  # 暴走防止の上限（1周1万件なので最大60万件）
        pages = fetch_all_pages(db_id)
        targets = [p for p in pages if predicate(p)]
        keep = len(pages) - len(targets)

        if not targets:
            print(f"  第{rnd}周: 対象なし。残り {keep} 件で完了です。")
            break

        if limit is not None:
            targets = targets[:limit]

        print(f"  第{rnd}周: 取得 {len(pages)} 件 / 削除対象 {len(targets)} 件 / 残す {keep} 件")

        if not apply:
            print("  (確認のみ。実際の削除は行っていません)")
            return len(targets), 0

        done = failed = 0
        counter_lock = threading.Lock()
        started = time.monotonic()

        def work(idx_page):
            nonlocal done, failed
            i, page = idx_page
            ok = archive_page(page["id"])
            with counter_lock:
                if ok:
                    done += 1
                else:
                    failed += 1
                seen = done + failed
                if seen % 250 == 0 or seen == len(targets):
                    rate = seen / max(0.001, (time.monotonic() - started) / 60)
                    remain = (len(targets) - seen) / max(1.0, rate)
                    print(
                        f"    進捗 {seen}/{len(targets)} (成功 {done} / 失敗 {failed}) "
                        f"{rate:.0f}件/分 残り約{remain:.0f}分"
                    )

        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(work, enumerate(targets, 1)))

        total_done += done
        total_failed += failed

        if limit is not None:
            break  # 動作確認モードでは1周で終える
        if failed and not done:
            print("  [Warning] 1件も削除できませんでした。中断します。")
            break

    print(f"  {label} 完了: 累計 {total_done} 件をゴミ箱へ移動 / 失敗 {total_failed} 件")
    return total_done, total_done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="実際に削除する")
    ap.add_argument("--dry-run", action="store_true", help="件数を数えるだけ")
    ap.add_argument("--limit", type=int, default=None, help="処理する件数の上限（動作確認用）")
    ap.add_argument("--only", choices=["topics", "videos"], default=None)
    args = ap.parse_args()

    if not NOTION_API_KEY:
        print("NOTION_API_KEY が見つかりません。中止します。")
        return

    apply = args.apply and not args.dry_run

    total = deleted = 0
    if args.only in (None, "topics"):
        t, d = purge("マルチメディア(トピック)DB", TOPIC_DB, is_legacy_topic, args.limit, apply)
        total += t
        deleted += d
    if args.only in (None, "videos"):
        t, d = purge("YouTube動画DB", VIDEO_DB, is_legacy_video, args.limit, apply)
        total += t
        deleted += d

    print(f"\n対象 {total} 件 / 削除 {deleted} 件")
    if not apply:
        print("実際に削除するには --apply を付けて実行してください。")


if __name__ == "__main__":
    main()
