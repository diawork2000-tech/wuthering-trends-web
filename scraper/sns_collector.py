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

import html as html_lib
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


def _error_reason(html):
    """RSSHub のエラー画面から、失敗した理由だけを取り出す。

    画面には見た目を整えるためのCSSが大量に入っており、素直にタグを外すと
    そちらが先に出てきて肝心の理由が読めない。実際それで一度、CSSの断片が
    ログに並んだ。理由は「Error Message:」の後ろに書かれている。
    """
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    match = re.search(r"Error Message:\s*(.+?)(?:\s+Route:|$)", text)
    return (match.group(1) if match else text)[:180]


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
            # 状態番号だけでは何が起きたのか分からない。RSSHub は失敗の理由を
            # 本文に書いて返すので、そこを短く持ち帰る。これが無いと、
            # 毎回サーバーのログを人が見に行くことになる。
            last_error = f"HTTP {res.status_code}"
            reason = _error_reason(res.text)
            if reason:
                last_error += f": {reason}"
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
            return _clean_url(media["url"])
    for link in entry.get("links", []) or []:
        if str(link.get("type", "")).startswith("image/") and link.get("href"):
            return _clean_url(link["href"])
    html = entry.get("summary", "") or entry.get("description", "") or ""
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html)
    return _clean_url(match.group(1)) if match else ""


def _clean_url(url):
    """本文から取り出したURLを、そのまま開ける形に戻す。

    本文はHTMLなので & が &amp; と書かれている。戻さずに使うと
    「?format=jpg&amp;name=orig」となり、画像が404で出てこない。
    実際にこれで186件の画像が表示できていなかった。
    """
    return html_lib.unescape((url or "").strip())


def _video_source(entry):
    """動画付きの投稿から、動画のURLと表紙画像を取り出す。戻り値は (動画URL, 表紙)。

    RSSHub は本文に <video src='….mp4' poster='….jpg'> の形で入れてくる
    （lib/routes/twitter/utils.ts）。src は用意されている中で最も画質の
    高いものが選ばれている。

    動画そのものは Twitter の配信元に置かれたままなので、こちらの通信量は
    増えない。再生できなかった場合も表紙画像が残るだけで、表示は崩れない。
    """
    html = entry.get("summary", "") or entry.get("description", "") or ""
    tag = re.search(r"<video[^>]*>", html)
    if not tag:
        return "", ""
    src = re.search(r"src=[\"']([^\"']+)[\"']", tag.group(0))
    poster = re.search(r"poster=[\"']([^\"']+)[\"']", tag.group(0))
    url = _clean_url(src.group(1)) if src else ""
    if not url.startswith("https://"):
        return "", ""
    return url, (_clean_url(poster.group(1)) if poster else "")


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


# 翻訳先が落ちているとき、翻訳結果としてエラー画面の文面が返ってくる。
# 実際に「Error 500 (Server Error)!!1500.That’s an error」が7件、
# 訳文としてそのまま登録されていた。訳せなかったものとして扱う。
ERROR_PAGE_SIGNS = re.compile(
    r"(Error \d{3}|Server Error|That[’']s an error|Bad Gateway|Too Many Requests|<!DOCTYPE)",
    re.IGNORECASE,
)


def _translate_once(translator, original):
    """訳して、まともな結果のときだけ返す。駄目なら空文字。"""
    try:
        title = translator(original)
    except Exception:
        return ""
    if not title or title == original:
        return ""
    if ERROR_PAGE_SIGNS.search(title):
        return ""
    return title


def translate_posts(posts, translator, langs=None, interval=0.4):
    """投稿の見出しを日本語に訳す。戻り値は (訳した件数, 失敗件数)。

    毎時の巡回で取り直した投稿を丸ごと訳すと、1回あたり百件近く翻訳を
    呼ぶことになり、まとめて弾かれる。実際それで一度も訳せていなかった。
    呼び出し側で「まだ登録していない投稿」だけに絞ってから渡すこと。

    翻訳できなかったことは必ず数えて返す。黙って原文を返すと、
    訳されていないことに誰も気づけない。
    """
    langs = langs or ["中国語", "韓国語"]
    translated = failed = 0
    for post in posts:
        if post.get("lang") not in langs:
            continue
        original = post["title"]
        title = _translate_once(translator, original)
        if not title:
            # 一度だけ間を置いて試し直す。翻訳側が混んでいるだけのことがある。
            time.sleep(2)
            title = _translate_once(translator, original)
        if not title:
            failed += 1
            continue
        post["title"] = title
        post["original_title"] = original
        translated += 1
        time.sleep(interval)
    return translated, failed


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
        video_url, poster = _video_source(entry)
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
            # 動画付きなら表紙を使う。本文中の1枚目より投稿の中身に近い。
            "thumbnail": poster or _first_image(entry),
            "video_url": video_url,
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
        # 実際に投稿が取れたアカウント数。対象数と混ぜて報告してはいけない。
        # 「14アカウントから20件」と書くと、13件が見送られていても
        # 全部から取れているように読めてしまう。
        "collected_accounts": 0,
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
            stats["collected_accounts"] += 1
        elif state == "empty":
            stats["empty_accounts"].append(label)
        else:
            stats["failed_accounts"].append(f"{label}（{state}）")
        time.sleep(interval)

    stats["posts"] = len(all_posts)
    return all_posts, stats
