"""出稿中の広告クリエイティブを集める。

Googleは「広告の透明性について」(adstransparency.google.com) で、実際に配信
されている広告を誰でも閲覧できるように公開している。ただし公式APIは無い。
そこで画面自身が使っている内部RPCを、同じ形で呼んでいる。

    公開データが相手なので鍵も認証も要らない代わりに、Google側の都合で
    いつでも壊れうる。壊れたときに本体の収集まで道連れにしないこと。
    ここから送出する例外は呼び出し側で握り潰す前提で書いてある。

取れるもの:
  - 鳴潮の広告として実際に配信された動画（多くは公式PVだが、公式チャンネルに
    無い広告専用の尺違いや、ファン制作MADの起用も混ざる）
  - その広告がいつからいつまで表示されていたか

取れないもの:
  - 表示回数・費用（Googleが政治広告以外では公開していない）
  - Meta / TikTok / X の広告（いずれも日本の一般広告を無料で引ける経路が無い）
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

RPC_URL = "https://adstransparency.google.com/anji/_/rpc/SearchService/SearchCreatives?authuser="
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
REGION_JP = 2392

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ad_creative_cache.json")

# 広告の中身の種類。透明性センターの内部表現をそのまま使っている。
FORMAT_TEXT = 2
FORMAT_IMAGE = 1
FORMAT_VIDEO = 3

# 動画広告のプレビューには、YouTubeのサムネイルURLが必ず埋まっている。
# 動画IDはそこから拾うのが一番確実だった（プレビュー本体は難読化されている）。
_YT_THUMB = re.compile(r"ytimg\.com/vi/([A-Za-z0-9_-]{11})")


def _post(payload, timeout=30):
    body = urllib.parse.urlencode({"f.req": json.dumps(payload, ensure_ascii=False)}).encode()
    req = urllib.request.Request(
        RPC_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
            "Referer": "https://adstransparency.google.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def search_creatives(domain, region_code=REGION_JP, max_pages=5, interval=0.4):
    """1つのドメイン宛の広告を、ページ送りしながら集める。

    ドメイン指定なのは、鳴潮の広告主アカウントが複数あり、名前検索では
    引けなかったため。透明性センター自身もドメインで束ねて表示している。
    """
    creatives, token = [], None
    for _ in range(max_pages):
        payload = {
            "2": 40,
            "3": {
                "8": [region_code],
                "12": {"1": domain, "2": True},
            },
            "7": {"1": 1, "2": 0, "3": region_code},
        }
        if token:
            payload["4"] = token
        data = _post(payload)
        items = data.get("1", [])
        creatives.extend(items)
        token = data.get("2")
        if not token or not items:
            break
        time.sleep(interval)
    return creatives


def parse_creative(creative):
    """RPCの生データを、意味の分かる形に直す。

    数字キーはGoogleの内部表現そのままなので、ここで意味に翻訳しておく。
    形が変わったら例外ではなく欠損として返し、1件の異常で全体を止めない。
    """
    content = creative.get("3") or {}
    return {
        "advertiser_id": creative.get("1") or "",
        "creative_id": creative.get("2") or "",
        "format": creative.get("4"),
        "advertiser": creative.get("12") or "",
        "preview_url": ((content.get("1") or {}).get("4")) or "",
        "first_shown": _epoch_to_date((creative.get("6") or {}).get("1")),
        "last_shown": _epoch_to_date((creative.get("7") or {}).get("1")),
    }


def _epoch_to_date(value):
    """秒数を YYYY-MM-DD にする。読めない値は空文字にして落とさない。"""
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    try:
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


def format_period(first_shown, last_shown):
    """出稿期間の表示文字列。片方しか無くても読める形にする。"""
    if first_shown and last_shown:
        return f"{first_shown} 〜 {last_shown}"
    return first_shown or last_shown or ""


def extract_youtube_id(text):
    """広告プレビューの中身からYouTubeの動画IDを取り出す。"""
    if not text:
        return ""
    match = _YT_THUMB.search(text)
    return match.group(1) if match else ""


def _fetch(url, timeout=25):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Referer": "https://adstransparency.google.com/"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", "replace")


def fetch_video_meta(video_id):
    """動画のタイトルとチャンネル名を取る。

    oEmbedを使うのは、YouTube Data APIの1日あたりの割り当てを
    広告の名前引きで削りたくないから。鍵も要らない。
    """
    url = (
        "https://www.youtube.com/oembed?url="
        + urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}", safe="")
        + "&format=json"
    )
    try:
        data = json.loads(_fetch(url, timeout=20))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError):
        return {"title": "", "channel": ""}
    return {"title": data.get("title") or "", "channel": data.get("author_name") or ""}


def load_cache(path=CACHE_PATH):
    """広告ID→動画情報の対応表。毎回プレビューを取り直さないための控え。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache, path=CACHE_PATH):
    """書き込み中に落ちても前回分を失わないよう、別名に書いてから差し替える。"""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except OSError as e:
        print(f"  [Warning] 広告キャッシュの保存に失敗しました: {e}")


def collect_ad_videos(ad_config, exclude_checker=None):
    """設定されたドメインの広告から、動画広告だけを取り出して返す。

    戻り値は trend_collector が Notion に渡す形と同じ。混ぜても壊れない。
    """
    if not ad_config.get("enabled", True):
        print("  [Ads] 広告収集は設定で無効化されています。")
        return [], {}

    domains = ad_config.get("domains", [])
    region = ad_config.get("region_code", REGION_JP)
    max_pages = ad_config.get("max_pages_per_domain", 5)
    interval = ad_config.get("request_interval_sec", 0.4)

    cache = load_cache()
    stats = {
        "creatives": 0,
        "video_ads": 0,
        "non_video": 0,
        "excluded": 0,
        "cache_hits": 0,
        "failed_domains": [],
    }

    seen_ids = set()
    videos = []

    for domain in domains:
        try:
            creatives = search_creatives(domain, region, max_pages, interval)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as e:
            print(f"  [Ads] {domain} の取得に失敗しました: {e}")
            stats["failed_domains"].append(domain)
            continue

        print(f"  [Ads] {domain}: 広告 {len(creatives)} 件")
        stats["creatives"] += len(creatives)

        for raw in creatives:
            info = parse_creative(raw)
            key = info["creative_id"]
            if not key:
                continue

            cached = cache.get(key)
            if cached is not None:
                stats["cache_hits"] += 1
                video_id = cached.get("video_id", "")
                title = cached.get("title", "")
                channel = cached.get("channel", "")
            else:
                video_id, title, channel = "", "", ""
                if info["preview_url"]:
                    try:
                        video_id = extract_youtube_id(_fetch(info["preview_url"]))
                    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
                        print(f"    [Ads] プレビュー取得失敗 {key}: {e}")
                        continue
                    if video_id:
                        meta = fetch_video_meta(video_id)
                        title, channel = meta["title"], meta["channel"]
                    time.sleep(interval)
                cache[key] = {"video_id": video_id, "title": title, "channel": channel}

            if not video_id:
                stats["non_video"] += 1
                continue
            if video_id in seen_ids:
                continue
            seen_ids.add(video_id)

            display_title = title or f"広告クリエイティブ {key}"
            if exclude_checker and exclude_checker(display_title):
                stats["excluded"] += 1
                continue

            stats["video_ads"] += 1
            videos.append({
                "title": display_title,
                "original_title": display_title,
                "channel": channel or info["advertiser"] or "不明",
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "video_type": "広告",
                "ad_period": format_period(info["first_shown"], info["last_shown"]),
                "ad_advertiser": info["advertiser"],
            })

    save_cache(cache)
    return videos, stats
