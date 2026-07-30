import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function GET() {
  const NOTION_API_KEY = process.env.NOTION_API_KEY;
  const NOTION_INTELLIGENCE_DB_ID = process.env.NOTION_INTELLIGENCE_DB_ID;

  if (!NOTION_API_KEY || !NOTION_INTELLIGENCE_DB_ID) {
    return NextResponse.json(
      { error: 'Notion API credentials are not set in environment.' },
      { status: 500 }
    );
  }

  const url = `https://api.notion.com/v1/databases/${NOTION_INTELLIGENCE_DB_ID}/query`;

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${NOTION_API_KEY}`,
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
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
      next: { revalidate: 60 } // 最短60秒キャッシュで超高速化＆最新キープ
    });

    if (!res.ok) {
      const errorText = await res.text();
      return NextResponse.json(
        { error: 'Failed to fetch topics from Notion', details: errorText },
        { status: res.status }
      );
    }

    const data = await res.json();
    const items = data.results.map((page) => {
      const props = page.properties || {};
      
      // タイトル（見出し）プロパティを取得
      let title = "無題のトピック";
      for (const key in props) {
        if (props[key].type === "title" && props[key].title?.length > 0) {
          title = props[key].title.map(t => t.plain_text).join('');
          break;
        }
      }

      // 各カスタムプロパティを抽出
      const sourceType = props["メディアソース"]?.select?.name || "外部情報ソース";
      const sourceUrl = props["一次URL"]?.url || "";
      const scriptOutline = props["ショート台本骨格"]?.rich_text?.map(r => r.plain_text).join('') || "構成台本準備中";
      const reason = props["合致根拠と期待値"]?.rich_text?.map(r => r.plain_text).join('') || "ホットトピック自動選出";
      const dateStr = props["日時"]?.date?.start || page.created_time?.substring(0, 10) || "";

      return {
        id: page.id,
        title,
        sourceType,
        sourceUrl,
        scriptOutline,
        reason,
        date: dateStr,
        createdTime: page.created_time
      };
    });

    return NextResponse.json({ success: true, items });
  } catch (error) {
    console.error('Error fetching intelligence items:', error);
    return NextResponse.json(
      { error: 'Internal server error while retrieving intelligence data.' },
      { status: 500 }
    );
  }
}
