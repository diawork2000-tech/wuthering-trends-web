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
