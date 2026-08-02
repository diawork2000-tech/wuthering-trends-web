"""既に Notion に入ってしまった「本来除外されるべき動画」を後片付けするツール。

除外ワード判定は trend_collector.should_exclude をそのまま使うので、
config.json の除外ワードを増やしたあとに実行すれば過去分にも遡って適用できる。

使い方:
    python purge_excluded.py           # 確認のみ（何も消さない）
    python purge_excluded.py --apply   # 実際にアーカイブする

Notion の archived=true は「ゴミ箱に移す」操作で、30日間は Notion の UI から
復元できる。完全削除ではない。
"""

import os
import sys
import json
import time
import argparse

import requests
from dotenv import load_dotenv

from trend_collector import should_exclude
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
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


def load_exclude_words():
    with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
        return json.load(f).get("youtube", {}).get("exclude_words", [])


def fetch_all_pages():
    """データベース内の全ページを取得する（100件ずつページング）。"""
    pages = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor

        res = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
            headers=HEADERS,
            json=payload,
            timeout=15,
        )
        if res.status_code != 200:
            raise RuntimeError(f"Notion query failed: {res.status_code} {res.text}")

        data = res.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return pages


def read_props(page):
    props = page.get("properties", {})
    title = ""
    for key in props:
        if props[key].get("type") == "title" and props[key].get("title"):
            title = "".join(t.get("plain_text", "") for t in props[key]["title"])
            break
    category = (props.get("カテゴリ", {}).get("select") or {}).get("name", "")
    url = props.get("URL", {}).get("url") or ""
    return title, category, url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="実際にアーカイブする（付けない場合は確認のみ）",
    )
    args = parser.parse_args()

    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        print("NOTION_API_KEY / NOTION_DATABASE_ID が見つかりません。")
        return 1

    exclude_words = load_exclude_words()
    print(f"除外ワード: {exclude_words}\n")

    print("Notion データベースを走査中...")
    pages = fetch_all_pages()
    print(f"  登録件数: {len(pages)} 件\n")

    hits = []
    for page in pages:
        title, category, url = read_props(page)
        if title and should_exclude(title, exclude_words):
            hits.append((page["id"], title, category, url))

    if not hits:
        print("除外対象に該当する動画はありませんでした。")
        return 0

    print(f"=== 除外対象に該当: {len(hits)} 件 ===")
    for _, title, category, url in hits:
        print(f"  [{category}] {title}")
        print(f"      {url}")

    if not args.apply:
        print(f"\n確認のみのため、まだ何も削除していません。")
        print(f"実行するには: python purge_excluded.py --apply")
        return 0

    print(f"\nアーカイブを実行します...")
    ok = 0
    for page_id, title, _, _ in hits:
        res = notion_request(
            "PATCH",
            f"https://api.notion.com/v1/pages/{page_id}",
            HEADERS,
            json={"archived": True},
            timeout=10,
        )
        if res.status_code in (200, 201):
            ok += 1
        else:
            print(f"  [失敗] {title[:40]} -> {res.status_code}")
        time.sleep(0.25)  # Notion のレート制限（3req/sec）回避

    print(f"\n完了: {ok} / {len(hits)} 件をアーカイブしました（30日間は復元可能）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
