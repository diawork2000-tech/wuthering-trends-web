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


MAX_HTTP_RETRIES = 4


def _open_with_backoff(req, timeout, label):
    """429と5xxは待って取り直す。

    まとめて引くと相手に絞られる。ここで諦めると、収集そのものは成功した
    のに中身だけ空という一番たちの悪い結果になるので、必ず待って粘る。
    """
    wait = 5
    for attempt in range(MAX_HTTP_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == MAX_HTTP_RETRIES - 1:
                raise
            retry_after = e.headers.get("Retry-After") if e.headers else None
            try:
                delay = max(float(retry_after), wait)
            except (TypeError, ValueError):
                delay = wait
            print(f"    [Ads] {label} が {e.code} を返しました。{delay:.0f}秒待って取り直します"
                  f" ({attempt + 1}/{MAX_HTTP_RETRIES})")
            time.sleep(delay)
            wait *= 2
    raise urllib.error.URLError(f"{label}: 再試行の上限に達しました")


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
    return json.loads(_open_with_backoff(req, timeout, "広告一覧"))


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


def discover_advertisers(domains, known=None, probe_pages=3):
    """広告を出している広告主IDを、遷移先ドメインから洗い出す。

    鳴潮の広告は本体の広告主アカウントだけでなく、代理店とみられる複数の
    アカウントからも出ている。IDを設定に直書きすると、代理店が増えた日に
    黙って取りこぼすので、毎回引き直す。

    一度見つけたIDは控えに残して使い続ける。ある回の応答にたまたま
    出てこなかっただけで対象から外れるのを防ぐため。

    浅くしか見ないのは、深く掘って出てくるのが代理店ばかりで、どうせ
    select_advertisers() で捨てるから。無駄な往復はレート制限を早める。
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


def select_advertisers(found, patterns):
    """本家の広告主だけに絞る。

    同じ遷移先に対して、代理店とみられる別会社も広告を出している。中身は
    個人配信者の動画を回しているもので、本家が作った素材ではない。

    IDを直書きせず名前で見るのは、本家が別法人でアカウントを増やしたときに
    黙って取りこぼさないため。patterns が空なら全部通す。
    """
    if not patterns:
        return dict(found), {}
    lowered = [p.lower() for p in patterns]
    kept, skipped = {}, {}
    for advertiser_id, name in found.items():
        text = (name or "").lower()
        if any(p in text for p in lowered):
            kept[advertiser_id] = name
        else:
            skipped[advertiser_id] = name
    return kept, skipped


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


def _fetch(url, timeout=25, label="プレビュー"):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Referer": "https://adstransparency.google.com/"},
    )
    return _open_with_backoff(req, timeout, label)


def resolve_video_id(preview_url, attempts=2):
    """プレビューから動画IDを取り出す。戻り値は (動画ID, 取得できたか)。

    プレビューは毎回組み立て直されるらしく、同じ広告でも動画IDが入って
    こない回がある。実測で1398件中361件が1回目に取りこぼしていた。
    取れなかったものを「動画ではない広告」と決めつけないための再試行。

    通信自体に失敗した回は「空振り」に数えない。レート制限に当たった日に
    全件が空振り扱いになり、数回で「動画ではない広告」として確定して
    しまうため。中身を見た上で無かった場合だけ空振りとする。
    """
    fetched = False
    for attempt in range(attempts):
        try:
            body = _fetch(preview_url)
            fetched = True
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
            body = ""
        video_id = extract_youtube_id(body)
        if video_id:
            return video_id, True
        if attempt + 1 < attempts:
            time.sleep(0.5)
    return "", fetched


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
        return {"title": "", "channel": "", "channel_url": ""}
    return {
        "title": data.get("title") or "",
        "channel": data.get("author_name") or "",
        # 名前は locale ごとに違い、変更もされうる。誰のチャンネルかの判定は
        # ハンドルを含む URL で行う。
        "channel_url": data.get("author_url") or "",
    }


def channel_handle(channel_url):
    """チャンネルURLから @ハンドルを取り出す。小文字で返す。"""
    if not channel_url:
        return ""
    return channel_url.rstrip("/").rsplit("/", 1)[-1].lower()


def is_official_channel(channel_url, official_handles):
    """本家が持つチャンネルの動画かどうか。

    本家の広告アカウントは、自社が作った素材だけでなく、個人配信者の動画も
    そのまま広告として大量に回している。実測では742本のうち382本が配信者の
    動画で、チャンネル数は117に及んだ。広告主単位の絞り込みでは落とせない。

    official_handles が空なら全部通す。
    """
    if not official_handles:
        return True
    handle = channel_handle(channel_url).lstrip("@")
    if not handle:
        return False
    # 設定側は @ 付きで書く想定だが、無くても通るようにしておく
    return handle in {h.lstrip("@").lower() for h in official_handles}


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
        video_id, fetched = resolve_video_id(info["preview_url"])
        if not video_id:
            previous = cache_entries.get(info["creative_id"]) or {}
            misses = previous.get("misses", 0)
            return info["creative_id"], {
                "video_id": "",
                "title": "",
                "channel": "",
                # 中身を見た上で無かったときだけ数える
                "misses": misses + 1 if fetched else misses,
            }
        meta = fetch_video_meta(video_id)
        return info["creative_id"], {
            "video_id": video_id,
            "title": meta["title"],
            "channel": meta["channel"],
            "channel_url": meta["channel_url"],
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


def _refresh_missing_meta(creatives, cache_entries, workers=6):
    """チャンネルURLを持たない古い控えを埋め直す。

    チャンネルURLは後から足した項目なので、それ以前に控えた分には入っていない。
    無いものを「本家ではない」と扱うと既存分が丸ごと落ちるため、YouTube側にだけ
    問い合わせて補う。透明性センターは叩かないのでレート制限には影響しない。
    """
    todo = [
        c["creative_id"] for c in creatives
        if (cache_entries.get(c["creative_id"]) or {}).get("video_id")
        and not (cache_entries.get(c["creative_id"]) or {}).get("channel_url")
    ]
    if not todo:
        return 0

    print(f"  [Ads] チャンネル情報が未取得の {len(todo)} 件を補います...")

    def one(creative_id):
        entry = cache_entries[creative_id]
        meta = fetch_video_meta(entry["video_id"])
        return creative_id, meta

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for creative_id, meta in pool.map(one, todo):
            if not meta["channel_url"]:
                continue  # 取れなかった回は据え置く。次回また試す
            entry = cache_entries[creative_id]
            entry["channel_url"] = meta["channel_url"]
            entry["channel"] = meta["channel"] or entry.get("channel", "")
            entry["title"] = entry.get("title") or meta["title"]
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
    probe_pages = ad_config.get("advertiser_probe_pages", 3)

    cache = load_cache()
    entries = cache["creatives"]

    found = discover_advertisers(domains, known=cache.get("advertisers"), probe_pages=probe_pages)
    cache["advertisers"] = found
    advertisers, skipped = select_advertisers(found, ad_config.get("advertiser_name_patterns", []))
    print(f"  [Ads] 広告主 {len(advertisers)} 件を対象にします")
    # 誰を外したかは必ず残す。黙って外すと、本家が法人を増やした日に
    # 収集が痩せた理由が分からなくなる。
    for advertiser_id, name in skipped.items():
        print(f"  [Ads] 対象外（本家以外）: {name or advertiser_id}")

    stats = {
        "advertisers": len(advertisers),
        "skipped_advertisers": len(skipped),
        "creatives": 0,
        "video_ads": 0,
        "non_video": 0,
        "other_channel": 0,
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
    _refresh_missing_meta(list(parsed.values()), entries, workers)
    save_cache(cache)

    official = ad_config.get("official_channels", [])

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

        # 本家の広告アカウントは配信者の動画もそのまま広告に使う。
        # 欲しいのは本家が作った素材なので、チャンネルで線を引く。
        if not is_official_channel(entry.get("channel_url", ""), official):
            stats["other_channel"] += 1
            continue
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
