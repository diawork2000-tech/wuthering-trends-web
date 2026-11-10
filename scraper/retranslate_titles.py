"""翻訳が止まっていた間（2026-09-06〜11-10）に、訳されずに入った見出しを訳し直す。

翻訳の窓口が Google に止められ、YouTube の見出しや公式SNSの投稿が英語・韓国語などの
まま登録されていた。窓口を替えて直したので（trend_collector.translate_if_needed）、
さかのぼって訳す。

    既定は下見だけ（訳した結果を数件見せる）。実際に書き換えるには --apply を付ける。
    元の見出しは「原文」の列に残す。途中で止めても、もう一度動かせば続きから進む
    （日本語になった行は対象から外れるため）。

対象:
  - YouTube の行：見出しにかなが無いもの（広告は素材のファイル名なので除く）
  - SNS の行：言語が翻訳対象（config.json の sns.translate_langs）のもの。英語は訳さない

間隔をあけて少しずつ訳す。まとめて投げると、この窓口も止められかねない。
毎時02分〜10分の巡回とは重ならないよう、15分〜55分の間に動かすこと。

    実行: python retranslate_titles.py [--apply] [--limit N] [--since 2026-09-06]
"""

import argparse
import io
import json
import os
import re
import sys
import time

from dotenv import load_dotenv

from notion_utils import notion_request, query_database_all
from trend_collector import TRANSLATION_STATS, translate_if_needed

load_dotenv()

AUDIT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "retranslate_audit.log")
KANA = re.compile(r"[ぁ-んァ-ヶ]")


def title_of(row):
    return "".join(t.get("plain_text", "") for t in (row["properties"].get("タイトル") or {}).get("title") or [])


def select_of(row, name):
    return ((row["properties"].get(name) or {}).get("select") or {}).get("name", "")


def text_of(row, name):
    rich = (row["properties"].get(name) or {}).get("rich_text") or []
    return rich[0].get("plain_text", "") if rich else ""


def needs_translation(row, sns_langs):
    title = title_of(row)
    category = select_of(row, "カテゴリ")
    if not title or KANA.search(title) or category == "広告":
        return False
    if category == "SNS":
        return select_of(row, "言語") in sns_langs
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="実際に書き換える")
    parser.add_argument("--limit", type=int, default=0, help="この件数で止める（0なら全部）")
    parser.add_argument("--since", default="2026-09-06", help="この日以降に登録された行だけ")
    parser.add_argument("--interval", type=float, default=1.0, help="1件ごとに待つ秒数")
    args = parser.parse_args()

    headers = {
        "Authorization": f"Bearer {os.getenv('NOTION_API_KEY')}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    here = os.path.dirname(os.path.abspath(__file__))
    with io.open(os.path.join(here, "config.json"), encoding="utf-8") as f:
        sns_langs = set(json.load(f).get("sns", {}).get("translate_langs", []))

    rows, complete = query_database_all(
        headers, os.getenv("NOTION_DATABASE_ID"),
        filter={"timestamp": "created_time", "created_time": {"on_or_after": f"{args.since}T00:00:00Z"}},
    )
    if not complete:
        print("[Error] 一覧を全部読めなかったので中止します")
        sys.exit(1)
    targets = [r for r in rows if needs_translation(r, sns_langs)]
    if args.limit:
        targets = targets[: args.limit]
    print(f"{args.since} 以降の行: {len(rows)} 件 / 訳し直す対象: {len(targets)} 件")

    done = failed = 0
    log = io.open(AUDIT_LOG, "a", encoding="utf-8") if args.apply else None
    try:
        for row in targets:
            original = text_of(row, "原文") or title_of(row)
            before = TRANSLATION_STATS["failed"]
            translated = translate_if_needed(original)
            if TRANSLATION_STATS["failed"] > before or translated == original:
                failed += 1
                # 続けて失敗するなら窓口に止められている。粘らずに止める。
                if failed >= 10 and done == 0:
                    print("[Error] 訳せない状態が続くので中止します（窓口に止められている可能性）")
                    break
                time.sleep(args.interval)
                continue

            if not args.apply:
                print(f"  原: {original[:50]}\n  訳: {translated[:50]}")
                done += 1
                time.sleep(args.interval)
                continue

            props = {"タイトル": {"title": [{"text": {"content": translated[:2000]}}]}}
            if not text_of(row, "原文"):
                props["原文"] = {"rich_text": [{"text": {"content": original[:1900]}}]}
            res = notion_request("PATCH", f"https://api.notion.com/v1/pages/{row['id']}",
                                 headers, json={"properties": props}, timeout=30)
            if res.status_code == 200:
                done += 1
                log.write(f"{row['id']}\t{original}\t{translated}\n")
            else:
                failed += 1
                print(f"  [Error] 書き換え失敗 {row['id']}: {res.text[:120]}")
            if done and done % 100 == 0:
                print(f"  …{done} 件完了")
            time.sleep(args.interval)
    finally:
        if log:
            log.close()

    verb = "書き換えた" if args.apply else "訳せた（下見）"
    print(f"{verb}: {done} 件 / 訳せなかった・失敗: {failed} 件")
    if not args.apply:
        print("下見だけです。書き換えるには --apply を付けてください。")


if __name__ == "__main__":
    main()
