"""カテゴリ「SNS」の投稿を、媒体を指定してゴミ箱へ移す。

収集の作りを直したあと、古い形式で登録された行を入れ替えるための道具。
消したぶんは次の巡回で取り直されるので、翻訳や動画URLが付いた形で
入り直る。

    既定は下見だけ。実際に動かすには --apply を付ける。
    ゴミ箱へ移すだけなので Notion 側で30日間は元に戻せる。

保護するもの:
  - 採用済み、または制作状況が 制作中 / 投稿済み / 見送り の行
    人が「これで作る」「これは作らない」と決めた記録を、
    入れ替えのついでに消してはいけない。

    実行: python purge_sns_posts.py --platform X [--apply]
"""

import argparse
import os
import sys
import time

from dotenv import load_dotenv

from notion_utils import notion_request
from purge_excluded import is_protected

load_dotenv()

AUDIT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "purge_sns_audit.log")


def fetch_sns_rows(headers, database_id, platform):
    """カテゴリ「SNS」かつ指定の媒体の行をすべて取る。"""
    rows, cursor = [], None
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    conditions = [{"property": "カテゴリ", "select": {"equals": "SNS"}}]
    if platform:
        conditions.append({"property": "媒体", "select": {"equals": platform}})

    while True:
        payload = {"filter": {"and": conditions}, "page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        res = notion_request("POST", url, headers, json=payload, timeout=30)
        if res.status_code != 200:
            print(f"[Error] 一覧の取得に失敗しました: {res.text[:200]}")
            sys.exit(1)
        data = res.json()
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            return rows
        cursor = data["next_cursor"]


def title_of(row):
    prop = row["properties"].get("タイトル", {})
    return "".join(t.get("plain_text", "") for t in prop.get("title", []))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", default="", help="媒体で絞る（X / BiliBili / Weibo / Reddit）。省略すると全部")
    parser.add_argument("--apply", action="store_true", help="実際にゴミ箱へ移す")
    parser.add_argument("--limit", type=int, default=1000, help="一度に移す上限")
    args = parser.parse_args()

    api_key = os.getenv("NOTION_API_KEY")
    database_id = os.getenv("NOTION_DATABASE_ID")
    if not api_key or not database_id:
        print("[Error] NOTION_API_KEY と NOTION_DATABASE_ID が要ります")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    rows = fetch_sns_rows(headers, database_id, args.platform)
    label = args.platform or "全媒体"
    print(f"カテゴリ「SNS」/ 媒体「{label}」の行: {len(rows)} 件")

    targets, protected = [], []
    for row in rows:
        keep, reason = is_protected(row)
        (protected if keep else targets).append((row, reason))

    print(f"  入れ替え対象     : {len(targets)} 件")
    print(f"  人の判断があり保護: {len(protected)} 件")
    for row, reason in protected:
        print(f"    [保護] {reason}: {title_of(row)[:50]}")

    if not args.apply:
        print("\n下見だけです。実行するには --apply を付けてください。")
        for row, _ in targets[:5]:
            print(f"    - {title_of(row)[:60]}")
        if len(targets) > 5:
            print(f"    ... 他 {len(targets) - 5} 件")
        return

    moved, failed = 0, 0
    with open(AUDIT_LOG, "a", encoding="utf-8") as log:
        for row, _ in targets[: args.limit]:
            res = notion_request(
                "PATCH", f"https://api.notion.com/v1/pages/{row['id']}",
                headers, json={"archived": True}, timeout=30,
            )
            if res.status_code == 200:
                moved += 1
                log.write(f"{row['id']}\t{label}\t{title_of(row)}\n")
            else:
                failed += 1
                print(f"  [Error] 失敗 {row['id']}: {res.text[:120]}")
            time.sleep(0.35)  # Notionの毎秒3回制限に合わせる

    print(f"\nゴミ箱へ移しました: {moved} 件 / 失敗 {failed} 件")
    print(f"移した行の記録: {AUDIT_LOG}")
    print("Notion のゴミ箱から30日間は元に戻せます。次の巡回で取り直されます。")


if __name__ == "__main__":
    main()
