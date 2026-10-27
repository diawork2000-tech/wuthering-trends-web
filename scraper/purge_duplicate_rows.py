"""同じURLで重複登録された行を、1行だけ残してゴミ箱へ移す。

登録済みURLの取得が途中で失敗しても処理を続けていた不具合のため、
広告が1回あたり約370件ずつ再登録されていた（2026-09〜10月）。
原因は trend_collector.get_existing_notion_urls 側で直してあり、
これは既に入ってしまった重複を片付けるための道具。

    既定は下見だけ。実際に動かすには --apply を付ける。
    ゴミ箱へ移すだけなので Notion 側で30日間は元に戻せる。

どの行を残すか:
  1. 人の判断が入っている行（採用済み、または制作状況が未着手以外）
     → 1つでもあれば、それを全部残す。どれを残すかを機械が決めてはいけない
  2. 出稿期間が入っている行
  3. いちばん古い行（最初に登録された行）

    実行: python purge_duplicate_rows.py [--apply]
"""

import argparse
import collections
import os
import sys
import time

from dotenv import load_dotenv

from notion_utils import notion_request, query_database_all
from purge_excluded import is_protected

load_dotenv()

AUDIT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "purge_duplicates_audit.log")


def fetch_all_rows(headers, database_id):
    rows, complete = query_database_all(headers, database_id)
    if not complete:
        # 途中までの一覧で判定すると、残すべき行を見落とす。止める。
        print("[Error] 一覧を全部読めなかったので中止します")
        sys.exit(1)
    return rows


def url_of(row):
    return (row["properties"].get("URL") or {}).get("url") or ""


def title_of(row):
    prop = row["properties"].get("タイトル", {})
    return "".join(t.get("plain_text", "") for t in prop.get("title", []))


def has_ad_period(row):
    return bool((row["properties"].get("出稿期間") or {}).get("rich_text"))


def choose(rows):
    """同じURLの行の束から (残す行, 消す行) を返す。"""
    protected = [r for r in rows if is_protected(r)[0]]
    if protected:
        keep = protected
    else:
        ranked = sorted(rows, key=lambda r: (not has_ad_period(r), r["created_time"]))
        keep = ranked[:1]
    keep_ids = {r["id"] for r in keep}
    return keep, [r for r in rows if r["id"] not in keep_ids]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="実際にゴミ箱へ移す")
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

    rows = fetch_all_rows(headers, database_id)
    groups = collections.defaultdict(list)
    for row in rows:
        if url_of(row):
            groups[url_of(row)].append(row)
    dup_groups = {u: g for u, g in groups.items() if len(g) > 1}

    targets = []
    kept_protected = 0
    by_category = collections.Counter()
    for group in dup_groups.values():
        keep, drop = choose(group)
        if any(is_protected(r)[0] for r in keep):
            kept_protected += 1
        for r in drop:
            targets.append(r)
            by_category[(r["properties"].get("カテゴリ", {}).get("select") or {}).get("name", "(なし)")] += 1

    print(f"全行数              : {len(rows)} 件")
    print(f"URLの種類           : {len(groups)} 種")
    print(f"重複しているURL     : {len(dup_groups)} 種")
    print(f"ゴミ箱へ移す行      : {len(targets)} 件")
    print(f"掃除後の行数        : {len(rows) - len(targets)} 件")
    print(f"人の判断を優先した束: {kept_protected} 種")
    print("カテゴリ別（移す行）:")
    for name, n in by_category.most_common():
        print(f"    {n:5d}  {name}")

    if not args.apply:
        print("\n下見だけです。実行するには --apply を付けてください。")
        return

    moved = failed = 0
    with open(AUDIT_LOG, "a", encoding="utf-8") as log:
        for r in targets:
            res = notion_request("PATCH", f"https://api.notion.com/v1/pages/{r['id']}",
                                 headers, json={"archived": True}, timeout=30)
            if res.status_code == 200:
                moved += 1
                log.write(f"{r['id']}\t{url_of(r)}\t{title_of(r)}\n")
            else:
                failed += 1
                print(f"  [Error] 失敗 {r['id']}: {res.text[:120]}")
            time.sleep(0.35)  # Notionの毎秒3回制限に合わせる

    print(f"\nゴミ箱へ移しました: {moved} 件 / 失敗 {failed} 件")
    print(f"移した行の記録: {AUDIT_LOG}")
    print("Notion のゴミ箱から30日間は元に戻せます。")


if __name__ == "__main__":
    main()
