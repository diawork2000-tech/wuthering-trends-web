"""共有ロガー: 全自動化スクリプトの実行結果をNotion「自動化実行ログ」DBに記録し、
エラー時のみ専用Discord Webhookへ通知する。

正本: claude_hybrid_workspace/shared_libs/automation_logger.py
配布先(物理コピー): wuthering-trends-web/scraper/shared/, youtube_automator/shared/,
                     youtube_multi_uploader/shared/
更新したら sync_to_projects.ps1 を実行して各プロジェクトへコピーし直すこと。
"""

import os
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

import requests

JST = timezone(timedelta(hours=9))
_MAX_MESSAGE_LEN = 1900


def _env(name, default=None):
    return os.getenv(name, default)


def _notion_request(method, url, headers, json=None, timeout=10, max_retries=5):
    """notion_utils.notion_request と同じリトライ設計(429/5xxを指数バックオフ)。
    コピー配布する都合上、依存を増やさないためここに複製している。"""
    res = None
    for attempt in range(max_retries):
        try:
            res = requests.request(method, url, headers=headers, json=json, timeout=timeout)
        except requests.exceptions.RequestException:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)
            continue

        if res.status_code == 429 and attempt < max_retries - 1:
            wait = float(res.headers.get("Retry-After", 2 ** attempt))
            time.sleep(wait)
            continue

        if res.status_code >= 500 and attempt < max_retries - 1:
            time.sleep(2 ** attempt)
            continue

        return res

    return res


def _notify_discord_if_error(project_name, status, message, webhook_url, alert_enabled):
    if status != "error" or not alert_enabled or not webhook_url:
        return
    try:
        content = f"🔴【自動化エラー】{project_name}\n内容: {message[:300]}"
        requests.post(webhook_url, json={"content": content}, timeout=10)
    except Exception as e:
        print(f"[automation_logger] Discord通知に失敗しました: {e}")


def log_run(project_name, status, message="", duration_sec=0.0,
            notion_api_key=None, notion_db_id=None,
            discord_webhook_url=None, discord_alert_enabled=None):
    """自動化実行ログをNotionへ1行追記する。失敗しても例外を投げない(呼び出し元の処理を止めないため)。

    引数を省略した場合は環境変数から読む:
      NOTION_API_KEY, NOTION_LOG_DB_ID, DISCORD_ALERT_WEBHOOK_URL, DISCORD_ALERT_ENABLED
    """
    api_key = notion_api_key or _env("NOTION_API_KEY")
    db_id = notion_db_id or _env("NOTION_LOG_DB_ID")
    webhook_url = discord_webhook_url or _env("DISCORD_ALERT_WEBHOOK_URL")
    if discord_alert_enabled is None:
        discord_alert_enabled = _env("DISCORD_ALERT_ENABLED", "false").lower() == "true"

    if status not in ("success", "error"):
        status = "error" if status else "success"

    trimmed_message = str(message)[:_MAX_MESSAGE_LEN]
    now_jst = datetime.now(JST)

    if api_key and db_id:
        try:
            payload = {
                "parent": {"database_id": db_id},
                "properties": {
                    "プロジェクト名": {"title": [{"text": {"content": project_name}}]},
                    "実行日時": {"date": {"start": now_jst.isoformat()}},
                    "ステータス": {"select": {"name": status}},
                    "詳細メッセージ": {"rich_text": [{"text": {"content": trimmed_message}}]},
                    "実行時間(秒)": {"number": round(float(duration_sec), 1)},
                },
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            }
            res = _notion_request("post", "https://api.notion.com/v1/pages", headers, json=payload)
            if res is None or res.status_code >= 300:
                detail = res.text[:200] if res is not None else "no response"
                print(f"[automation_logger] Notionログ書き込み失敗: {detail}")
        except Exception as e:
            print(f"[automation_logger] Notionログ書き込み中に例外: {e}")
    else:
        print("[automation_logger] NOTION_API_KEY/NOTION_LOG_DB_ID未設定のため、Notionログはスキップされました")

    _notify_discord_if_error(project_name, status, trimmed_message, webhook_url, discord_alert_enabled)


class _RunHandle:
    """`with automation_run(...) as run:` の run オブジェクト。
    run.set_summary(...) で成功時の詳細メッセージを差し込める。"""

    def __init__(self):
        self.summary = ""

    def set_summary(self, text):
        self.summary = text


@contextmanager
def automation_run(project_name, **log_kwargs):
    """既存スクリプトへの変更を最小化するためのコンテキストマネージャ。

    使い方:
        with automation_run("trend_collector") as run:
            ...処理...
            run.set_summary("新着5件を同期しました")

    正常終了時は status="success" で記録、例外発生時は status="error" で記録した上で
    例外をそのまま再送出する(呼び出し元の既存のエラーハンドリングは妨げない)。
    """
    handle = _RunHandle()
    start = time.time()
    try:
        yield handle
    except Exception:
        duration = time.time() - start
        log_run(project_name, "error", traceback.format_exc(), duration, **log_kwargs)
        raise
    else:
        duration = time.time() - start
        log_run(project_name, "success", handle.summary, duration, **log_kwargs)
