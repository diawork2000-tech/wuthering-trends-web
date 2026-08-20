"""広告カテゴリから、本家チャンネル以外の動画をゴミ箱へ移す。

本家の広告アカウントは、自社が作った素材だけでなく個人配信者の動画も
そのまま広告として回している。収集側 (ad_collector) は config.json の
`official_channels` で線を引くようになったが、それ以前に登録された行は
残ったままなので、後から揃えるための道具。

    既定は下見だけ。実際に動かすには --apply を付ける。
    ゴミ箱へ移すだけなので Notion 側で30日間は元に戻せる。

保護するもの:
  - 採用済み、または制作状況が 制作中 / 投稿済み / 見送り の行
    人が「これで作る」「これは作らない」と決めた記録を、機械判定で
    消してはいけない。

    実行: python purge_nonofficial_ads.py [--apply] [--limit N]
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from dotenv import load_dotenv

from ad_collector import fetch_video_meta, is_official_channel
from notion_utils import notion_request
from purge_excluded import is_protected

load_dotenv()

AUDIT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "purge_ads_audit.log")


def load_official_channels():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("ad_transparency", {}).get("official_channels", [])


def video_id_of(url):
    if not url or "youtube.com/watch?v=" not in url:
        return ""
    return url.split("watch?v=", 1)[1].split("&", 1)[0]


def fetch_ad_rows(headers, database_id):
    """カテゴリ「広告」の行をすべて取る。"""
    rows, cursor = [], None
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    while True:
        payload = {"filter": {"property": "カテゴリ", "select": {"equals": "広告"}}, "page_size": 100}
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="実際にゴミ箱へ移す")
    parser.add_argument("--limit", type=int, default=500, help="一度に移す上限")
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

    official = load_official_channels()
    if not official:
        print("[Error] config.json の official_channels が空です。全部消してしまうので中止します")
        sys.exit(1)

    rows = fetch_ad_rows(headers, database_id)
    print(f"カテゴリ「広告」の行: {len(rows)} 件")

    # 判定はチャンネル名ではなくハンドルで行う。配信者側にも
    # 「Wuthering Waves」「〜official」を名乗るチャンネルが実在する。
    ids = [video_id_of((r["properties"].get("URL") or {}).get("url")) for r in rows]
    with ThreadPoolExecutor(max_workers=12) as pool:
        metas = list(pool.map(lambda v: fetch_video_meta(v) if v else {"channel_url": "", "channel": ""}, ids))

    targets, protected, unknown = [], [], []
    for row, meta in zip(rows, metas):
        if not meta.get("channel_url"):
            # 判定できないものは触らない。消すより残す方が取り返しがつく
            unknown.append((row, meta))
            continue
        if is_official_channel(meta["channel_url"], official):
            continue
        keep, reason = is_protected(row)
        if keep:
            protected.append((row, meta, reason))
            continue
        targets.append((row, meta))

    print(f"  本家以外で削除対象 : {len(targets)} 件")
    print(f"  人の判断があり保護 : {len(protected)} 件")
    print(f"  判定できず据え置き : {len(unknown)} 件")
    for row, meta, reason in protected:
        title = (row["properties"]["タイトル"]["title"] or [{}])[0].get("plain_text", "")
        print(f"    [保護] {reason}: {title[:50]}")

    if not args.apply:
        print("\n下見だけです。実行するには --apply を付けてください。")
        for row, meta in targets[:10]:
            title = (row["properties"]["タイトル"]["title"] or [{}])[0].get("plain_text", "")
            print(f"    - {meta['channel'][:20]:20s} {title[:50]}")
        if len(targets) > 10:
            print(f"    ... 他 {len(targets) - 10} 件")
        return

    moved, failed = 0, 0
    with open(AUDIT_LOG, "a", encoding="utf-8") as log:
        for row, meta in targets[: args.limit]:
            title = (row["properties"]["タイトル"]["title"] or [{}])[0].get("plain_text", "")
            res = notion_request(
                "PATCH", f"https://api.notion.com/v1/pages/{row['id']}",
                headers, json={"archived": True}, timeout=30,
            )
            if res.status_code == 200:
                moved += 1
                log.write(f"{row['id']}\t{meta['channel']}\t{title}\n")
            else:
                failed += 1
                print(f"  [Error] 失敗 {row['id']}: {res.text[:120]}")
            time.sleep(0.35)  # Notionの毎秒3回制限に合わせる

    print(f"\nゴミ箱へ移しました: {moved} 件 / 失敗 {failed} 件")
    print(f"移した行の記録: {AUDIT_LOG}")
    print("Notion のゴミ箱から30日間は元に戻せます。")


if __name__ == "__main__":
    main()
