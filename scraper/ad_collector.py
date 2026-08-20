"""出稿中の広告クリエイティブを集める。

Googleは「広告の透明性について」(adstransparency.google.com) で、実際に配信
されている広告を誰でも閲覧できるように公開している。ただし公式APIは無い。
そこで画面自身が使っている内部RPCを、同じ形で呼んでいる。

    公開データが相手なので鍵も認証も要らない代わりに、Google側の都合で
    いつでも壊れうる。壊れたときに本体の収集まで道連れにしないこと。
    ここから送出する例外は呼び出し側で握り潰す前提で書いてある。

ここで本当に欲しいのは、公式チャンネルに上がっていない広告専用の映像。
鳴潮の広告素材の多くは限定公開のチャンネル (UCAMjmQpxCVKhYdRCv4tYajA) に
置かれており、検索にもRSSにも一切出てこない。透明性センターを通す以外に
見つける方法が無い。

    絞り込みの2点を間違えると、この本命がまるごと落ちる。
      - ドメインではなく広告主IDで引くこと（ドメイン指定は取りこぼす）
      - 地域を指定しないこと（日本指定だと海外向けの素材が消える）
    実測では、ドメイン+日本指定=45件に対し、広告主ID+地域なし=742件だった。
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

RPC_URL = "https://adstransparency.google.com/anji/_/rpc/SearchService/SearchCreatives?authuser="
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
REGION_JP = 2392

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ad_creative_cache.json")

# 広告の中身の種類。透明性センターの内部表現をそのまま使っている。
FORMAT_IMAGE = 1
FORMAT_TEXT = 2
FORMAT_VIDEO = 3

# 動画広告のプレビューには、YouTubeのサムネイルURLが埋まっている。
# 動画IDはそこから拾うのが一番確実だった（プレビュー本体は難読化されている）。
_YT_THUMB = re.compile(r"ytimg\.com/vi/([A-Za-z0-9_-]{11})")

# 同じ広告主がパニシング:グレイレイヴンの広告も出している。素材のファイル名が
# 「PGR-」で始まり、チャンネル名でも見分けられる。
_PGR_TITLE = re.compile(r"^PGR[-_]", re.IGNORECASE)
_PGR_CHANNELS = {"PGR", "パニシング:グレイレイヴン", "Punishing: Gray Raven"}


def _post(payload, timeout=40):
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


def search_creatives(domain=None, advertiser=None, region=None, max_pages=60, interval=0.2):
    """条件に合う広告を、ページ送りしながら最後まで集める。

    region に None を渡すと地域を絞らない。海外向けの素材こそ公式チャンネルに
    無いものが多いので、既定は絞らない側にしてある。
    """
    creatives, token = [], None
    for _ in range(max_pages):
        filters = {"12": {"1": domain or "", "2": True}}
        if region is not None:
            filters["8"] = [region]
        if advertiser:
            filters["13"] = {"1": [advertiser]}
        payload = {"2": 40, "3": filters, "7": {"1": 1, "2": 0, "3": REGION_JP}}
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


def discover_advertisers(domains, known=None, probe_pages=20):
    """広告を出している広告主IDを、遷移先ドメインから洗い出す。

    鳴潮の広告は本体の広告主アカウントだけでなく、代理店とみられる複数の
    アカウントからも出ている。IDを設定に直書きすると、代理店が増えた日に
    黙って取りこぼすので、毎回引き直す。

    一度見つけたIDは控えに残して使い続ける。ある回の応答にたまたま
    出てこなかっただけで対象から外れるのを防ぐため。
    """
    found = dict(known or {})
    for domain in domains:
        try:
            creatives = search_creatives(domain=domain, max_pages=probe_pages)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as e:
            print(f"  [Ads] 広告主の洗い出しに失敗 {domain}: {e}")
            continue
        for creative in creatives:
            advertiser_id = creative.get("1")
            if advertiser_id:
                found[advertiser_id] = creative.get("12") or found.get(advertiser_id, "")
    return found


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


def is_other_game(title, channel):
    """同じ広告主が出している別タイトル（パニシング）の広告かどうか。"""
    if channel in _PGR_CHANNELS:
        return True
    return bool(_PGR_TITLE.match(title or ""))


def _fetch(url, timeout=25):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Referer": "https://adstransparency.google.com/"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", "replace")


def resolve_video_id(preview_url, attempts=2):
    """プレビューから動画IDを取り出す。1度だけ取り直す。

    プレビューは毎回組み立て直されるらしく、同じ広告でも動画IDが入って
    こない回がある。実測で1398件中361件が1回目に取りこぼしていた。
    取れなかったものを「動画ではない広告」と決めつけないための再試行。
    """
    for attempt in range(attempts):
        try:
            video_id = extract_youtube_id(_fetch(preview_url))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
            video_id = ""
        if video_id:
            return video_id
        if attempt + 1 < attempts:
            time.sleep(0.5)
    return ""


def fetch_video_meta(video_id):
    """動画のタイトルとチャンネル名を取る。

    oEmbedを使うのは、YouTube Data APIの1日あたりの割り当てを削りたくない
    から。広告素材は限定公開が多く、Data APIでは引けない点でも都合が良い。
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
    except (OSError, ValueError):
        return {"creatives": {}, "advertisers": {}}
    if not isinstance(data, dict):
        return {"creatives": {}, "advertisers": {}}
    # 旧形式（広告IDが直接並んでいる）からの持ち上げ
    if "creatives" not in data:
        return {"creatives": data, "advertisers": {}}
    data.setdefault("creatives", {})
    data.setdefault("advertisers", {})
    return data


