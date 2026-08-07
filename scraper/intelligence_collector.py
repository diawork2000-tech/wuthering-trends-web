import sys
import os
import json
import traceback
import re
import time
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

try:
    import feedparser
except ImportError:
    feedparser = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    # google-generativeai は開発終了(EOL)のため後継 SDK の google-genai へ移行済み。
    from google import genai
except ImportError:
    genai = None

from trend_collector import YouTubeKeyManager, translate_if_needed
from notion_utils import notion_request
from shared.automation_logger import log_run

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv(os.path.join(BASE_DIR, "../.env.local"))

CONFIG_FILE = os.path.join(BASE_DIR, "config_intelligence.json")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_INTELLIGENCE_DB_ID = os.getenv("NOTION_INTELLIGENCE_DB_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY") or os.getenv("YOUTUBE_API_KEYS")

LOG_PATH = os.path.join(BASE_DIR, "intelligence_logs.json")
SCHEDULE_PATH = os.path.join(BASE_DIR, "../src/data/upcoming_schedule.json")


# どのカードにも出てくる語。これを残すと「鳴潮」だけで全部が同一話題に見えてしまう。
# 「競合バズ実績」の見出しや攻略サイトの定型文（評価・おすすめ編成…）もここで落とす。
TITLE_STOPWORDS = {
    "鳴潮", "wutheringwaves", "wuthering", "waves", "wuwa", "meicho",
    "競合", "バズ", "実績", "動画", "解説", "攻略", "最新", "情報", "まとめ",
    "shorts", "short", "ショート", "youtube", "gaming",
    "評価", "おすすめ", "編成", "パーティ", "武器", "音骸", "方法", "進め方",
    "gamewith", "game8", "インサイド", "ニュース", "yahoo",
}


def _title_tokens(text):
    """タイトルから意味のある語だけを取り出す。同一話題の判定に使う。

    ハッシュタグ（#wuwacreator 等）は話題ではなく投稿者の習慣なので、
    残すと無関係な動画同士が同一視されてしまう。先に丸ごと落とす。
    """
    t = re.sub(r"#\S+", " ", str(text).lower())
    t = re.sub(r"[【】\[\]（）()｜|/,.!?・:：\-—＆&\"']", " ", t)
    tokens = set(re.findall(r'[a-z0-9]{3,}|[ァ-ヴー]{2,}|[一-龥]{2,}', t))
    return {w for w in tokens if w not in TITLE_STOPWORDS}


def cluster_similar_items(items, threshold=0.34):
    """同じ話題を扱うアイテムをまとめる。

    「同じ話題が別ソースから5件」で一覧が埋まるのを防ぐのが第一の目的だが、
    複数の情報源が同時に取り上げている = 話題性が高い、という判断材料にもなるため
    まとめた件数を mention_count として残す。代表は最もスコアが高いものを選ぶ。
    """
    clusters = []  # [{"rep": item, "tokens": set, "members": [item, ...]}]
    for item in items:
        tokens = _title_tokens(item.get("title", ""))
        # 特徴語が1語しかないタイトルは、偶然の一致で無関係なものと結合されやすいため
        # 束ねの対象から外し、単独の話題として扱う。
        if len(tokens) < 2:
            clusters.append({"rep": item, "tokens": set(), "members": [item]})
            continue

        for c in clusters:
            if not c["tokens"]:
                continue
            overlap = len(tokens & c["tokens"])
            union = len(tokens | c["tokens"])
            # 割合だけだと語数の少ないタイトル同士が1語かぶるだけで一致してしまうので
            # 実数でも2語以上重なっていることを条件に加える。
            if overlap >= 2 and union and (overlap / union) >= threshold:
                c["members"].append(item)
                if item.get("score", 0) > c["rep"].get("score", 0):
                    c["rep"] = item
                    c["tokens"] = tokens
                break
        else:
            clusters.append({"rep": item, "tokens": tokens, "members": [item]})

    representatives = []
    for c in clusters:
        rep = c["rep"]
        rep["mention_count"] = len(c["members"])
        # 別ソースが同じ話題に触れているほど加点する（最大 +18）
        rep["score"] = min(100, rep.get("score", 60) + min(18, (len(c["members"]) - 1) * 6))
        representatives.append(rep)
    return representatives


def _feed_entry_iso(entry):
    """RSS エントリの公開日時を ISO8601 で返す。

    RSS の日付表記はソースによってバラバラなので、feedparser が正規化した
    published_parsed（UTC の time.struct_time）を優先して使う。
    """
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                continue
    return ""


def _hours_since(iso_str):
    """ISO8601 の日時から現在までの経過時間(時)。解釈できなければ None。"""
    if not iso_str:
        return None
    try:
        s = str(iso_str).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.5, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
    except Exception:
        return None


def score_competitor_video(view_count, like_count, published_at):
    """競合動画のスコア。絶対再生数ではなく「伸び速度」を主軸にする。

    投稿直後の1万再生と、半年かけての1万再生では価値が全く違う。
    後追いで作って間に合うかを判断したいので、時間あたりの再生数で測る。
    """
    hours = _hours_since(published_at) or 72.0
    vph = view_count / hours

    for bar, pt in ((5000, 40), (2000, 34), (1000, 28), (500, 22), (200, 16), (50, 10)):
        if vph >= bar:
            speed = pt
            break
    else:
        speed = 4

    freshness = 8 if hours <= 24 else (4 if hours <= 72 else 0)
    # 高評価率は「再生されただけ」か「刺さったか」の区別になる
    engagement = 4 if view_count > 0 and (like_count / view_count) >= 0.05 else 0

    return min(100, 50 + speed + freshness + engagement), round(vph, 1)


def score_web_item(weight, published_at):
    """Web/RSS 記事のスコア。情報源の信頼度と鮮度で決める。"""
    hours = _hours_since(published_at)
    if hours is None:
        recency = 2  # 日時不明のものを不利にしすぎない程度に
    elif hours <= 6:
        recency = 12
    elif hours <= 24:
        recency = 8
    elif hours <= 72:
        recency = 4
    else:
        recency = 0
    return min(100, int(weight) + recency)


def load_upcoming_events():
    """実装予定カレンダーを読む。スコアの直前ブースト判定に使う。"""
    try:
        with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("events", [])
    except Exception:
        return []


def schedule_boost(text, events):
    """まもなく実装/開催される要素に触れたネタを加点する。

    新キャラ実装の数日前にそのキャラの解説を出すのが最も伸びるため、
    カレンダー上で近い予定に言及しているネタを優先的に浮上させる。
    """
    if not events:
        return 0, None
    low = str(text).lower()
    best, best_name = 0, None
    today = datetime.now(timezone.utc) + timedelta(hours=9)
    for ev in events:
        name = str(ev.get("character", "")).strip()
        if len(name) < 2 or name.lower() not in low:
            continue
        try:
            start = datetime.strptime(str(ev.get("start_date")), "%Y-%m-%d")
        except Exception:
            continue
        days = (start - today.replace(tzinfo=None)).days
        if -3 <= days <= 14:
            pt = 12 if days >= 0 else 6
            if pt > best:
                best, best_name = pt, name
    return best, best_name


