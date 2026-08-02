import os
import json
import traceback
import re
import requests
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from notion_utils import notion_request

# Load environment variables
load_dotenv()

CONFIG_FILE = "config.json"
def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: {CONFIG_FILE} not found. Using default settings.")
        return {
            "youtube": {
                "search_queries": ["鳴潮", "Wuthering Waves"], 
                "max_results_per_query": 50, 
                "region_code": "JP",
                "shorts_ratio": 0.85,
                "jp_ratio": 0.85
            }
        }
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def is_japanese(text):
    """テキストにひらがな・カタカナが含まれているか簡易判定（中国語の誤検知を防ぐため漢字を除外）"""
    return bool(re.search(r'[ぁ-んァ-ヶ]', text))

def should_exclude(title, exclude_words):
    """タイトルが除外ワードを含んでいるか判定

    英数字の語だけ単語境界 \\b を付け、日本語の語は素の部分一致で見る。
    日本語は文字同士が地続き（どちらも \\w 扱い）で境界が生まれないため、
    以前のように一律 \\b を付けると「鳴潮切り抜き集めてみた」「ホロライブの配信」等が
    素通りし、【】や空白で囲まれた時だけ偶然効く状態になっていた。
    """
    if not exclude_words:
        return False

    for ew in exclude_words:
        if not ew:
            continue

        pattern = re.escape(ew)
        # 半角英数字で始まる/終わる語のみ、部分一致の暴発を防ぐため境界を付ける
        if re.match(r'[A-Za-z0-9_]', ew[0]):
            pattern = r'\b' + pattern
        if re.match(r'[A-Za-z0-9_]', ew[-1]):
            pattern = pattern + r'\b'

        if re.search(pattern, title, re.IGNORECASE):
            return True
    return False

def translate_if_needed(text):
    """日本語が含まれていなければGoogle翻訳で日本語に変換する"""
    if not text:
        return text
        
    if is_japanese(text):
        return text
        
    try:
        # 短い中国語などが自動判定で日本語(ja)と誤判定されるのを防ぐため、
        # autoで翻訳前と同じ結果になった場合はzh-TWからの翻訳を試す
        translator_auto = GoogleTranslator(source='auto', target='ja')
        trans_auto = translator_auto.translate(text)
        
        if trans_auto != text:
            return trans_auto
            
        # それでも変わらない場合は中国語（繁体字）として強制翻訳
        translator_zh = GoogleTranslator(source='zh-TW', target='ja')
        return translator_zh.translate(text)
    except Exception as e:
        print(f"Translation error: {e}")
        return text

# Activity Logger for Web UI Tracking
class ActivityLogger:
    def __init__(self):
        now_jst = datetime.now(timezone.utc) + timedelta(hours=9)
        self.log_data = {
            "id": now_jst.isoformat(),
            "timestamp": now_jst.strftime("%Y/%m/%d %H:%M (JST)"),
            "status": "Success",
            "api_key_status": "Key #1 (メイン構成運用)",
            "new_items_count": 0,
            "summary": "処理開始中...",
            "details": [f"🎬 [{now_jst.strftime('%H:%M')}] 起動: トレンド収集＆自動整理プロセス始動"]
        }

    def log(self, msg):
        now_time = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%H:%M:%S")
        self.log_data["details"].append(f"• [{now_time}] {msg}")
        print(f"  [Log] {msg}")

    def set_key_status(self, text):
        self.log_data["api_key_status"] = text

    def add_new_items(self, count):
        self.log_data["new_items_count"] += count

    def set_summary(self, summary_text, is_error=False):
        self.log_data["summary"] = summary_text
        if is_error:
            self.log_data["status"] = "Error"

    def save_to_json(self):
        log_file = "logs.json"
        existing_logs = []
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    existing_logs = json.load(f)
                    if not isinstance(existing_logs, list):
                        existing_logs = []
            except Exception:
                existing_logs = []

        # 新規ログをトップ(最上位)に追加し、最大170件でカット (約1週間+ゆとり分)
        existing_logs.insert(0, self.log_data)
        existing_logs = existing_logs[:170]

        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(existing_logs, f, ensure_ascii=False, indent=2)
        print(f"  [Log Saved] 稼働ログが {log_file} に正常に保管・同期されました！")

