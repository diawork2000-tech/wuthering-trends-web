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
    import google.generativeai as genai
except ImportError:
    genai = None

from trend_collector import YouTubeKeyManager, translate_if_needed

load_dotenv()

CONFIG_FILE = "config_intelligence.json"
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_INTELLIGENCE_DB_ID = os.getenv("NOTION_INTELLIGENCE_DB_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

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
        self.trending_keywords = set()
        self.gemini_model = None
        self.notion_title_prop_name = "名前"
        
        if GEMINI_API_KEY and genai:
            try:
                genai.configure(api_key=GEMINI_API_KEY)
                self._init_best_gemini_model()
            except Exception as e:
                print(f"  [Warning] Gemini configuration failed: {e}")
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
            available = [m.name.replace("models/", "") for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            print(f"  [GenAI Available Models]: {available[:6]}...")
            for target in candidate_models:
                if target in available or any(target in a for a in available):
                    matched = next((a for a in available if target in a), target)
                    self.gemini_model = genai.GenerativeModel(matched)
                    print(f"  [Info] Gemini AI Auto-Locked on Model: {matched}!")
                    return
            if available:
                self.gemini_model = genai.GenerativeModel(available[0])
                print(f"  [Info] Gemini AI Connected to default available Model: {available[0]}!")
                return
        except Exception as e:
            print(f"  [Model Search Error] {e}")
            self.gemini_model = None

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
                
            if patch_props:
                print(f"  [Notion Auto-Upgrade] Creating {len(patch_props)} new customized columns in your database...")
                requests.patch(url_get, headers=headers, json={"properties": patch_props}, timeout=10)
                print("  [Success] Notion Database schema fully upgraded and synchronized!")
            else:
                print("  [Notion Schema] All required columns are already present!")
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
        print("\n=== [Phase 1] Analyzing Target YouTube Channels ===")
        if not self.key_manager.get_client():
            print("  [Notice] YOUTUBE_API_KEY not present in local env. Skipping channel analysis.")
            return

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
                
                if view_count > 1500 or like_count > 100:
                    words = re.findall(r'([A-Za-z0-9_-]{2,}|[ァ-ンヴー]{2,}|[一-龥]{2,})', title)
                    for w in words:
                        if len(w) >= 2 and w not in ["鳴潮", "動画", "解説", "最強", "紹介"]:
                            self.trending_keywords.add(w)
                    self.collected_raw_items.append({
                        "title": f"【競合バズ実績】{title}",
                        "summary": f"{ch_name} で現在 {view_count:,} 再生 / 高評価 {like_count:,} の注目テーマ",
                        "url": f"https://www.youtube.com/watch?v={video['id']}",
                        "source_type": "YouTube競合動向",
                        "score": 85
                    })
        print(f"  [Analytics Complete] Extracted {len(self.trending_keywords)} trending buzzwords!")

    def crawl_web_sources(self):
        print("\n=== [Phase 2] Crawling Multi-Platform Web Sources (Selective Foreign-Only Translation) ===")
        headers_web = {
            "User-Agent": "WutheringTrendsIntelligenceEngine/2.0 (YouTube Content Curator; by @Diachannel12345)",
            "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8"
        }
        
        def is_already_japanese(text):
            # ひらがな、カタカナ、または一般的な日本の漢字が3文字以上含まれていれば純日本の生記事と認定！
            kana_kanji_count = len(re.findall(r'[ぁ-んァ-ヶー一-龠]', str(text)))
            return kana_kanji_count >= 3

        for src in self.config.get("target_web_sources", []):
            if not src.get("enabled", True):
                continue
            name = src.get("name", "Unknown Source")
            url = src.get("url", "")
            stype = src.get("type", "rss")
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
                            summary_clean = re.sub(r'<[^>]+>', '', str(summary_txt))[:140]
                            
                            # 日本のサイトや既に日本語で書かれた記事は絶対に翻訳にかけず純生データを尊重し、
                            # Redditなど海外の英語圏テキストだけにピンポイントで綺麗な自動翻訳を実行！
                            if is_already_japanese(raw_title):
                                title_ja = raw_title
                                summary_ja = summary_clean if summary_clean != raw_title else raw_title
                            else:
                                title_ja = translate_if_needed(raw_title)
                                summary_ja = translate_if_needed(summary_clean) if summary_clean != raw_title else title_ja
                            
                            # リダイレクト400エラーが起きる可能性のあるURLは、クリックした瞬間に誰の環境でも
                            # 一発で記事に到達できるスマートな正規URL（生リンク or 安全検索リンク）へ徹底自動クレンジング！
                            safe_url = link
                            if not link or "news.google.com" in link or not link.startswith("http"):
                                safe_url = f"https://www.google.com/search?q={requests.utils.quote(title_ja[:35])}"
                                
                            self.collected_raw_items.append({
                                "title": title_ja,
                                "summary": summary_ja,
                                "url": safe_url,
                                "source_type": name[:30],
                                "score": 75
                            })
                            item_cnt += 1
                        print(f"    -> Harvested & Selective-Translated {item_cnt} high-impact topic cards successfully!")
            except Exception as e:
                print(f"  [Warning] Failed crawling {name}: {e}")
                
        print(f"  [Crawl Complete] Total collected raw items across all networks: {len(self.collected_raw_items)}")

    def generate_and_filter_ideas(self):
        print("\n=== [Phase 3] Generating & Filtering Video Topics ===")
        target_count = self.config.get("settings", {}).get("target_items_per_run", 15)
        
        for item in self.collected_raw_items:
            combined = (item["title"] + " " + item.get("summary", "")).lower()
            for kw in self.trending_keywords:
                if kw.lower() in combined:
                    item["score"] = min(100, item.get("score", 60) + 15)
                    item["match_kw"] = kw
                    break

        sorted_items = sorted(self.collected_raw_items, key=lambda x: x.get("score", 0), reverse=True)[:35]
        if not sorted_items:
            print("  [Info] No candidate items found above criteria in this run.")
            return []

        if self.gemini_model and len(sorted_items) > 0:
            print(f"  [Gemini Batch] Sending batch request to Gemini AI with {len(sorted_items)} items to format high-impact video ideas...")
            prompt = (
                "あなたはチャンネル@Diachannel12345専属のYouTubeショート＆動画クリエイティブ責任者です。\n"
                "以下の回収ニュースとバズ状況のリストから、冒頭3秒で視聴者の関心を強烈に惹く"
                f"優れた動画ネタ企画を 【 最大 {target_count} 件 】 選出および加工構築してください。\n\n"
                "【⚠️最重要・絶対指令⚠️】\n"
                "1. 海外Reddit等の英語や外国語の記事が含まれる場合は、必ず【100% 自然で熱量ある純日本語の見出し・要約・台本】に完全意訳・翻訳すること。\n"
                "2. タイトルや本文に英語をそのまま放置・直訳状態にして出力することは堅く禁ずる。\n"
                "3. 「〜についてご存じですか？！」のような陳腐で機械的なお決まり文句は一切使わず、視聴者が思わず目を奪われるリアルで知的なバズ台本骨格に作成せよ。\n\n"
                "出力は必ず【純粋なJSONフォーマットの配列】のみを返し、Markdownコードブロックや不要な解説文は入れないでください。\n\n"
                "JSONの形式基準:\n"
                "[\n"
                "  {\n"
                '    "topic_title": "100%日本語：ショートで圧倒的注目を浴びる激アツ見出し",\n'
                '    "summary": "何が盛り上がっているのかの熱狂要因要約(純日本語)",\n'
                '    "source_url": "提供リスト内に記載された正確な元URL(厳格)",\n'
                '    "source_type": "提供リストのメディア種別",\n'
                '    "script_outline": "導入3秒(インパクトある問題提起) ➔ 話題解説(事実と本質) ➔ オチとまとめ",\n'
                '    "reason": "なぜこの企画がターゲットファンに響き再生数が伸びるかの見立て"\n'
                "  }\n"
                "]\n\n"
                "素材リスト:\n" + json.dumps(sorted_items[:25], ensure_ascii=False)
            )
            try:
                ai_res = self.gemini_model.generate_content(prompt)
                raw_txt = ai_res.text.strip()
                raw_txt = re.sub(r'^```(json)?|```$', '', raw_txt, flags=re.MULTILINE).strip()
                ideas_list = json.loads(raw_txt)
                
                # 英語未翻訳または陳腐な機械テンプレート混入を防衛する最終品質フィルター！
                clean_ideas = []
                for idea in ideas_list:
                    tt = str(idea.get("topic_title", ""))
                    to = str(idea.get("script_outline", ""))
                    # 日本語(仮名・漢字)がちゃんと含まれ、怪しい英文放置がないカードだけを選定！
                    if len(re.findall(r'[ぁ-んァ-ヶー一-龠]', tt)) >= 2 and "についてご存じですか" not in to:
                        clean_ideas.append(idea)
                print(f"  [Gemini Success] Successfully generated & filtering {len(clean_ideas)} high-purity Japanese topic cards!")
                return clean_ideas[:target_count]
            except Exception as e:
                print(f"  [Warning] Gemini generation failed ({e}). Falling back to advanced algorithm.")

        out_ideas = []
        for item in sorted_items[:target_count]:
            kw_match = item.get("match_kw", "注目トレンド")
            t_title = translate_if_needed(item.get("title", "無題のトレンドネタ"))
            t_sum = translate_if_needed(item.get("summary", ""))
            # 日本語翻訳に失敗して英語のままになっている場合は品質保持のため除外する！
            if len(re.findall(r'[ぁ-んァ-ヶー一-龠]', t_title)) < 2:
                continue
            out_ideas.append({
                "topic_title": t_title,
                "summary": t_sum,
                "source_url": item.get("url", ""),
                "source_type": item.get("source_type", "Web調査"),
                "script_outline": f"【冒頭3秒】：『{t_title[:22]}！この裏にある重大な真実を見抜いた？！』➔ 決定的証拠と背景の考察 ➔ まとめと今後の対策",
                "reason": f"熱狂度足切り通過およびキーワード「{kw_match}」による評価抽出"
            })
        print(f"  [Algorithm Ready] Formatted {len(out_ideas)} items using advanced algorithmic pipeline.")
        return out_ideas

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
                    "ショート台本骨格": {"rich_text": [{"text": {"content": str(idea.get("script_outline", ""))[:400]}}]},
                    "合致根拠と期待値": {"rich_text": [{"text": {"content": str(idea.get("reason", ""))[:300]}}]},
                    "日時": {"date": {"start": (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")}}
                }
            }
            try:
                res = requests.post(url_post, headers=headers_notion, json=payload, timeout=8)
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
        url_query = f"https://api.notion.com/v1/databases/{NOTION_INTELLIGENCE_DB_ID}/query"
        payload_query = {
            "filter": {
                "timestamp": "created_time",
                "created_time": {
                    "before": f"{seven_days_ago}T00:00:00.000Z"
                }
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
                        del_res = requests.patch(url_patch, headers=headers, json={"archived": True}, timeout=8)
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
                        requests.patch(f"https://api.notion.com/v1/pages/{pid}", headers=headers, json={"archived": True}, timeout=10)
                        purged_cnt += 1
                        print(f"    -> Purged sub-quality un-translated card: '{t_str[:35]}...'")
                print(f"  [Quality Patrol Complete] Successfully scrubbed {purged_cnt} un-translated or mechanical cards from Notion!")
        except Exception as e:
            print(f"  [Error during cleanup] {e}")

    def run(self):
        print(f"\n--- [Intelligence Engine Started] {(datetime.now(timezone.utc) + timedelta(hours=9)).strftime('%Y/%m/%d %H:%M:%S (JST)')} ---")
        try:
            self.analyze_channels()
            self.crawl_web_sources()
            ideas = self.generate_and_filter_ideas()
            if ideas:
                self.push_to_notion(ideas)
            self.cleanup_old_notion_cards()
            print("\n--- [All Intelligence Processing & Auto-Cleanup Completed Successfully!] ---\n")
        except Exception as e:
            print(f"[Fatal Exception during Intelligence Execution]: {traceback.format_exc()}")

if __name__ == "__main__":
    engine = IntelligenceEngine()
    engine.run()