def minutes_since_last_run():
    """前回の収集完了からの経過分数。記録が無ければ None（＝必ず実行する）。"""
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            logs = json.load(f)
        if not logs:
            return None
        last = datetime.strptime(logs[0]["timestamp"], "%Y-%m-%d %H:%M:%S")
        now_jst = (datetime.now(timezone.utc) + timedelta(hours=9)).replace(tzinfo=None)
        return (now_jst - last).total_seconds() / 60.0
    except Exception:
        return None


def is_force_run():
    """手動の「今すぐ即時発掘」など、間隔を無視して実行すべきかどうか。"""
    if "--force" in sys.argv:
        return True
    return str(os.getenv("FORCE_RUN", "")).lower() in ("1", "true", "yes")


# 『鳴潮』の話だと判断できる手がかり。タイトル・概要・タグのどこかにあればよい。
RELEVANCE_MARKERS = (
    "鳴潮", "めいちょう", "wutheringwaves", "wuthering waves", "wuthering", "wuwa",
    "鳴潮攻略", "kurogames", "クロゲ", "漂泊者", "音骸", "共鳴者", "ソラランク",
)

# 明らかに別ゲーム・別ジャンルの話。手がかり語が紛れ込んでいても弾く。
OFF_TOPIC_MARKERS = (
    "zenless", "zenlesszonegame", "ゼンレスゾーンゼロ", "原神", "genshin",
    "スターレイル", "starrail", "崩壊", "honkai", "アズールレーン", "fgo",
    "fate/", "ブルーアーカイブ", "ウマ娘", "モンハン", "ポケモン",
)


# 鳴潮の話ではあるが、ゲーム内容の動画ネタにはならないもの。
# コスプレ写真集・イベント来場レポートなどが該当する。
NOISE_MARKERS = (
    "コスプレ", "こすぷれ", "cosplay", "レイヤー", "写真集", "グラビア",
    "漫画博覧会", "ワンダーフェスティバル", "コミケ", "コミックマーケット",
    "美女", "美脚", "水着グラビア",
)


def is_relevant(*texts):
    """『鳴潮』の話として扱ってよい素材かを判定する。

    競合チャンネルは鳴潮以外の動画も投稿しており、Googleニュースの検索結果にも
    別ゲームの記事が紛れ込む。これらを Gemini に渡すと、鳴潮の用語で
    もっともらしい嘘（実在しないキャラのビルド解説など）を書いてしまうため、
    解析に入る前にここで落とす。

    加えて、鳴潮関連ではあってもコスプレ写真集のように
    ゲーム内容の動画ネタにならないものも同時に除外する。
    """
    blob = " ".join(str(t or "") for t in texts).lower()
    if not blob.strip():
        return False
    if any(m in blob for m in OFF_TOPIC_MARKERS):
        return False
    if any(m in blob for m in NOISE_MARKERS):
        return False
    return any(m in blob for m in RELEVANCE_MARKERS)


def _build_reason(item, kw_match):
    """「なぜ今これなのか」を、手元の事実だけで組み立てる。

    Gemini が無料枠切れ等で失敗したときのフォールバックでも、
    定型文ではなく判断材料になる一文が出るようにしておく。
    """
    parts = []
    mentions = item.get("mention_count", 1)
    if mentions > 1:
        parts.append(f"{mentions}件の情報源が同時に取り上げている話題")
    if item.get("schedule_hit"):
        parts.append(f"まもなく実装・開催の「{item['schedule_hit']}」に関連")
    hours = _hours_since(item.get("published_at"))
    if hours is not None and hours <= 24:
        parts.append(f"約{int(hours)}時間前に出たばかりの新しい情報")
    if item.get("match_kw"):
        parts.append(f"競合が扱っている注目ワード「{item['match_kw']}」を含む")
    if not parts:
        parts.append(f"「{kw_match}」に関連する情報として収集")
    return " ／ ".join(parts)


def load_intelligence_config():
    if not os.path.exists(CONFIG_FILE):
        return {"target_channels": [], "target_web_sources": [], "settings": {"target_items_per_run": 15}}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_intelligence_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