# Global activity logger instance
logger = ActivityLogger()

class YouTubeKeyManager:
    """複数のAPIキーをローテートし、クォータ切れエラー(403等)を検知して予備キーへバトンタッチする管理クラス"""
    def __init__(self):
        raw_key_str = os.getenv("YOUTUBE_API_KEY", "")
        # カンマ、改行、スペースなどで結合されていれば綺麗に分解してプール化
        self.keys = [k.strip() for k in raw_key_str.split(",") if k.strip() and k.strip() != "your_youtube_api_key_here"]
        self.current_index = 0
        self.client = None
        if self.keys:
            self._build_client()
            logger.log(f"🔑 APIキープール構築完了: 全 {len(self.keys)} 枚中、Key #1 から通信スタート")
        else:
            print("  [Error] No valid YouTube API keys found in YOUTUBE_API_KEY.")
            logger.set_summary("YouTube APIキーが登録されていません", is_error=True)

    def _build_client(self):
        print(f"  [Info] Using YouTube API Key #{self.current_index + 1} of {len(self.keys)}")
        self.client = build("youtube", "v3", developerKey=self.keys[self.current_index])

    def get_client(self):
        return self.client

    def switch_key(self):
        if self.current_index + 1 < len(self.keys):
            msg = f"⚠️ Key #{self.current_index + 1} にて1日上限に到達！予備キー #{self.current_index + 2} へ即時オートローテーション移行！"
            print("  [Warning] " + msg)
            logger.log(msg)
            logger.set_key_status(f"⚠️ Key #{self.current_index + 2} へ交代適用済 ({len(self.keys)}枚体制)")
            self.current_index += 1
            self._build_client()
            return True
        msg = "🛑 設定中の全てのAPIキー(1〜4枚目)のクォータ上限を使い切りました！"
        print("  [Fatal Error] " + msg)
        logger.log(msg)
        logger.set_key_status("🛑 全キー上限到達停止中")
        logger.set_summary("全APIキー上限による中断", is_error=True)
        return False

    def execute(self, req_func):
        """API実行をラッピング。403エラー(Quota Exceeded)時には即時スイッチして再試行する"""
        while self.client:
            try:
                return req_func(self.client)
            except Exception as e:
                err_msg = str(e).lower()
                if "quota" in err_msg or "403" in err_msg or "exceeded" in err_msg or "ratelimit" in err_msg:
                    if not self.switch_key():
                        print(f"  [Error] All keys used up. Could not complete YouTube API request: {str(e)}")
                        return None
                else:
                    print(f"  [Error] Non-quota YouTube API error encountered: {str(e)}")
                    return None
        return None

def fetch_youtube_api(key_manager, query, max_results, region_code, order="date", published_after=None, video_duration="short"):
    """YouTube APIの実行（全自動フェイルオーバー付帯版）"""
    if max_results <= 0:
        return []
        
    kwargs = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": order,
        "maxResults": max_results,
        "regionCode": region_code,
        "relevanceLanguage": "ja",
        "videoDuration": video_duration
    }
    if published_after:
        kwargs["publishedAfter"] = published_after

    def _req(client):
        request = client.search().list(**kwargs)
        return request.execute()

    response = key_manager.execute(_req)
    if response and "items" in response:
        return response.get("items", [])
    return []

