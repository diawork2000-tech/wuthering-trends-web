"""公式アカウントの「地の投稿」を収集する。

ad_collector が「広告として出稿されている素材」を追うのに対し、こちらは
公式アカウントが普段どおり流している投稿そのものを追う。一次情報は
YouTube より先に X・BiliBili・Weibo に出ることが多い。

    対象は official_accounts.json の collect: true だけ。
    アカウントの追加・削除はコードではなくそのファイルで行う。

経路は2種類ある。

    X / BiliBili / Weibo → RSSHub という中継サーバーを経由する。
        公開インスタンス(rsshub.app)は自動アクセスを Cloudflare で
        丸ごと拒否するため使えない。自前で立てたものの URL を
        環境変数 RSSHUB_BASE_URL に入れること。

    Reddit → 公式RSSがそのまま読めるので中継を挟まない。
        専用の User-Agent を名乗らないと 403 で弾かれる点にだけ注意。

一番の落とし穴は「HTTP 200 なのに 0 件」。
TikTok は常にこの形で返してくるため収集対象から外した
(config_intelligence.json の無効化メモを参照)。エラーで止まらないので
放置すると「正常終了・0件」が延々と続き、取り逃しに気づけない。
0件は必ず警告として表に出すこと。
"""

import os
import re
import time

import feedparser
import requests

MAX_HTTP_RETRIES = 3
RETRY_WAIT_SECONDS = 5

# Reddit は既定のUAだとデータセンターからのアクセスを 403 で弾く。
# 何者かを名乗れば通る。intelligence_collector と同じ流儀に揃えてある。
USER_AGENT = "WutheringTrendsCollector/1.0 (YouTube Content Curator)"

# 画面とNotionに出す媒体名。ここを直すと表示が全部変わる。
PLATFORM_LABELS = {
    "x": "X",
    "bilibili": "BiliBili",
    "weibo": "Weibo",
    "reddit": "Reddit",
}

LANG_LABELS = {
    "ja": "日本語",
    "en": "英語",
    "ko": "韓国語",
    "zh-CN": "中国語",
    "zh-TW": "中国語(繁体)",
}


def platform_label(platform):
    return PLATFORM_LABELS.get(platform, platform)


def lang_label(lang):
    return LANG_LABELS.get(lang, lang)


def account_label(account):
    """アカウント1件の呼び名。絞り込みの選択肢にもそのまま使う。

    数字のIDだけ出されても人間には読めないので、BiliBili と Weibo は名前を使う。
    """
    platform = account["platform"]
    if platform == "x":
        return "@" + account["id"]
    if platform == "reddit":
        return "r/" + account["id"]
    if platform in ("bilibili", "weibo"):
        return (account.get("name") or account["id"]).split("（")[0].strip()
    return account["id"]


def source_label(account):
    """「X ・ 日本語 ・ @WW_JP_Official」の形。どこから来た情報かを一目で分かるようにする。

    タブ上で媒体も言語も混ざるので、行だけ見て出所が辿れないと使い物にならない。
    """
    return f"{platform_label(account['platform'])} ・ {lang_label(account['lang'])} ・ {account_label(account)}"


def feed_url(account, rsshub_base, access_key=""):
    """アカウント1件ぶんのフィードURLを組み立てる。

    RSSHub のルートは実物のソース(lib/routes/*)で確認したもの。
    ドキュメントは版によって古いことがあるので、変更するときは
    ソース側の path を見ること。
    """
    platform = account["platform"]

    if platform == "reddit":
        # 中継を挟まない。new ではなく hot を使う。
        # new は掲示板の全書き込みが流れてくるので、1日で数百件になり
        # 公式アカウントの投稿が埋もれる。hot なら反応があったものだけに絞れる。
        # intelligence_collector 側も同じ理由で hot を使っている。
        return f"https://www.reddit.com/r/{account['id']}/hot/.rss?limit=25"

    if not rsshub_base:
        return ""

    base = rsshub_base.rstrip("/")
    if platform == "x":
        path = f"/twitter/user/{account['id']}"
    elif platform == "bilibili":
        # 投稿動画だけでなく告知文も拾いたいので動態(dynamic)を使う
        path = f"/bilibili/user/dynamic/{account['id']}"
    elif platform == "weibo":
        path = f"/weibo/user/{account['id']}"
    else:
        return ""

    url = base + path
    if access_key:
        url += f"?key={access_key}"
    return url


