import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

function getFallbackData() {
  try {
    const filePath = path.join(process.cwd(), 'src/data/intelligence_cache.json');
    if (fs.existsSync(filePath)) {
      const raw = fs.readFileSync(filePath, 'utf-8');
      return JSON.parse(raw);
    }
  } catch (e) {
    console.error('Failed to read backup cache:', e);
  }
  return {
    success: true,
    items: [
      {
        id: "item-init",
        title: "【初期データ】鳴潮ショート動画 AI自動採掘スタンバイ",
        sourceType: "システム通知",
        sourceUrl: "https://wutheringwaves.kurogames.com/jp/",
        scriptOutline: "【冒頭3秒】：『鳴潮の最新トレンド情報を見逃してない？！』➔ 最強ビルドとイベント攻略をAIが毎日500件発掘 ➔ まとめ：次回更新をお楽しみに！",
        reason: "クラウドとの環境連携中、または初期同期状態です。20分後のクロール更新便にて新しいカードが充当されます！",
        date: "2026-07-30",
        createdTime: "2026-07-30T12:00:00.000Z"
      }
    ]
  };
}

export async function GET() {
  const NOTION_API_KEY = process.env.NOTION_API_KEY;
  // Vercel 側の環境変数が未設定・古いままでも動くよう、実運用中の DB ID をフォールバックとして残す。
  // DB を作り直したときは環境変数を入れ替えるだけで済み、再デプロイは不要。
  const NOTION_INTELLIGENCE_DB_ID =
    process.env.NOTION_INTELLIGENCE_DB_ID || '3ad82a7701b08067bf5de4694df49d9b';

  if (!NOTION_API_KEY) {
    console.log('[Notice] NOTION_API_KEY not found in server env. Using local intelligent cache seamlessly.');
    return NextResponse.json(getFallbackData());
  }

  const url = `https://api.notion.com/v1/databases/${NOTION_INTELLIGENCE_DB_ID}/query`;

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${NOTION_API_KEY}`,
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
        'Cache-Control': 'no-cache, no-store, max-age=0, must-revalidate',
      },
      body: JSON.stringify({
        page_size: 100,
        sorts: [
          {
            timestamp: 'created_time',
            direction: 'descending'
          }
        ]
      }),
      cache: 'no-store'
    });

    if (!res.ok) {
      console.warn('Notion API query failed, falling back to local cached rack.', await res.text());
      return NextResponse.json(getFallbackData());
    }

    const data = await res.json();
    const items = data.results.map((page) => {
      const props = page.properties || {};
      
      let title = "無題のトピック";
      for (const key in props) {
        if (props[key].type === "title" && props[key].title?.length > 0) {
          title = props[key].title.map(t => t.plain_text).join('');
          break;
        }
      }

      const sourceType = props["メディアソース"]?.select?.name || "外部バズソース";
      const sourceUrl = props["一次URL"]?.url || "";
      const scriptOutline = props["ショート台本骨格"]?.rich_text?.map(r => r.plain_text).join('') || "台本構成の準備中";
      const reason = props["合致根拠と期待値"]?.rich_text?.map(r => r.plain_text).join('') || "ホットトピック自動選抜";
      const dateStr = props["日時"]?.date?.start || page.created_time?.substring(0, 10) || "2026-07-30";
      const adopted = props["採用"]?.checkbox || false;
      const score = props["スコア"]?.number ?? 60;
      const viewCount = props["再生数"]?.number ?? 0;
      const viewsPerHour = props["伸び速度"]?.number ?? 0;
      const mentionCount = props["言及ソース数"]?.number ?? 1;
      const status = props["制作状況"]?.select?.name || '未着手';

      return {
        id: page.id,
        title,
        sourceType,
        sourceUrl,
        scriptOutline,
        reason,
        adopted,
        score,
        viewCount,
        viewsPerHour,
        mentionCount,
        status,
        date: dateStr,
        createdTime: page.created_time
      };
    });

    // ★新・極上のUXハック：メディア多様性ラウンドロビン・シャッフル (Alternating Sort)
    // 「YouTube競合」の連続投入等によってブラウザ上部の表示が偏るのを完全に防ぐため
    // 各プラットフォーム(Reddit/YouTube/攻略・SNS)の記事を1枚ずつ交互に美しく織り交ぜて配置する！
    const groups = { reddit: [], youtube: [], other: [] };
    items.forEach(item => {
      const st = String(item.sourceType || '').toLowerCase();
      const su = String(item.sourceUrl || '').toLowerCase();
      if (st.includes('reddit') || su.includes('reddit')) {
        groups.reddit.push(item);
      } else if (st.includes('youtube') || su.includes('youtube') || su.includes('youtu.be')) {
        groups.youtube.push(item);
      } else {
        groups.other.push(item);
      }
    });

    const alternatedItems = [];
    const maxLen = Math.max(groups.reddit.length, groups.youtube.length, groups.other.length);
    for (let i = 0; i < maxLen; i++) {
      if (groups.reddit[i]) alternatedItems.push(groups.reddit[i]);
      if (groups.other[i]) alternatedItems.push(groups.other[i]);
      if (groups.youtube[i]) alternatedItems.push(groups.youtube[i]);
    }

    return NextResponse.json({ success: true, items: alternatedItems.length > 0 ? alternatedItems : getFallbackData().items });
  } catch (error) {
    console.error('Error fetching intelligence items, switching to failsafe cache:', error);
    return NextResponse.json(getFallbackData());
  }
}