def get_target_channels_from_notion(headers, channels_db_id):
    """Notionのデータベースから対象チャンネルIDのリストを取得する"""
    if not channels_db_id:
        return []
    
    print("Fetching target channels from Notion...")
    url = f"https://api.notion.com/v1/databases/{channels_db_id}/query"
    channel_ids = []
    
    try:
        res = requests.post(url, headers=headers, json={})
        if res.status_code == 200:
            data = res.json()
            for page in data.get("results", []):
                props = page.get("properties", {})
                ch_id_prop = props.get("チャンネルID", {}).get("rich_text", [])
                if ch_id_prop:
                    channel_ids.append(ch_id_prop[0].get("plain_text", ""))
        else:
            print(f"  [Error] Failed to fetch channels: {res.text}")
    except Exception as e:
        print(f"  [Error] Communication with Notion failed: {str(e)}")
        
    print(f"Found {len(channel_ids)} target channels in Notion.")
    return channel_ids

def fetch_channel_latest_videos(key_manager, channel_id, max_results=10):
    """チャンネルのアップロード済みプレイリストから最新動画を取得し、1週間以内のものだけに絞る（キースワップ自動適用）"""
    if not channel_id.startswith("UC"):
        return []
    
    playlist_id = "UU" + channel_id[2:]
    
    def _req(client):
        request = client.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=max_results
        )
        return request.execute()

    response = key_manager.execute(_req)
    if not response:
        return []
        
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    items = []
    for pl_item in response.get("items", []):
        snippet = pl_item.get("snippet", {})
        published_at_str = snippet.get("publishedAt")
        if not published_at_str:
            continue
            
        try:
            published_at = datetime.fromisoformat(published_at_str.replace('Z', '+00:00'))
            if published_at < one_week_ago:
                continue
        except Exception:
            pass
            
        video_id = snippet.get("resourceId", {}).get("videoId")
        if video_id:
            items.append({
                "id": {"videoId": video_id},
                "snippet": snippet
            })
    return items