def _fetch(url, label, timeout=25):
    """取得して feedparser に渡す。落ちたら数回だけ待って試し直す。

    戻り値は (feed, error)。error が入っているときは feed は None。
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml,application/atom+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    last_error = ""
    for attempt in range(MAX_HTTP_RETRIES):
        try:
            res = requests.get(url, headers=headers, timeout=timeout)
        except Exception as e:
            last_error = str(e)
        else:
            if res.status_code == 200:
                return feedparser.parse(res.text), ""
            last_error = f"HTTP {res.status_code}"
            # 4xx は待っても直らない。相手の設定かこちらのURLが違う。
            if 400 <= res.status_code < 500 and res.status_code != 429:
                break
        if attempt < MAX_HTTP_RETRIES - 1:
            time.sleep(RETRY_WAIT_SECONDS * (attempt + 1))
    return None, last_error


def _first_image(entry):
    """サムネイルに使える画像を1枚拾う。無ければ空文字。"""
    for media in entry.get("media_content", []) or []:
        if media.get("url"):
            return media["url"]
    for link in entry.get("links", []) or []:
        if str(link.get("type", "")).startswith("image/") and link.get("href"):
            return link["href"]
    html = entry.get("summary", "") or entry.get("description", "") or ""
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html)
    return match.group(1) if match else ""


def _clean_title(entry):
    """投稿本文を1行の見出しに均す。

    X の投稿には見出しが無く、RSSHub は本文をそのまま title に入れてくる。
    改行やHTMLが混ざったままだと Notion でも画面でも読めない。
    """
    raw = entry.get("title") or entry.get("summary") or ""
    text = re.sub(r"<[^>]+>", " ", str(raw))
    text = re.sub(r"\s+", " ", text).strip()
    # Notion のタイトルは2000文字まで。余裕を見て切る。
    return text[:300] if text else "(本文なし)"


def _published_iso(entry):
    """投稿日時を ISO8601（UTC）で返す。Notion の日付列にそのまま入る形。

    表示用に整形するのは画面側の仕事。ここで「○月○日」にしてしまうと
    並べ替えができなくなる。
    """
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return ""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", parsed)
    except Exception:
        return ""


def collect_account(account, rsshub_base, access_key, max_items, translator=None):
    """1アカウントぶん取る。戻り値は (投稿リスト, 状態)。

    状態は "ok" / "empty" / エラー内容。呼び出し側で集計して表に出す。

    translator は日本語へ訳す関数。中国語・韓国語のまま並べても読めないので、
    訳した文を見出しにし、原文は別に残す。渡さなければ翻訳しない。
    """
    url = feed_url(account, rsshub_base, access_key)
    if not url:
        return [], "RSSHubのURLが未設定"

    feed, error = _fetch(url, source_label(account))
    if error:
        return [], error
    if not feed or not feed.entries:
        # ここが一番大事。取れたのに0件は「静かな失敗」なので必ず返す。
        return [], "empty"

    posts = []
    for entry in feed.entries[:max_items]:
        link = entry.get("link", "")
        if not link or not str(link).startswith("http"):
            continue
        original = _clean_title(entry)
        title = original
        if translator:
            try:
                title = translator(original) or original
            except Exception:
                # 翻訳が落ちても収集は続ける。原文のままでも情報は伝わる。
                title = original
        posts.append({
            "title": title,
            # 訳した文と原文が同じなら、わざわざ原文を持つ意味がない
            "original_title": original if original != title else "",
            "url": link,
            "channel": source_label(account),
            "thumbnail": _first_image(entry),
            "view_count": 0,
            "like_count": 0,
            "platform": platform_label(account["platform"]),
            "lang": lang_label(account["lang"]),
            "account": account_label(account),
            "account_url": account.get("url", ""),
            "posted_at": _published_iso(entry),
        })
    return posts, "ok"


def load_accounts(path=None):
    """official_accounts.json から収集対象だけを読む。"""
    import json

    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "official_accounts.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [a for a in data.get("accounts", []) if a.get("collect")]


def describe_targets(accounts=None):
    """収集対象のアカウント一覧を1行ずつの文字列で返す。

    どのアカウントを見に行っているのかは、ログを読むだけで分かる必要がある。
    設定ファイルを開かないと確認できない状態にしてはいけない。
    """
    accounts = accounts if accounts is not None else load_accounts()
    return [source_label(a) for a in accounts]


def collect_sns_posts(sns_config, accounts=None, translator=None):
    """公式SNSの投稿をまとめて取る。戻り値は (投稿リスト, 集計)。"""
    rsshub_base = os.getenv("RSSHUB_BASE_URL", "").strip()
    access_key = os.getenv("RSSHUB_ACCESS_KEY", "").strip()
    max_items = int(sns_config.get("max_items_per_account", 20))
    interval = float(sns_config.get("interval_seconds", 1.0))

    accounts = accounts if accounts is not None else load_accounts()

    stats = {
        "accounts": len(accounts),
        "posts": 0,
        "empty_accounts": [],
        "failed_accounts": [],
        "skipped_no_rsshub": 0,
    }
    all_posts = []

    for account in accounts:
        label = source_label(account)
        if account["platform"] != "reddit" and not rsshub_base:
            # RSSHub がまだ無い間も Reddit だけは動く。全部止める必要はない。
            stats["skipped_no_rsshub"] += 1
            continue

        posts, state = collect_account(account, rsshub_base, access_key, max_items)
        if state == "ok":
            all_posts.extend(posts)
        elif state == "empty":
            stats["empty_accounts"].append(label)
        else:
            stats["failed_accounts"].append(f"{label}（{state}）")
        time.sleep(interval)

    stats["posts"] = len(all_posts)
    return all_posts, stats