def save_cache(cache, path=CACHE_PATH):
    """書き込み中に落ちても前回分を失わないよう、別名に書いてから差し替える。"""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except OSError as e:
        print(f"  [Warning] 広告キャッシュの保存に失敗しました: {e}")


MAX_RESOLVE_MISSES = 3


def _needs_resolving(info, cache_entries):
    """この広告の中身を（もう一度）調べるべきか。

    プレビューを持たない広告は画像やテキストなので、確定して二度と触らない。
    プレビューはあるのに動画IDが取れなかったものは、取りこぼしと仕様変更の
    区別がつかない。ここで確定させると、一度の通信の綾で「動画ではない広告」
    として永久に埋もれるため、回数を区切って引き直す。
    """
    if not info["preview_url"]:
        return False
    entry = cache_entries.get(info["creative_id"])
    if entry is None:
        return True
    if entry.get("video_id"):
        return False
    return entry.get("misses", 0) < MAX_RESOLVE_MISSES


def _resolve_missing(creatives, cache_entries, workers=6):
    """中身が未確定の広告だけ、まとめて調べる。

    初回は1400件近くを引くことになるので直列だと現実的な時間で終わらない。
    相手は公開ページとはいえ他人様のサーバーなので、同時数は控えめにする。
    """
    todo = [c for c in creatives if _needs_resolving(c, cache_entries)]
    if not todo:
        return 0

    print(f"  [Ads] 中身が未確定の広告 {len(todo)} 件を確認します...")

    def one(info):
        video_id = resolve_video_id(info["preview_url"])
        if not video_id:
            previous = cache_entries.get(info["creative_id"]) or {}
            return info["creative_id"], {
                "video_id": "",
                "title": "",
                "channel": "",
                "misses": previous.get("misses", 0) + 1,
            }
        meta = fetch_video_meta(video_id)
        return info["creative_id"], {
            "video_id": video_id,
            "title": meta["title"],
            "channel": meta["channel"],
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for creative_id, entry in pool.map(one, todo):
            cache_entries[creative_id] = entry

    # プレビューを持たない広告（画像・テキスト）は確定させ、次回以降調べ直さない
    for info in creatives:
        if not info["preview_url"]:
            cache_entries.setdefault(
                info["creative_id"], {"video_id": "", "title": "", "channel": ""}
            )
    return len(todo)


def collect_ad_videos(ad_config, exclude_checker=None):
    """配信された広告から、動画広告だけを取り出して返す。

    戻り値は trend_collector が Notion に渡す形と同じ。混ぜても壊れない。
    """
    if not ad_config.get("enabled", True):
        print("  [Ads] 広告収集は設定で無効化されています。")
        return [], {}

    domains = ad_config.get("domains", [])
    region = ad_config.get("region_code")  # None なら地域を絞らない
    max_pages = ad_config.get("max_pages_per_advertiser", 60)
    interval = ad_config.get("request_interval_sec", 0.2)
    workers = ad_config.get("resolve_workers", 6)
    probe_pages = ad_config.get("advertiser_probe_pages", 20)

    cache = load_cache()
    entries = cache["creatives"]

    advertisers = discover_advertisers(domains, known=cache.get("advertisers"), probe_pages=probe_pages)
    cache["advertisers"] = advertisers
    print(f"  [Ads] 広告主 {len(advertisers)} 件を対象にします")

    stats = {
        "advertisers": len(advertisers),
        "creatives": 0,
        "video_ads": 0,
        "non_video": 0,
        "other_game": 0,
        "excluded": 0,
        "newly_resolved": 0,
        "failed_advertisers": [],
    }

    parsed = {}
    for advertiser_id in advertisers:
        try:
            raw = search_creatives(
                advertiser=advertiser_id, region=region,
                max_pages=max_pages, interval=interval,
            )
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as e:
            print(f"  [Ads] {advertiser_id} の取得に失敗しました: {e}")
            stats["failed_advertisers"].append(advertiser_id)
            continue
        print(f"  [Ads] {advertisers[advertiser_id] or advertiser_id}: 広告 {len(raw)} 件")
        for item in raw:
            info = parse_creative(item)
            if info["creative_id"]:
                parsed[info["creative_id"]] = info

    stats["creatives"] = len(parsed)
    stats["newly_resolved"] = _resolve_missing(list(parsed.values()), entries, workers)
    save_cache(cache)

    seen_ids = set()
    videos = []
    for info in parsed.values():
        entry = entries.get(info["creative_id"]) or {}
        video_id = entry.get("video_id", "")
        if not video_id:
            stats["non_video"] += 1
            continue
        if video_id in seen_ids:
            continue
        seen_ids.add(video_id)

        title = entry.get("title") or f"広告クリエイティブ {info['creative_id']}"
        channel = entry.get("channel") or ""

        if is_other_game(title, channel):
            stats["other_game"] += 1
            continue
        if exclude_checker and exclude_checker(title):
            stats["excluded"] += 1
            continue

        stats["video_ads"] += 1
        videos.append({
            "title": title,
            "original_title": title,
            "channel": channel or info["advertiser"] or "不明",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "video_type": "広告",
            "ad_period": format_period(info["first_shown"], info["last_shown"]),
            "ad_advertiser": info["advertiser"],
        })

    return videos, stats