def get_youtube_trends(config, mode="latest"):
    """Fetch videos based on mode ('latest' or 'popular_weekly') using multi-key fallback support"""
    key_manager = YouTubeKeyManager()
    if not key_manager.get_client():
        return {"error": "No valid YouTube API Keys are configured."}
    
    results = {}
    
    yt_config = config.get("youtube", {})
    queries = yt_config.get("search_queries", ["鳴潮"])
    max_results = yt_config.get("max_results_per_query", 50)
    region_code = yt_config.get("region_code", "JP")
    exclude_words = yt_config.get("exclude_words", [])
    
    shorts_ratio = yt_config.get("shorts_ratio", 0.85)
    jp_ratio = yt_config.get("jp_ratio", 0.85)
    
    shorts_limit = int(max_results * shorts_ratio)
    long_limit = max_results - shorts_limit

    published_after = None
    order = "date"
    if mode == "popular_weekly":
        order = "viewCount"
        one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        published_after = one_week_ago.isoformat()

    for query in queries:
        print(f"  - Searching YouTube for: '{query}' (Mode: {mode})")
        shorts_items = fetch_youtube_api(key_manager, query, shorts_limit, region_code, order, published_after, "short")
        long_items = fetch_youtube_api(key_manager, query, long_limit, region_code, order, published_after, "medium")
        
        videos = []
        
        shorts_jp_limit = int(shorts_limit * jp_ratio)
        shorts_foreign_limit = shorts_limit - shorts_jp_limit
        shorts_jp_count = 0
        shorts_foreign_count = 0
        
        for item in shorts_items:
            snippet = item.get("snippet", {})
            if snippet.get("liveBroadcastContent") != "none": continue
            title = snippet.get("title", "")
            if should_exclude(title, exclude_words): continue
            
            if is_japanese(title):
                if shorts_jp_count >= shorts_jp_limit: continue
                shorts_jp_count += 1
            else:
                if shorts_foreign_count >= shorts_foreign_limit: continue
                shorts_foreign_count += 1
                
            videos.append({
                "title": translate_if_needed(title),
                "original_title": title,
                "channel": snippet.get("channelTitle", ""),
                "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                "video_type": "Shorts"
            })
            
        long_jp_limit = int(long_limit * jp_ratio)
        long_foreign_limit = long_limit - long_jp_limit
        long_jp_count = 0
        long_foreign_count = 0
        
        for item in long_items:
            snippet = item.get("snippet", {})
            if snippet.get("liveBroadcastContent") != "none": continue
            title = snippet.get("title", "")
            if should_exclude(title, exclude_words): continue
            
            if is_japanese(title):
                if long_jp_count >= long_jp_limit: continue
                long_jp_count += 1
            else:
                if long_foreign_count >= long_foreign_limit: continue
                long_foreign_count += 1
            
            videos.append({
                "title": translate_if_needed(title),
                "original_title": title,
                "channel": snippet.get("channelTitle", ""),
                "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                "video_type": "通常"
            })
            
        results[query] = videos

    notion_api_key = os.getenv("NOTION_API_KEY")
    channels_db_id = os.getenv("NOTION_CHANNELS_DB_ID")
    target_channels = yt_config.get("target_channels", [])
    
    if notion_api_key and channels_db_id:
        headers = {
            "Authorization": f"Bearer {notion_api_key}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        notion_channels = get_target_channels_from_notion(headers, channels_db_id)
        target_channels = list(set(target_channels + notion_channels))

    if target_channels and mode == "latest":
        print("\n  - Fetching latest videos from targeted channels...")
        channel_videos = []
        for ch_id in target_channels:
            print(f"    - Fetching channel: {ch_id}")
            ch_items = fetch_channel_latest_videos(key_manager, ch_id, max_results=5)
            for item in ch_items:
                snippet = item.get("snippet", {})
                
                title = snippet.get("title", "")
                if should_exclude(title, exclude_words): continue
                
                is_shorts = "#shorts" in title.lower() or "shorts" in title.lower()
                v_type = "Shorts" if is_shorts else "通常"
                
                channel_videos.append({
                    "title": translate_if_needed(title),
                    "original_title": title,
                    "channel": snippet.get("channelTitle", ""),
                    "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                    "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                    "video_type": v_type
                })
        if channel_videos:
            results["★Target Channels"] = channel_videos
            
    return results

def get_existing_notion_urls(headers, database_id):
    """Notionデータベースから既に登録されている動画URLのリスト（セット）を取得する"""
    print("Fetching existing video URLs from Notion database...")
    existing_urls = set()
    has_more = True
    next_cursor = None
    
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    
    while has_more:
        payload = {"page_size": 100}
        if next_cursor:
            payload["start_cursor"] = next_cursor
            
        try:
            res = requests.post(url, headers=headers, json=payload)
            if res.status_code == 200:
                data = res.json()
                for page in data.get("results", []):
                    # プロパティ名が "URL" であることを前提とする
                    props = page.get("properties", {})
                    url_prop = props.get("URL", {}).get("url")
                    if url_prop:
                        existing_urls.add(url_prop)
                        
                has_more = data.get("has_more", False)
                next_cursor = data.get("next_cursor")
            else:
                print(f"  [Error] Failed to fetch existing URLs: {res.text}")
                break
        except Exception as e:
            print(f"  [Error] Communication with Notion failed during query: {str(e)}")
            break
            
    print(f"Found {len(existing_urls)} existing videos in Notion.")
    return existing_urls

def send_to_notion(video_list, category, existing_urls):
    """Notionのデータベースに動画情報を追加する（重複排除つき）"""
    notion_api_key = os.getenv("NOTION_API_KEY")
    database_id = os.getenv("NOTION_DATABASE_ID")
    
    if not notion_api_key or notion_api_key == "your_notion_api_key_here" or not database_id or database_id == "your_notion_database_id_here":
        print("Notion API configuration is missing. Skipping Notion upload.")
        return

    headers = {
        "Authorization": f"Bearer {notion_api_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    print(f"Processing {len(video_list)} items for Notion (Category: {category})...")
    import time
    
    success_count = 0
    skip_count = 0
    for video in video_list:
        # 既にNotionに存在する場合はスキップ
        if video["url"] in existing_urls:
            skip_count += 1
            continue
            
        payload = {
            "parent": {"database_id": database_id},
            "cover": {
                "type": "external",
                "external": {"url": video["thumbnail"] if video["thumbnail"] else "https://via.placeholder.com/640x360.png?text=No+Image"}
            },
            "properties": {
                "タイトル": {
                    "title": [{"text": {"content": video["title"]}}]
                },
                "URL": {
                    "url": video["url"]
                },
                "チャンネル": {
                    "rich_text": [{"text": {"content": video["channel"]}}]
                },
                "カテゴリ": {
                    "select": {"name": category}
                }
            },
            "children": [
                {
                    "object": "block",
                    "type": "video",
                    "video": {
                        "type": "external",
                        "external": {
                            "url": video["url"]
                        }
                    }
                }
            ]
        }
        
        try:
            res = notion_request("POST", "https://api.notion.com/v1/pages", headers, json=payload)
            if res.status_code == 200:
                success_count += 1
                existing_urls.add(video["url"]) # 今回追加した分もセットに入れておく
            else:
                print(f"  [Error] Failed to upload to Notion: {res.text}")
        except Exception as e:
            print(f"  [Error] Communication with Notion failed: {str(e)}")
            
        time.sleep(0.35) # Rate limit avoidance (Max 3 req/sec)
        
    msg = f"カテゴリ「{category}」: 新規追加 {success_count} 件 / スキップ {skip_count} 件 (登録済)"
    print("  " + msg)
    if success_count > 0:
        logger.log(msg)
    logger.add_new_items(success_count)
    return success_count

def send_to_discord(msg, filepath=None):
    """DiscordのWebhookにメッセージ（とファイル）を送信する"""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url or webhook_url == "your_discord_webhook_url_here":
        return

    try:
        print("Sending message to Discord...")
        # 1. メッセージのみを送信（json形式）
        payload = {"content": msg}
        requests.post(webhook_url, json=payload)
        
        # 2. ファイルがある場合は別で送信（multipart/form-data形式）
        if filepath and os.path.exists(filepath):
            with open(filepath, "rb") as f:
                files = {"file": (os.path.basename(filepath), f)}
                requests.post(webhook_url, files=files)
                
        print("Successfully sent to Discord!")
    except Exception as e:
        print(f"Discord notification error: {str(e)}")

def get_flat_video_list(data_dict):
    """辞書から動画の平坦なリストを作成する"""
    flat_list = []
    for query, videos in data_dict.items():
        if isinstance(videos, list):
            flat_list.extend(videos)
    # 重複URLを削除
    seen_urls = set()
    unique_list = []
    for v in flat_list:
        if v["url"] not in seen_urls:
            unique_list.append(v)
            seen_urls.add(v["url"])
    return unique_list

def main():
    print("--- Wuthering Waves Trend Collector (Advanced) ---")
    logger.log("🚀 YouTubeトレンド収集ツールの自動実行プロセス始動")
    
    try:
        config = load_config()
        logger.log(f"📋 検索設定ロード: キーワード {len(config.get('youtube', {}).get('search_queries', []))}個 / 1ワード最大 {config.get('youtube', {}).get('max_results_per_query', 50)} 件")
        
        print("\n[1] Fetching LATEST YouTube trends (85% Shorts, 15% Normal)...")
        logger.log("🆕 [ステップ1] 「最新トレンド (Shorts & 長尺)」の検索・回収処理をスタート...")
        latest_data = get_youtube_trends(config, mode="latest")
        
        print("\n[2] Fetching POPULAR YouTube trends from past 7 days (85% Shorts, 15% Normal)...")
        logger.log("🔥 [ステップ2] 「週間人気ランキング (直近7日間)」の回収処理をスタート...")
        popular_data = get_youtube_trends(config, mode="popular_weekly")
        
        collected_data = {
            "youtube": {
                "latest": latest_data,
                "popular_weekly": popular_data
            }
        }
        
        output_file = "trends_output.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(collected_data, f, ensure_ascii=False, indent=2)
            
        md_output_file = "video_list.md"
        with open(md_output_file, "w", encoding="utf-8") as f:
            f.write("# Wuthering Waves Collected Videos\n\n")
            
            def write_section(title, data_dict):
                f.write(f"## {title}\n\n")
                for query, videos in data_dict.items():
                    if isinstance(videos, list) and videos:
                        f.write(f"### Keyword: {query}\n\n")
                        f.write("| Thumbnail | Title & Link | Channel |\n")
                        f.write("| :---: | :--- | :--- |\n")
                        for video in videos:
                            thumb_md = f"![Thumbnail]({video['thumbnail']})" if video['thumbnail'] else "No Image"
                            display_title = video['title']
                            if video['title'] != video['original_title']:
                                display_title += f"<br>*(Orig: {video['original_title']})*"
                            title_md = f"[{display_title}]({video['url']})"
                            f.write(f"| {thumb_md} | {title_md} | {video['channel']} |\n")
                        f.write("\n")
                        
            write_section("🔥 Popular Trends in Past 7 Days", popular_data)
            write_section("🆕 Latest Trends", latest_data)
                    
        print(f"\nDone. Results have been saved to {output_file} and {md_output_file}")
        
        print("\n[3] Uploading to Notion Database...")
        logger.log("📤 [ステップ3] Notionデータベースへの差分・新規アップロード検証を開始...")
        target_channel_videos = []
        if "★Target Channels" in latest_data:
            target_channel_videos = latest_data.pop("★Target Channels")

        latest_flat = get_flat_video_list(latest_data)
        popular_flat = get_flat_video_list(popular_data)
        
        notion_api_key = os.getenv("NOTION_API_KEY")
        database_id = os.getenv("NOTION_DATABASE_ID")
        if notion_api_key and notion_api_key != "your_notion_api_key_here" and database_id and database_id != "your_notion_database_id_here":
            headers = {
                "Authorization": f"Bearer {notion_api_key}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28"
            }
            existing_urls = get_existing_notion_urls(headers, database_id)
            
            send_to_notion([v for v in popular_flat if v.get("video_type") == "Shorts"], "週間人気 (Shorts)", existing_urls)
            send_to_notion([v for v in popular_flat if v.get("video_type") == "通常"], "週間人気 (通常)", existing_urls)
            send_to_notion([v for v in latest_flat if v.get("video_type") == "Shorts"], "最新 (Shorts)", existing_urls)
            send_to_notion([v for v in latest_flat if v.get("video_type") == "通常"], "最新 (通常)", existing_urls)
            
            if target_channel_videos:
                target_flat = get_flat_video_list({"dummy": target_channel_videos})
                send_to_notion(target_flat, "登録チャンネル", existing_urls)
        else:
            print("Notion API is not configured. Skipping upload.")
            logger.log("ℹ️ Notion設定不備のためアップロードスキップ")
        
        logger.log(f"✅ 全プロセスの収集＆同期が安全に完了しました！ (今回追加: {logger.log_data['new_items_count']} 件)")
        logger.set_summary(f"正常完了 (新着Notion追加: {logger.log_data['new_items_count']} 件)")
        logger.save_to_json()
        
    except Exception as e:
        err_detail = str(e)
        print(f"\n[CRITICAL ERROR] {err_detail}")
        logger.log(f"💥 致命的エラー発生により中断: {err_detail}")
        logger.set_summary("異常終了 (エラー検出)", is_error=True)
        logger.save_to_json()
        
        # ⚠️ エラーが出た場合のみ、Discordへ直接SOS警告アラートを送信！！
        alert_msg = f"⚠️ **【YouTubeトレンド収集 エラー検知】** ⚠️\n自動巡回プロセス中に致命的なエラーまたは例外を検出しました。\n\n**詳細:** `{err_detail}`\nスタジオ活動実績ログまたは GitHub Actions コンソールをご確認ください。"
        send_to_discord(alert_msg)
        raise e

if __name__ == "__main__":
    main()