class IntelligenceEngine:
    def __init__(self):
        self.config = load_intelligence_config()
        self.key_manager = YouTubeKeyManager()
        self.collected_raw_items = []
        self.competitor_raw_items = []  # ★最重要：競合チャンネル動向専用の独立収容ラック（別枠カウント）！
        self.trending_keywords = set()
        # google-genai では「モデル」はクライアント越しに名前で呼び出す方式のため、
        # 以前の GenerativeModel インスタンスの代わりに Client + モデル名の組で保持する。
        self.gemini_client = None
        self.gemini_model_name = None
        # Gemini が実際に成功したか、無料枠制限等で代替アルゴリズムに落ちたかを
        # 毎回のログに残すためのステータス。値: not_configured / no_items / success / failed
        self.gemini_topic_status = "not_configured"
        self.gemini_competitor_status = "not_configured"
        self.notion_title_prop_name = "名前"

        if GEMINI_API_KEY and genai:
            try:
                self.gemini_client = genai.Client(api_key=GEMINI_API_KEY)
                self._init_best_gemini_model()
            except Exception as e:
                print(f"  [Warning] Gemini configuration failed: {e}")
                self.gemini_client = None
        else:
            print("  [Info] Gemini API key not set. Running in high-speed algorithmic fallback mode.")

        if NOTION_API_KEY and NOTION_INTELLIGENCE_DB_ID:
            self.ensure_notion_db_schema()

    def _init_best_gemini_model(self):
        candidate_models = [
            'gemini-flash-latest',
            'gemini-3.6-flash',
            'gemini-3.5-flash',
            'gemini-2.0-flash',
            'gemini-flash-lite-latest',
            'gemini-pro-latest'
        ]
        try:
            available = [
                m.name.replace("models/", "") for m in self.gemini_client.models.list()
                if "generateContent" in (m.supported_actions or [])
            ]
            print(f"  [GenAI Available Models]: {available[:6]}...")
            for target in candidate_models:
                if target in available or any(target in a for a in available):
                    matched = next((a for a in available if target in a), target)
                    self.gemini_model_name = matched
                    print(f"  [Info] Gemini AI Auto-Locked on Model: {matched}!")
                    return
            if available:
                self.gemini_model_name = available[0]
                print(f"  [Info] Gemini AI Connected to default available Model: {available[0]}!")
                return
        except Exception as e:
            print(f"  [Model Search Error] {e}")
            self.gemini_model_name = None

    def ensure_notion_db_schema(self):
        print("\n=== 🛠️ [Setup] Auto-Configuring Notion Database Schema ===")
        headers = {
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        url_get = f"https://api.notion.com/v1/databases/{NOTION_INTELLIGENCE_DB_ID}"
        try:
            res = requests.get(url_get, headers=headers, timeout=10)
            if res.status_code != 200:
                print(f"  [Warning] Could not inspect Notion DB (Status {res.status_code})")
                return
                
            db_data = res.json()
            props = db_data.get("properties", {})
            
            for p_name, p_val in props.items():
                if p_val.get("type") == "title":
                    self.notion_title_prop_name = p_name
                    print(f"  [Notion Schema] Identified primary title property as: '{p_name}'")
                    break
                    
            patch_props = {}
            if "メディアソース" not in props:
                patch_props["メディアソース"] = {"select": {}}
            if "一次URL" not in props:
                patch_props["一次URL"] = {"url": {}}
            if "ショート台本骨格" not in props:
                patch_props["ショート台本骨格"] = {"rich_text": {}}
            if "合致根拠と期待値" not in props:
                patch_props["合致根拠と期待値"] = {"rich_text": {}}
            if "日時" not in props:
                patch_props["日時"] = {"date": {}}
            if "採用" not in props:
                patch_props["採用"] = {"checkbox": {}}
            if "スコア" not in props:
                patch_props["スコア"] = {"number": {}}
            if "再生数" not in props:
                patch_props["再生数"] = {"number": {}}
            if "伸び速度" not in props:
                patch_props["伸び速度"] = {"number": {}}
            if "言及ソース数" not in props:
                patch_props["言及ソース数"] = {"number": {}}
            # 「採用」だけだと作ったのか作っていないのかが後から分からないため、
            # 制作の進み具合を段階で持てるようにする。
            if "制作状況" not in props:
                patch_props["制作状況"] = {
                    "select": {
                        "options": [
                            {"name": "未着手", "color": "default"},
                            {"name": "制作中", "color": "yellow"},
                            {"name": "投稿済み", "color": "green"},
                            {"name": "見送り", "color": "gray"},
                        ]
                    }
                }

            if patch_props:
                print(f"  [Notion Auto-Upgrade] Creating {len(patch_props)} new customized columns in your database...")
                requests.patch(url_get, headers=headers, json={"properties": patch_props}, timeout=10)
                print("  [Success] Notion Database schema fully upgraded and synchronized!")
            else:
                print(f"  [Notion Schema] All required columns are already present!")
        except Exception as e:
            print(f"  [Error] Notion schema auto-configuration error: {e}")

    def get_channel_id_cached(self, ch_obj):
        if "id" in ch_obj and ch_obj["id"].startswith("UC"):
            return ch_obj["id"]
            
        url_or_name = ch_obj.get("url", "")
        handle_match = re.search(r'(@[A-Za-z0-9_.-]+|@[^\s/]+)', url_or_name)
        if not handle_match:
            return None
        handle_str = handle_match.group(0)
        
        def _search_ch(client):
            return client.search().list(part="snippet", q=handle_str, type="channel", maxResults=1).execute()
            
        res = self.key_manager.execute(_search_ch)
        if res and res.get("items"):
            found_id = res["items"][0]["snippet"]["channelId"]
            ch_obj["id"] = found_id
            save_intelligence_config(self.config)
            return found_id
        return None

    def analyze_channels(self):
        print("\n=== [Phase 1] Analyzing Target YouTube Channels (Separate Competitor Track) ===")
        if not self.key_manager.get_client():
            print("  [Notice] YOUTUBE_API_KEY not present in local env. Skipping channel analysis.")
            return

        skipped_offtopic = 0

        for ch in self.config.get("target_channels", []):
            if not ch.get("enabled", True):
                continue
            ch_name = ch.get("name", "Unknown Channel")
            ch_id = self.get_channel_id_cached(ch)
            if not ch_id:
                continue
                
            playlist_id = "UU" + ch_id[2:]
            def _get_pl(client):
                return client.playlistItems().list(part="snippet", playlistId=playlist_id, maxResults=10).execute()
            pl_res = self.key_manager.execute(_get_pl)
            if not pl_res or not pl_res.get("items"):
                continue
                
            vid_ids = [item["snippet"]["resourceId"]["videoId"] for item in pl_res["items"] if "videoId" in item.get("snippet", {}).get("resourceId", {})]
            if not vid_ids:
                continue
                
            ids_str = ",".join(vid_ids)
            def _get_vids(client):
                # tags まで取るのは、タイトルに『鳴潮』と書かれていない動画でも
                # タグで判別できるようにするため（無関係な動画の混入を防ぐ）
                return client.videos().list(part="snippet,statistics", id=ids_str).execute()
            v_res = self.key_manager.execute(_get_vids)
            if not v_res or not v_res.get("items"):
                continue
                
            for video in v_res["items"]:
                snippet = video.get("snippet", {})
                stats = video.get("statistics", {})
                title = snippet.get("title", "")
                view_count = int(stats.get("viewCount", 0))
                like_count = int(stats.get("likeCount", 0))
                published_at = snippet.get("publishedAt", "")

                if view_count > 1500 or like_count > 100:
                    words = re.findall(r'([A-Za-z0-9_-]{2,}|[ァ-ンヴー]{2,}|[一-龥]{2,})', title)
                    for w in words:
                        if len(w) >= 2 and w not in ["鳴潮", "動画", "解説", "最強", "紹介"]:
                            self.trending_keywords.add(w)
                    
                    ch_title_lower = str(ch_name).lower() + str(title).lower()
                    if "diachannel" in ch_title_lower or "dia" in str(ch_name).lower() or "自チャンネル" in str(ch_name):
                        continue

                    # 監視対象チャンネルは鳴潮以外のゲームも投稿している。
                    # タイトル・概要・タグのどこにも手がかりが無いものは取り込まない。
                    if not is_relevant(title, snippet.get("description", ""), " ".join(snippet.get("tags", []) or [])):
                        skipped_offtopic += 1
                        continue

                    desc_raw = re.sub(r'\s+', ' ', str(snippet.get("description", ""))).strip()
                    desc_clean = desc_raw[:1500] if desc_raw else f"{title} に関するキャラクター性能評価、パーティ組み上げや立ち回り攻略の詳細論証。"
                    score, vph = score_competitor_video(view_count, like_count, published_at)
                    full_summary = f"【動画の概要と発信内容詳細】\n{desc_clean}\n\n（📊 バズ実績: {ch_name} にて現在 {view_count:,} 再生 / 高評価 {like_count:,} / 約 {vph:,.0f} 再生毎時）"

                    self.competitor_raw_items.append({
                        "title": f"【競合バズ実績】{title}",
                        "summary": full_summary,
                        "url": f"https://www.youtube.com/watch?v={video['id']}",
                        "source_type": "YouTube競合 (別枠全件枠)",
                        "score": score,
                        "view_count": view_count,
                        "like_count": like_count,
                        "views_per_hour": vph,
                        "published_at": published_at,
                    })
        print(f"  [Analytics Complete] Extracted {len(self.trending_keywords)} keywords and locked {len(self.competitor_raw_items)} competitor videos in separate track!")
        if skipped_offtopic:
            print(f"  [Relevance Filter] 鳴潮と無関係な競合動画 {skipped_offtopic} 件を除外しました。")

    def crawl_web_sources(self):
        print("\n=== [Phase 2] Crawling Multi-Platform Web Sources (Selective Foreign-Only Translation & Pure Direct URLs) ===")
        headers_web = {
            "User-Agent": "WutheringTrendsIntelligenceEngine/2.0 (YouTube Content Curator; by @Diachannel12345)",
            "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8"
        }
        
        def is_already_japanese(text):
            kana_kanji_count = len(re.findall(r'[ぁ-んァ-ヶー一-龠]', str(text)))
            return kana_kanji_count >= 3

        for src in self.config.get("target_web_sources", []):
            if not src.get("enabled", True):
                continue
            name = src.get("name", "Unknown Source")
            url = src.get("url", "")
            stype = src.get("type", "rss")
            weight = src.get("weight", 55)  # 情報源ごとの信頼度（設定ファイルで調整可能）
            print(f"  [Fetch] {name} ({stype})...")
            
            try:
                if "rss" in stype and feedparser:
                    res = requests.get(url, headers=headers_web, timeout=12)
                    if res.status_code == 200:
                        feed = feedparser.parse(res.text)
                        item_cnt = 0
                        for entry in feed.entries[:15]:
                            raw_title = getattr(entry, 'title', '')
                            link = getattr(entry, 'link', '')
                            summary_txt = getattr(entry, 'summary', raw_title)
                            summary_clean = re.sub(r'<[^>]+>', '', str(summary_txt))[:1500]
                            
                            if is_already_japanese(raw_title):
                                title_ja = raw_title
                                summary_ja = summary_clean if summary_clean != raw_title else raw_title
                            else:
                                title_ja = translate_if_needed(raw_title)
                                summary_ja = translate_if_needed(summary_clean) if summary_clean != raw_title else title_ja
                            
                            if not link or not str(link).startswith("http") or "google.com/search" in str(link):
                                continue

                            # 検索フィードには別ゲームの記事も紛れ込む。翻訳前の原文で判定する。
                            if not is_relevant(raw_title, summary_clean):
                                continue

                            published_iso = _feed_entry_iso(entry)
                            self.collected_raw_items.append({
                                "title": title_ja,
                                "summary": summary_ja,
                                "url": link,
                                "source_type": name[:30],
                                "score": score_web_item(weight, published_iso),
                                "published_at": published_iso or "",
                            })
                            item_cnt += 1
                        print(f"    -> Harvested & Selective-Translated {item_cnt} high-impact pure-link topic cards!")
            except Exception as e:
                print(f"  [Warning] Failed crawling {name}: {e}")
                
        print(f"  [Crawl Complete] Total collected raw items across all networks: {len(self.collected_raw_items)}")

    def update_schedule_if_stale(self, stale_after_hours=20):
        """新キャラ・バージョン実装予定のスケジュールを更新する（アップデート先読み機能）。

        頻繁には変わらない情報なので、15分おきの本体巡回に相乗りさせつつ
        実際のサイト取得・Gemini解析は stale_after_hours 時間おきに間引く。
        取得元は「⚙️ マルチメディア収集ソース」モーダルの
        「📅 更新カレンダー情報源」タブ（config_intelligence.json の schedule_sources）で管理される。
        """
        out_path = os.path.join(os.path.dirname(__file__), "../src/data/upcoming_schedule.json")

        try:
            if os.path.exists(out_path):
                with open(out_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                last_updated = datetime.fromisoformat(existing["updated_at"])
                age_hours = (datetime.now(timezone.utc) - last_updated).total_seconds() / 3600
                if age_hours < stale_after_hours:
                    print(f"  [Schedule] 前回更新から {age_hours:.1f} 時間しか経っていないためスキップ（{stale_after_hours}時間おき）")
                    return
        except Exception:
            pass  # ファイル破損・初回等はそのまま更新処理へ

        sources = [s for s in self.config.get("schedule_sources", []) if s.get("enabled", True)]
        if not sources:
            print("  [Schedule] スケジュール情報源が未設定のためスキップ")
            return

        if not self.gemini_model_name:
            print("  [Schedule] Gemini 未設定のためスケジュール解析をスキップ")
            return

        print(f"\n=== [Schedule] 📅 {len(sources)}件の情報源からアップデート予定を解析中 ===")
        headers_web = {"User-Agent": "WutheringTrendsIntelligenceEngine/2.0 (Schedule Tracker)"}
        combined_text = ""
        for src in sources:
            try:
                res = requests.get(src["url"], headers=headers_web, timeout=15)
                if res.status_code != 200:
                    print(f"  [Warning] {src.get('name')}: HTTP {res.status_code}")
                    continue
                text = BeautifulSoup(res.text, "html.parser").get_text(separator=" ", strip=True) if BeautifulSoup else res.text
                combined_text += f"\n\n=== 情報源: {src.get('name')} ({src['url']}) ===\n{text[:20000]}"
            except Exception as e:
                print(f"  [Warning] {src.get('name')} の取得に失敗: {e}")

        if not combined_text.strip():
            print("  [Schedule] 情報源からテキストを取得できなかったため更新を中止")
            return

        prompt = (
            "あなたはゲーム『鳴潮 (Wuthering Waves)』の情報整理担当です。\n"
            "以下は攻略Wiki・イベント一覧ページ等から取得した生テキストです。ここから「今後実装予定・および現在"
            "開催中のキャラクター・武器・バージョン・期間限定イベント・ストーリー章」のスケジュールを抽出してください。\n\n"
            "【指示】\n"
            "1. 日付は可能なら YYYY-MM-DD 形式に正規化する。年が不明なら文脈から補い、それでも不明なら null。\n"
            "2. わかる場合は end_date（バナー終了日・イベント終了日等）も入れる。不明なら null。\n"
            "3. 公式発表済みか、リーク・非公式情報かを confirmed (true/false) で必ず区別する。イベント一覧ページに"
            "具体的な開始・終了日として明記されているものは confirmed:true でよい。未来のキャラ実装のような"
            "リーク・予想情報は confirmed:false とする。\n"
            "4. 「開始日・終了日ともに今日より過去」のものだけを除外する。開始日が今日より前でも終了日が今日以降"
            "であれば『現在開催中』として必ず含める。\n"
            "5. category は \"character\"(キャラ実装/バナー) / \"weapon\"(武器バナー) / \"version\"(バージョン更新) / "
            "\"event\"(期間限定イベント) / \"story\"(ストーリー章) のいずれかで分類する。\n"
            "6. character・event は必ず日本語で出力すること。情報源に英語表記しかない場合でも、"
            "公式の日本語ローカライズ名（判明していれば）またはカタカナ表記に翻訳し、英語の原文を"
            "そのまま出力してはならない（開発者・閲覧者は日本語話者のため）。\n"
            "7. 同一の出来事が複数ソースに重複して出てきた場合は1件にまとめる。\n"
            "8. イベント一覧ページには同時に10件以上のイベントが載っていることがある。代表的なものだけを"
            "抜粋せず、日付が読み取れるものは可能な限り全件拾うこと。件数上限は設けない。\n\n"
            "出力は必ず【純粋なJSONフォーマットの配列】のみ。Markdownコードブロックや解説文は禁止。\n"
            "[\n  {\n"
            '    "character": "キャラクター名・武器名・イベント名など",\n'
            '    "event": "具体的な内容（実装 / バナー開始 / バージョンアップデート / イベント開催 等）",\n'
            '    "category": "character/weapon/version/event/story のいずれか",\n'
            '    "start_date": "YYYY-MM-DD または null",\n'
            '    "end_date": "YYYY-MM-DD または null",\n'
            '    "confirmed": true または false,\n'
            '    "notes": "補足（フェーズ、根拠等）を1行程度で"\n'
            "  }\n]\n\n"
            "生テキスト:\n" + combined_text[:90000]
        )

        try:
            res = self.gemini_client.models.generate_content(
                model=self.gemini_model_name, contents=prompt
            )
            raw_txt = re.sub(r'^```(json)?|```$', '', res.text.strip(), flags=re.MULTILINE).strip()
            events = json.loads(raw_txt)
            events = [e for e in events if e.get("character")]

            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump({
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "events": events
                }, f, ensure_ascii=False, indent=2)
            print(f"  [Schedule Success] {len(events)}件の実装予定を抽出・保存しました")
        except Exception as e:
            print(f"  [Warning] スケジュール解析に失敗: {e}")

    def _gemini_enrich(self, sorted_items, competitor_cards, target_count):
        """トピック選出と競合動画の解説を1回の Gemini 呼び出しでまとめて行う。

        戻り値は (topics, competitors) のタプル。失敗時は None を返し、
        呼び出し側は従来通りアルゴリズムによるフォールバックへ落ちる。
        """
        # スコアや再生数などの数値はこちらで確定済みなので、AI には
        # 文章の生成だけを任せ、数値は後からこちらで戻す（AIに数値を作らせない）。
        topic_src = [
            {
                "title": it.get("title", ""),
                "summary": str(it.get("summary", ""))[:600],
                "url": it.get("url", ""),
                "source_type": it.get("source_type", ""),
                "mention_count": it.get("mention_count", 1),
            }
            for it in sorted_items[:20]
        ]
        comp_src = [
            {
                "title": c.get("topic_title", ""),
                "summary": str(c.get("script_outline", ""))[:600],
                "url": c.get("source_url", ""),
            }
            for c in competitor_cards[:15]
        ]

        prompt = (
            "あなたはゲーム『鳴潮』専門のコンテンツアナリストです。\n"
            "ショート動画の企画を立てるために、以下2種類の素材を解析してください。\n\n"
            "【A: Web/SNSトピック候補】から最大 " + str(target_count) + " 件を選び、\n"
            "【B: 競合YouTube動画】は件数を削らず全件について解説してください。\n\n"
            "【⚠️最優先の絶対指令：事実の捏造を禁ずる⚠️】\n"
            "A. 素材に書かれていない情報を、絶対に補完・推測・創作してはならない。\n"
            "   キャラクター名・音骸セット名・武器名・数値・効果は、素材に明記されているものだけを使うこと。\n"
            "   もっともらしい鳴潮の用語で埋めることは、最も重大な違反とみなす。\n"
            "B. 素材の情報が薄い場合は、無理に長文化せず、分かっている範囲だけを簡潔に書くこと。\n"
            "C. 素材が『鳴潮』に関するものだと判断できない場合（別ゲーム・別ジャンルの話題など）は、\n"
            "   その項目を出力に含めず、丸ごと省略すること。件数合わせのために残してはならない。\n"
            "D. source_url は必ず素材に記載されたURLをそのまま使うこと。URLを創作・改変してはならない。\n\n"
            "共通の指令:\n"
            "1. 素材から読み取れる範囲で、結論・根拠・キャラ名・パーティ構成・数値まで具体的に記述すること。\n"
            "2. 意味の薄いあらすじで済ませないこと（ただしAを優先し、無い情報は書かない）。\n"
            "3. 『冒頭3秒』『〜をご存じですか？！』のような定型テンプレートは禁止。\n"
            "4. 英語素材は100%自然な日本語へ完全翻訳すること。\n"
            "5. reason は「なぜ今このネタなのか」を、時期・競合状況・話題性の観点で具体的に書くこと。\n\n"
            "出力は純粋なJSONオブジェクトのみ。Markdownコードブロックは不可。形式:\n"
            "{\n"
            '  "topics": [\n'
            "    {\n"
            '      "topic_title": "純日本語の魅力的な見出し",\n'
            '      "summary": "核心ポイント(純日本語)",\n'
            '      "source_url": "素材に記載された元URLを正確に代入",\n'
            '      "source_type": "素材のメディア種別",\n'
            '      "script_outline": "【動画・記事の完全論説・網羅的詳細】：\\n(全容を長尺で徹底解説)",\n'
            '      "reason": "なぜ今このネタが狙い目なのかの具体的な理由"\n'
            "    }\n"
            "  ],\n"
            '  "competitors": [\n'
            "    {\n"
            '      "topic_title": "純日本語の見出し",\n'
            '      "summary": "動画の核心ポイント",\n'
            '      "source_url": "素材に記載された元動画URLを正確に代入",\n'
            '      "source_type": "YouTube競合 (別枠全件枠)",\n'
            '      "script_outline": "【動画・記事の完全論説・網羅的詳細】：\\n(結論・ビルド方針・強さを徹底解説)",\n'
            '      "reason": "この競合動画が伸びている理由の分析"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "A: Web/SNSトピック候補:\n" + json.dumps(topic_src, ensure_ascii=False) + "\n\n"
            "B: 競合YouTube動画:\n" + json.dumps(comp_src, ensure_ascii=False)
        )

        try:
            res = self.gemini_client.models.generate_content(
                model=self.gemini_model_name, contents=prompt
            )
            txt = re.sub(r'^```(json)?|```$', '', res.text.strip(), flags=re.MULTILINE).strip()
            data = json.loads(txt)
        except Exception as e:
            print(f"  [Warning] Gemini combined analysis failed ({e}). Falling back to advanced algorithm.")
            return None

        # 数値系のフィールドは元データ（URLをキー）から復元する
        topic_meta = {it.get("url", ""): it for it in sorted_items}
        comp_meta = {c.get("source_url", ""): c for c in competitor_cards}

        dropped = 0
        topics_out = []
        for idea in data.get("topics", []) or []:
            tt = str(idea.get("topic_title", ""))
            to = str(idea.get("script_outline", ""))
            if len(re.findall(r'[ぁ-んァ-ヶー一-龠]', tt)) < 2 or "についてご存じですか" in to:
                continue
            # 渡していないURLが返ってきた場合、素材に無いものを作文した疑いが強いので捨てる
            meta = topic_meta.get(idea.get("source_url", ""))
            if meta is None:
                dropped += 1
                continue
            idea["score"] = meta.get("score", 60)
            idea["view_count"] = 0
            idea["views_per_hour"] = 0
            idea["mention_count"] = meta.get("mention_count", 1)
            topics_out.append(idea)

        comps_out = []
        for c in data.get("competitors", []) or []:
            meta = comp_meta.get(c.get("source_url", ""))
            if meta is None:
                dropped += 1
                continue
            c["score"] = meta.get("score", 90)
            c["view_count"] = meta.get("view_count", 0)
            c["views_per_hour"] = meta.get("views_per_hour", 0)
            c["mention_count"] = 1
            comps_out.append(c)

        if dropped:
            print(f"  [Fabrication Guard] 素材に無いURLを含む {dropped} 件を破棄しました。")

        return topics_out, comps_out

    def generate_and_filter_ideas(self):
        print("\n=== [Phase 3] Generating, Deduplicating & Filtering Video Topics ===")
        target_count = self.config.get("settings", {}).get("target_items_per_run", 12)
        
        existing_urls = set()
        existing_titles = set()
        
        try:
            cache_path = os.path.join(os.path.dirname(__file__), "../src/data/intelligence_cache.json")
            if os.path.exists(cache_path):
                with open(cache_path, "r", encoding="utf-8") as cf:
                    cdata = json.load(cf)
                    for item in cdata.get("items", []):
                        u = str(item.get("sourceUrl", "")).strip()
                        t = str(item.get("title", "")).strip().lower()
                        if u and "http" in u: existing_urls.add(u)
                        if t: existing_titles.add(t)
        except Exception:
            pass

        if NOTION_API_KEY and NOTION_INTELLIGENCE_DB_ID:
            try:
                headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}
                res_db = requests.post(f"https://api.notion.com/v1/databases/{NOTION_INTELLIGENCE_DB_ID}/query", headers=headers, json={"page_size": 100}, timeout=8)
                if res_db.status_code == 200:
                    for page in res_db.json().get("results", []):
                        props = page.get("properties", {})
                        u_prop = props.get("一次URL", {})
                        if u_prop and u_prop.get("url"):
                            existing_urls.add(str(u_prop["url"]).strip())
                        t_prop = props.get("名前") or props.get("Name") or props.get("title")
                        if t_prop and t_prop.get("title") and len(t_prop["title"]) > 0:
                            existing_titles.add(str(t_prop["title"][0]["plain_text"]).strip().lower())
            except Exception:
                pass

        print(f"  [Deduplication Shield] Registered {len(existing_urls)} existing URLs and {len(existing_titles)} existing titles in prevention memory.")

        upcoming_events = load_upcoming_events()

        unique_raw_items = []
        seen_in_batch_url = set()
        seen_in_batch_title = set()
        
        for item in self.collected_raw_items:
            i_url = str(item.get("url", "")).strip()
            i_title = str(item.get("title", "")).strip().lower()
            
            if i_url in existing_urls or i_title in existing_titles or i_url in seen_in_batch_url or i_title in seen_in_batch_title:
                continue
            
            if i_url and "http" in i_url: seen_in_batch_url.add(i_url)
            seen_in_batch_title.add(i_title)
            
            combined = (item["title"] + " " + item.get("summary", "")).lower()
            for kw in self.trending_keywords:
                if kw.lower() in combined:
                    item["score"] = min(100, item.get("score", 60) + 10)
                    item["match_kw"] = kw
                    break

            # 実装/開催が近い要素に触れているネタを浮上させる
            boost, ev_name = schedule_boost(combined, upcoming_events)
            if boost:
                item["score"] = min(100, item.get("score", 60) + boost)
                item["schedule_hit"] = ev_name

            unique_raw_items.append(item)

        print(f"  [Deduplication Complete] Filtered down from {len(self.collected_raw_items)} raw grabs to {len(unique_raw_items)} distinct, fresh candidates.")

        # 同じ話題が別ソースから何件も並ぶのを畳む。複数が触れている話題は加点される。
        before_cluster = len(unique_raw_items)
        unique_raw_items = cluster_similar_items(unique_raw_items)
        print(f"  [Topic Clustering] Merged {before_cluster} candidates into {len(unique_raw_items)} distinct topics.")

        web_items = [x for x in unique_raw_items if "youtube" not in str(x.get("source_type", "")).lower() and "youtube" not in str(x.get("url", "")).lower()]
        yt_items = [x for x in unique_raw_items if "youtube" in str(x.get("source_type", "")).lower() or "youtube" in str(x.get("url", "")).lower()]
        
        web_sorted = sorted(web_items, key=lambda x: x.get("score", 0), reverse=True)[:28]
        yt_sorted = sorted(yt_items, key=lambda x: x.get("score", 0), reverse=True)[:5]
        
        sorted_items = sorted(web_sorted + yt_sorted, key=lambda x: x.get("score", 0), reverse=True)
        print(f"  [Diversity Balance] Selected {len(web_sorted)} Web/Reddit sources and {len(yt_sorted)} YouTube sources into final pool.")
        
        if not sorted_items:
            print("  [Info] No candidate items found above criteria in this run.")
            return []

        # ★【新・仕様変更：一石二鳥＆競合全権アンチダブリ監視システム】
        # Web巡回(Reddit/TikTok/Web版YouTube等)からの12件選出に加え、競合チャンネル監視の最新ヒット動画は
        # 「ダブりさえなければ何件でも全て余すことなくピックアップ・収録する」無敵全採掘モード！
        competitor_cards = []
        for comp in sorted(self.competitor_raw_items, key=lambda x: x.get("score", 0), reverse=True):
            c_url = str(comp.get("url", "")).strip()
            c_title = str(comp.get("title", "")).strip().lower()
            if c_url in existing_urls or c_title in existing_titles or c_url in seen_in_batch_url:
                continue
            if c_url and "http" in c_url: seen_in_batch_url.add(c_url)
            
            det_raw = str(comp.get("summary", "")).strip()
            det_jp = translate_if_needed(det_raw)
            c_title_jp = translate_if_needed(comp.get("title", "競合注目テーマ"))
            
            detail_summary = f"【動画・記事の完全論説・網羅的詳細】：\n{det_jp if len(det_jp) > 15 else f'『{c_title_jp}』における攻略戦略やビルド意図、および界隈へのインパクト詳細。'}"

            competitor_cards.append({
                "topic_title": c_title_jp,
                "summary": det_jp[:100],
                "source_url": comp.get("url", ""),
                "source_type": "YouTube競合 (別枠全件枠)",
                "script_outline": detail_summary,
                "reason": (
                    f"競合チャンネルで約 {comp.get('views_per_hour', 0):,.0f} 再生/時 のペースで伸びている実績データに基づく抽出"
                ),
                "score": comp.get("score", 90),
                "view_count": comp.get("view_count", 0),
                "views_per_hour": comp.get("views_per_hour", 0),
                "mention_count": 1,
            })
                
        print(f"  [Competitor Track Unlimited] Successfully locked {len(competitor_cards)} non-duplicate competitor hit videos for full immersion!")

        # --- Gemini 解析（トピックと競合を1回の呼び出しでまとめて処理する）---
        # 以前はトピック用・競合用で別々に呼んでいたため、15分おきの巡回と掛け合わせて
        # 1日約192回に達し、無料枠(1日20回)を大幅に超えて9割が失敗していた。
        # 1回にまとめることで消費を半減させる（巡回間隔の見直しと合わせて枠内に収める）。
        if not self.gemini_model_name:
            self.gemini_topic_status = "not_configured"
            self.gemini_competitor_status = "not_configured"
        elif not sorted_items and not competitor_cards:
            self.gemini_topic_status = "no_items"
            self.gemini_competitor_status = "no_items"
        else:
            self.gemini_topic_status = "failed" if sorted_items else "no_items"
            self.gemini_competitor_status = "failed" if competitor_cards else "no_items"

            enriched = self._gemini_enrich(sorted_items, competitor_cards, target_count)
            if enriched:
                topics_out, comps_out = enriched
                if topics_out:
                    self.gemini_topic_status = "success"
                if comps_out:
                    competitor_cards = comps_out
                    self.gemini_competitor_status = "success"
                if topics_out:
                    print(f"  [Gemini Success] {len(topics_out)} topics / {len(comps_out)} competitor cards enriched in a single call.")
                    return topics_out[:target_count] + competitor_cards

        out_ideas = []
        for item in sorted_items[:target_count]:
            kw_match = item.get("match_kw", "注目トレンド")
            t_title = translate_if_needed(item.get("title", "無題のトレンドネタ"))
            t_sum = translate_if_needed(item.get("summary", "")).strip()
            if len(re.findall(r'[ぁ-んァ-ヶー一-龠]', t_title)) < 2:
                continue
            out_ideas.append({
                "topic_title": t_title,
                "summary": t_sum[:100],
                "source_url": item.get("url", ""),
                "source_type": item.get("source_type", "Web調査"),
                "script_outline": f"【動画・記事の完全論説・網羅的詳細】：\n{t_sum if len(t_sum) > 15 else f'「{t_title}」にて提起されたビルド方針や戦略、イベント攻略情報および熱烈な議論詳細の全容。'}",
                "reason": _build_reason(item, kw_match),
                "score": item.get("score", 60),
                "view_count": 0,
                "views_per_hour": 0,
                "mention_count": item.get("mention_count", 1),
            })
        print(f"  [Algorithm Ready] Formatted {len(out_ideas)} items using advanced algorithm.")
        return out_ideas + competitor_cards

    def push_to_notion(self, ideas):
        print(f"\n=== [Phase 4] Pushing {len(ideas)} Cards to Notion ===")
        if not NOTION_API_KEY or not NOTION_INTELLIGENCE_DB_ID:
            print("  [Notice] NOTION_API_KEY or NOTION_INTELLIGENCE_DB_ID is missing.")
            return

        headers_notion = {
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        url_post = "https://api.notion.com/v1/pages"
        success_cnt = 0

        for idea in ideas:
            payload = {
                "parent": {"database_id": NOTION_INTELLIGENCE_DB_ID},
                "properties": {
                    self.notion_title_prop_name: {"title": [{"text": {"content": str(idea.get("topic_title", ""))[:100]}}]},
                    "メディアソース": {"select": {"name": str(idea.get("source_type", "外部情報"))[:50]}},
                    "一次URL": {"url": str(idea.get("source_url", ""))[:200] if str(idea.get("source_url", "")).startswith("http") else None},
                    "ショート台本骨格": {"rich_text": [{"text": {"content": str(idea.get("script_outline", ""))[:2000]}}]},
                    "合致根拠と期待値": {"rich_text": [{"text": {"content": str(idea.get("reason", ""))[:400]}}]},
                    "日時": {"date": {"start": (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")}},
                    "スコア": {"number": idea.get("score", 60)},
                    "再生数": {"number": int(idea.get("view_count", 0) or 0)},
                    "伸び速度": {"number": round(float(idea.get("views_per_hour", 0) or 0), 1)},
                    "言及ソース数": {"number": int(idea.get("mention_count", 1) or 1)},
                    "制作状況": {"select": {"name": "未着手"}},
                }
            }
            try:
                res = notion_request("POST", url_post, headers_notion, json=payload, timeout=8)
                if res.status_code in [200, 201]:
                    success_cnt += 1
                    print(f"  [Notion OK] Placed card: {idea.get('topic_title')[:35]}...")
                else:
                    print(f"  [Notion Fail] Status {res.status_code}: {res.text}")
                time.sleep(0.3)
            except Exception as e:
                print(f"  [Error] Notion transmission error: {e}")
                
        print(f"  [Complete] Successfully appended {success_cnt} new topic cards to your Notion database!")
        
        # さらに、Webスタジオ側が絶対に「読込エラー」を出さないよう安心のローカルバックアップJSONへ同時同期！
        try:
            cache_dir = os.path.join(os.path.dirname(__file__), "../src/data")
            os.makedirs(cache_dir, exist_ok=True)
            cache_path = os.path.join(cache_dir, "intelligence_cache.json")
            cache_items = []
            for idx, idea in enumerate(ideas):
                cache_items.append({
                    "id": f"card-{idx}",
                    "title": str(idea.get("topic_title", "無題のトレンド")),
                    "sourceType": str(idea.get("source_type", "外部情報"))[:30],
                    "sourceUrl": str(idea.get("source_url", "")),
                    "scriptOutline": str(idea.get("script_outline", "")),
                    "reason": str(idea.get("reason", "")),
                    "score": idea.get("score", 60),
                    "viewCount": int(idea.get("view_count", 0) or 0),
                    "viewsPerHour": round(float(idea.get("views_per_hour", 0) or 0), 1),
                    "mentionCount": int(idea.get("mention_count", 1) or 1),
                    "date": (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d"),
                    "createdTime": (datetime.now(timezone.utc) + timedelta(hours=9)).isoformat()
                })
            with open(cache_path, "w", encoding="utf-8") as cf:
                json.dump({"success": True, "items": cache_items}, cf, ensure_ascii=False, indent=2)
            print("  [Backup Sync] Mirrored cards to local intelligence_cache.json for 100% zero-error visual viewing on Vercel!")
        except Exception as ce:
            print(f"  [Notice] Cache mirror warning: {ce}")

    def cleanup_old_notion_cards(self):
        """1週間(7日間)以上経過した古い記事を自動でアーカイブし、パンクと動作遅延を未然に100%防止する"""
        print("\n=== [Phase 5] 🧹 Auto-Cleaning Up Notion Cards Older Than 7 Days ===")
        if not NOTION_API_KEY or not NOTION_INTELLIGENCE_DB_ID:
            print("  [Skip] Notion credentials missing.")
            return

        headers = {
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        
        # 7日前のタイムスタンプまたは日付
        seven_days_ago = (datetime.now(timezone.utc) + timedelta(hours=9) - timedelta(days=7)).strftime("%Y-%m-%d")
        print(f"  [Target Horizon] Identifying all topic cards older than {seven_days_ago}...")
        
        # まずは「日時」プロパティでの古いもの、あるいは作成日時での古いものを検索
        # ただし「採用」済み(ネタ帳として使う予定のもの)は、いつまでも参照できるよう対象から除外する
        url_query = f"https://api.notion.com/v1/databases/{NOTION_INTELLIGENCE_DB_ID}/query"
        payload_query = {
            "filter": {
                "and": [
                    {
                        "timestamp": "created_time",
                        "created_time": {"before": f"{seven_days_ago}T00:00:00.000Z"}
                    },
                    {
                        "property": "採用",
                        "checkbox": {"equals": False}
                    }
                ]
            },
            "page_size": 100
        }
        
        try:
            res = requests.post(url_query, headers=headers, json=payload_query, timeout=12)
            if res.status_code != 200:
                print(f"  [Warning] Failed to query old pages: {res.text}")
            else:
                pages = res.json().get("results", [])
                if not pages:
                    print("  [Cleanup] Zero cards exceeded the 7-day shelf-life limit. Database is perfectly fresh!")
                else:
                    archived_cnt = 0
                    for pg in pages:
                        page_id = pg["id"]
                        url_patch = f"https://api.notion.com/v1/pages/{page_id}"
                        del_res = notion_request("PATCH", url_patch, headers, json={"archived": True}, timeout=8)
                        if del_res.status_code in [200, 201]:
                            archived_cnt += 1
                        time.sleep(0.2)
                    print(f"  [Cleanup Success] Automatically archived and wiped {archived_cnt} outdated cards!")

            # 続いて！！ 現在Notionに残留してしまっている【 未翻訳(英語のまま) 】や【 陳腐な機械的テンプレート 】の品質未達カードを自発的にお掃除！
            print("\n=== [Phase 5-B] 🛡️ Quality Patrol: Purging Un-Translated English & Mechanical Boilerplate Cards ===")
            res_all = requests.post(url_query, headers=headers, json={"page_size": 100}, timeout=12)
            if res_all.status_code == 200:
                all_pages = res_all.json().get("results", [])
                purged_cnt = 0
                for pg in all_pages:
                    pid = pg["id"]
                    props = pg.get("properties", {})
                    
                    # タイトルの抽出
                    t_str = ""
                    t_prop = props.get(self.notion_title_prop_name) or props.get("名前") or props.get("Name") or props.get("title")
                    if t_prop and t_prop.get("title") and len(t_prop["title"]) > 0:
                        t_str = t_prop["title"][0]["plain_text"]
                        
                    # 台本の抽出
                    o_str = ""
                    o_prop = props.get("ショート台本骨格", {})
                    if o_prop and o_prop.get("rich_text") and len(o_prop["rich_text"]) > 0:
                        o_str = o_prop["rich_text"][0]["plain_text"]
                        
                    # ひらがな・カタカナ・日常漢字が極端に少ない(純英語状態) または 「についてご存じですか？！」などの機械的文字列が含まれている場合は徹底削除！
                    if len(re.findall(r'[ぁ-んァ-ヶー一-龠]', t_str)) < 2 or "についてご存じですか" in o_str or "Bro had one job" in t_str or "Reddit -" in o_str:
                        notion_request("PATCH", f"https://api.notion.com/v1/pages/{pid}", headers, json={"archived": True}, timeout=10)
                        purged_cnt += 1
                        print(f"    -> Purged sub-quality un-translated card: '{t_str[:35]}...'")
                print(f"  [Quality Patrol Complete] Successfully scrubbed {purged_cnt} un-translated or mechanical cards from Notion!")
        except Exception as e:
            print(f"  [Error during cleanup] {e}")

    def run(self):
        now_str = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime('%Y/%m/%d %H:%M:%S (JST)')
        print(f"\n--- [Intelligence Engine Started] {now_str} ---")
        run_start_time = time.time()

        # 巡回間隔のガード。外部 cron が15分おきに叩いても、ここで実際の実行頻度を決める。
        # cron 側の設定を触らずに間隔を変えられるようにしてある（設定ファイルの
        # settings.min_run_interval_minutes）。手動実行(--force / FORCE_RUN)は素通し。
        interval = int(self.config.get("settings", {}).get("min_run_interval_minutes", 0) or 0)
        elapsed = minutes_since_last_run()
        if interval and elapsed is not None and elapsed < interval and not is_force_run():
            print(
                f"  [Skip] 前回の収集から {elapsed:.0f} 分しか経っていません"
                f"（設定間隔 {interval} 分）。今回はスキップします。"
            )
            print("  ※ Gemini無料枠とYouTube APIクォータを使い切らないための意図的な間引きです。")
            return

        try:
            self.analyze_channels()
            self.crawl_web_sources()
            ideas = self.generate_and_filter_ideas()
            
            # 各ソースごとの収集実績内訳をカウント
            source_breakdown = {}
            for idx, item in enumerate(ideas or []):
                st = str(item.get("source_type", "一般Web")).strip()
                source_breakdown[st] = source_breakdown.get(st, 0) + 1
                
            if ideas:
                self.push_to_notion(ideas)
            self.cleanup_old_notion_cards()

            try:
                self.update_schedule_if_stale()
            except Exception as e:
                print(f"  [Warning] Schedule update failed (non-fatal): {e}")
            
            # ★活動ログ(Activity Log)の自動保存処理：いつ・どれだけ集まったかを記録！
            try:
                log_path = os.path.join(os.path.dirname(__file__), "intelligence_logs.json")
                logs_data = []
                if os.path.exists(log_path):
                    with open(log_path, "r", encoding="utf-8") as lf:
                        try: logs_data = json.load(lf)
                        except Exception: logs_data = []
                
                new_log_entry = {
                    "timestamp": (datetime.now(timezone.utc) + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M:%S'),
                    "status": "Success",
                    "total_harvested": len(self.collected_raw_items) + len(self.competitor_raw_items),
                    "final_selected": len(ideas or []),
                    "breakdown": source_breakdown,
                    "gemini_topic_status": self.gemini_topic_status,
                    "gemini_competitor_status": self.gemini_competitor_status
                }
                logs_data.insert(0, new_log_entry)
                logs_data = logs_data[:50]  # 最新50件の実績ログをスッキリ整理保持
                
                with open(log_path, "w", encoding="utf-8") as lf:
                    json.dump(logs_data, lf, ensure_ascii=False, indent=2)
                print(f"  [Activity Log Recorded] Saved operational stats ({len(ideas or [])} cards selected) into intelligence_logs.json!")
            except Exception as le:
                print(f"  [Log Warning] Failed to write intelligence logs: {le}")

            log_run("intelligence_collector", "success",
                    f"収集{len(self.collected_raw_items) + len(self.competitor_raw_items)}件 / 採用{len(ideas or [])}件",
                    time.time() - run_start_time)
            print("\n--- [All Intelligence Processing, Auto-Cleanup & Logging Completed Successfully!] ---\n")
        except Exception as e:
            print(f"[Fatal Exception during Intelligence Execution]: {traceback.format_exc()}")
            log_run("intelligence_collector", "error", traceback.format_exc(), time.time() - run_start_time)

if __name__ == "__main__":
    engine = IntelligenceEngine()
    engine.run()
