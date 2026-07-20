import os
import json
import traceback
import re
import requests
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from dotenv import load_dotenv
from deep_translator import GoogleTranslator

# Load environment variables
load_dotenv()

CONFIG_FILE = "config.json"
def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: {CONFIG_FILE} not found. Using default settings.")
        return {
            "youtube": {"search_queries": ["鳴潮", "Wuthering Waves"], "max_results_per_query": 50, "region_code": "JP"}
        }
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def is_japanese(text):
    """テキストに日本語（ひらがな、カタカナ、漢字）が含まれているか簡易判定"""
    return bool(re.search(r'[ぁ-んァ-ヶ亜-熙]', text))

def translate_if_needed(text):
    """日本語が含まれていなければGoogle翻訳で日本語に変換する"""
    if not text or is_japanese(text):
        return text
    try:
        return GoogleTranslator(source='auto', target='ja').translate(text)
    except Exception:
        return text

def fetch_youtube_api(youtube, query, max_results, region_code, order="date", published_after=None, video_duration="short"):
    """YouTube APIの実行（ページネーションなしの簡易版）"""
    if max_results <= 0:
        return []
        
    kwargs = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": order,
        "maxResults": max_results,
        "regionCode": region_code,
        "videoDuration": video_duration
    }
    if published_after:
        kwargs["publishedAfter"] = published_after

    try:
        request = youtube.search().list(**kwargs)
        response = request.execute()
        return response.get("items", [])
    except Exception as e:
        print(f"  [Error] Failed to search '{query}' (duration={video_duration}): {str(e)}")
        return []

def fetch_channel_latest_videos(youtube, channel_id, max_results=10):
    """チャンネルのアップロード済みプレイリストから最新動画を取得 (1トークン消費)"""
    if not channel_id.startswith("UC"):
        return []
    
    # アップロードプレイリストIDは、チャンネルIDの先頭の 'UC' を 'UU' に変えたもの
    playlist_id = "UU" + channel_id[2:]
    
    try:
        request = youtube.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=max_results
        )
        response = request.execute()
        
        # プレイリストアイテムを検索APIのアイテムフォーマットに似せて変換する
        items = []
        for pl_item in response.get("items", []):
            snippet = pl_item.get("snippet", {})
            # resourceId.videoId に動画IDが入っている
            video_id = snippet.get("resourceId", {}).get("videoId")
            if video_id:
                # 検索APIと構造を合わせる
                items.append({
                    "id": {"videoId": video_id},
                    "snippet": snippet
                })
        return items
    except Exception as e:
        print(f"  [Error] Failed to fetch channel {channel_id}: {str(e)}")
        return []

def get_youtube_trends(config, mode="latest"):
    """Fetch videos based on mode ('latest' or 'popular_weekly')"""
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key or api_key == "your_youtube_api_key_here":
        return {"error": "YouTube API Key is not set."}
    
    youtube = build("youtube", "v3", developerKey=api_key)
    results = {}
    
    yt_config = config.get("youtube", {})
    queries = yt_config.get("search_queries", ["鳴潮"])
    max_results = yt_config.get("max_results_per_query", 50)
    region_code = yt_config.get("region_code", "JP")
    
    # 85%をShorts、15%を通常動画（medium）に割り当てる
    shorts_limit = int(max_results * 0.85)
    long_limit = max_results - shorts_limit

    # popular_weekly モードの場合は1週間前の日時を設定
    published_after = None
    order = "date"
    if mode == "popular_weekly":
        order = "viewCount"
        one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        published_after = one_week_ago.isoformat()

    for query in queries:
        print(f"  - Searching YouTube for: '{query}' (Mode: {mode})")
        # Shortsの取得
        shorts_items = fetch_youtube_api(youtube, query, shorts_limit, region_code, order, published_after, "short")
        # 長編・通常動画の取得 (4分〜20分を想定して medium を指定)
        long_items = fetch_youtube_api(youtube, query, long_limit, region_code, order, published_after, "medium")
        
        videos = []
        # Shortsの処理
        for item in shorts_items:
            snippet = item.get("snippet", {})
            if snippet.get("liveBroadcastContent") != "none": continue
            videos.append({
                "title": translate_if_needed(snippet.get("title", "")),
                "original_title": snippet.get("title", ""),
                "channel": snippet.get("channelTitle", ""),
                "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                "video_type": "Shorts"
            })
            
        # 通常動画の処理
        for item in long_items:
            snippet = item.get("snippet", {})
            if snippet.get("liveBroadcastContent") != "none": continue
            videos.append({
                "title": translate_if_needed(snippet.get("title", "")),
                "original_title": snippet.get("title", ""),
                "channel": snippet.get("channelTitle", ""),
                "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                "video_type": "通常"
            })
            
        results[query] = videos

    # 特定チャンネルの動画を確実に追加する
    target_channels = yt_config.get("target_channels", [])
    if target_channels and mode == "latest":
        print("\n  - Fetching latest videos from targeted channels...")
        channel_videos = []
        for ch_id in target_channels:
            print(f"    - Fetching channel: {ch_id}")
            ch_items = fetch_channel_latest_videos(youtube, ch_id, max_results=5)
            for item in ch_items:
                snippet = item.get("snippet", {})
                
                # タイトルにShortsなどと入っている簡易判定（完全ではない）
                title = snippet.get("title", "")
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
            res = requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload)
            if res.status_code == 200:
                success_count += 1
                existing_urls.add(video["url"]) # 今回追加した分もセットに入れておく
            else:
                print(f"  [Error] Failed to upload to Notion: {res.text}")
        except Exception as e:
            print(f"  [Error] Communication with Notion failed: {str(e)}")
            
        time.sleep(0.35) # Rate limit avoidance (Max 3 req/sec)
        
    print(f"Category '{category}': Uploaded {success_count} new items. Skipped {skip_count} existing items.")

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
    
    # 起動時のDiscord通知
    send_to_discord("🚀 **[情報収集開始]** 鳴潮トレンド収集ツールの自動実行がスタートしました！\n数分後に完了結果をお知らせします。")
    
    config = load_config()
    
    print("\n[1] Fetching LATEST YouTube trends (85% Shorts, 15% Normal)...")
    latest_data = get_youtube_trends(config, mode="latest")
    
    print("\n[2] Fetching POPULAR YouTube trends from past 7 days (85% Shorts, 15% Normal)...")
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
    # Notionへ通知（フラットなリストに変換してカテゴリを付与）
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
        
        # 週間人気のShortsと通常を分けて登録
        send_to_notion([v for v in popular_flat if v.get("video_type") == "Shorts"], "週間人気 (Shorts)", existing_urls)
        send_to_notion([v for v in popular_flat if v.get("video_type") == "通常"], "週間人気 (通常)", existing_urls)
        
        # 最新のShortsと通常を分けて登録
        send_to_notion([v for v in latest_flat if v.get("video_type") == "Shorts"], "最新 (Shorts)", existing_urls)
        send_to_notion([v for v in latest_flat if v.get("video_type") == "通常"], "最新 (通常)", existing_urls)
    else:
        print("Notion API is not configured. Skipping upload.")
    
    # Discordへ通知 (任意)
    completion_msg = "**✅ [鳴潮トレンド収集完了]**\n本日の最新動画一覧と人気ランキングの収集が完了しました！添付のMarkdownファイルをご確認ください。\n※Notionアプリのギャラリービューからサムネイル付きで綺麗にご覧いただけます！"
    send_to_discord(completion_msg, md_output_file)

if __name__ == "__main__":
    main()
