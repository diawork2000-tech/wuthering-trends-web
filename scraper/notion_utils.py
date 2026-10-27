"""Notion API 呼び出しの共通ラッパー。

送信件数の多いループ（動画やトピックカードの一括登録・アーカイブ）で
429 (Rate Limited) を受けると、そのカードだけ黙って欠落していた。
Retry-After ヘッダーを尊重しつつ指数バックオフで自動リトライする。
"""

import time
import requests


def notion_request(method, url, headers, json=None, timeout=10, max_retries=5):
    """429/5xx を自動リトライする Notion API 呼び出し。

    リトライを使い切った場合はその時点のレスポンス（またはネットワーク例外）を
    そのまま返す/送出するので、呼び出し側の既存のエラーハンドリングは変更不要。
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            res = requests.request(method, url, headers=headers, json=json, timeout=timeout)
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)
            continue

        if res.status_code == 429 and attempt < max_retries - 1:
            wait = float(res.headers.get("Retry-After", 2 ** attempt))
            print(f"    [Notion Rate Limited] {wait:.1f}秒待機してリトライします ({attempt + 1}/{max_retries})")
            time.sleep(wait)
            continue

        if res.status_code >= 500 and attempt < max_retries - 1:
            time.sleep(2 ** attempt)
            continue

        return res

    return res


# Notion は1回の問い合わせで最大1万件までしか返さない。その先は has_more が
# 立たずに黙って終わる。動画DBは2026-10時点で1万5千件を超えており、
# 登録済みURLの確認がこの上限で頭打ちになった結果、見えない側の行を
# 「未登録」と判定して同じ動画を何度も登録していた（広告が最大6回）。
NOTION_QUERY_CAP = 10000


def query_database_all(headers, database_id, filter=None, page_size=100):
    """データベースの行を、1万件の上限を越えて全部たどる。

    登録日時の古い順に並べて読み、1回の問い合わせが終わるたびに、最後に
    読んだ行の登録日時から続きを問い合わせ直す。新しい行が1件も出てこなく
    なったら読み終わり。登録日時は分単位なので境目の行は2回返ってくるが、
    行のIDで重複を除く。

    「1万件ちょうどで止まったら続きがある」とは判定しない。Notion は
    ゴミ箱に入れたばかりの行も上限の数に含めるらしく、1万件より手前
    （実測 9,998件）で has_more を立てずに終わることがある。件数で
    判定していた版は、1万3千件あるDBを9,998件で「全部読めた」と扱った。

    戻り値は (行のリスト, 全部読めたか)。途中で失敗したら False を返す。
    全部読めていない一覧で重複判定や削除をしてはいけない。
    """
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    rows, seen = [], set()
    since = None
    while True:
        conditions = [filter] if filter else []
        if since:
            conditions.append({"timestamp": "created_time", "created_time": {"on_or_after": since}})
        body = {
            "page_size": page_size,
            "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
        }
        if len(conditions) == 1:
            body["filter"] = conditions[0]
        elif conditions:
            body["filter"] = {"and": conditions}

        cursor, new_rows, last_time = None, 0, since
        while True:
            if cursor:
                body["start_cursor"] = cursor
            try:
                res = notion_request("POST", url, headers, json=body, timeout=30)
            except Exception as e:
                print(f"  [Error] Notionの問い合わせ中に通信が失敗しました: {e}")
                return rows, False
            if res.status_code != 200:
                print(f"  [Error] Notionの問い合わせに失敗しました: {res.status_code} {res.text[:200]}")
                return rows, False
            data = res.json()
            for page in data.get("results", []):
                if page["id"] not in seen:
                    seen.add(page["id"])
                    rows.append(page)
                    new_rows += 1
                last_time = page.get("created_time", last_time)
            if not data.get("has_more") or not data.get("next_cursor"):
                break
            cursor = data["next_cursor"]

        # 続きを問い合わせて新しい行が出てこなければ、そこで全部。
        # 行の総数は有限なので、新しい行が出続けることはなく必ず止まる。
        if new_rows == 0:
            return rows, True
        since = last_time
