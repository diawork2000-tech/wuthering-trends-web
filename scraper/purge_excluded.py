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
from datetime import datetime, timezone

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


# 人が判断を下した行。除外ワードに引っかかっても自動でアーカイブしない。
PROTECTED_STATUSES = {"制作中", "投稿済み", "見送り"}


def is_protected(page):
    """人の判断が入っている行かを判定する。

    採用チェック、または制作状況が未着手以外なら保護対象。
    除外ワードは機械判定であり、人が「これで作る」「これは作らない」と
    決めた記録を機械判定で消してはいけない。
    """
    props = page.get("properties", {})
    if props.get("採用", {}).get("checkbox"):
        return True, "採用済み"
    status = (props.get("制作状況", {}).get("select") or {}).get("name")
    if status in PROTECTED_STATUSES:
        return True, f"制作状況={status}"
    return False, ""


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
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="1回でアーカイブする上限件数（既定200）。想定外の大量削除を防ぐため",
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
    protected = []
    for page in pages:
        title, category, url = read_props(page)
        if not (title and should_exclude(title, exclude_words)):
            continue
        guarded, reason = is_protected(page)
        if guarded:
            protected.append((title, reason))
            continue
        hits.append((page["id"], title, category, url))

    if protected:
        print(f"=== 除外ワードに該当するが、人の判断が入っているため保護: {len(protected)} 件 ===")
        for title, reason in protected:
            print(f"  [保護:{reason}] {title[:50]}")
        print()

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

    # 想定外の大量削除を防ぐ。除外ワードを1語足しただけで数百件が対象に
    # なることがあり、確認せずに走らせると取り返しがつかない。
    if len(hits) > args.limit:
        print(f"\n[中止] 対象が {len(hits)} 件あり、上限 {args.limit} 件を超えています。")
        print("       内容を確認したうえで --limit を明示的に指定してください。")
        return 1

    print(f"\nアーカイブを実行します...")
    audit_path = os.path.join(BASE_DIR, "purge_audit.log")
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    ok = 0
    # 何を消したかを必ず残す。復元はNotionのゴミ箱から行うが、
    # 「何が消えたのか」はここを見ないと後から分からない。
    with open(audit_path, "a", encoding="utf-8") as audit:
        audit.write(f"# {stamp} purge_excluded.py --apply 対象{len(hits)}件\n")
        for page_id, title, category, url in hits:
            res = notion_request(
                "PATCH",
                f"https://api.notion.com/v1/pages/{page_id}",
                HEADERS,
                json={"archived": True},
                timeout=10,
            )
            if res.status_code in (200, 201):
                ok += 1
                audit.write(f"{stamp}\tARCHIVED\t{page_id}\t{category}\t{title}\t{url}\n")
            else:
                print(f"  [失敗] {title[:40]} -> {res.status_code}")
                audit.write(f"{stamp}\tFAILED({res.status_code})\t{page_id}\t{category}\t{title}\t{url}\n")
            time.sleep(0.25)  # Notion のレート制限（3req/sec）回避

    print(f"\n完了: {ok} / {len(hits)} 件をアーカイブしました（30日間は復元可能）。")
    print(f"      記録: {audit_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
