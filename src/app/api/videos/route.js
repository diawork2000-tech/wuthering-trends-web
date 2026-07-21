import { NextResponse } from 'next/server';

export async function GET() {
  const notionApiKey = process.env.NOTION_API_KEY;
  const databaseId = process.env.NOTION_DATABASE_ID;

  if (!databaseId || !notionApiKey) {
    return NextResponse.json({ error: 'Database ID or API Key is not defined' }, { status: 500 });
  }

  try {
    let allResults = [];
    let hasMore = true;
    let nextCursor = undefined;
    
    // 最大5ページ (500件) まで取得する
    while (hasMore && allResults.length < 500) {
      const body = {
        sorts: [
          {
            timestamp: 'created_time',
            direction: 'descending',
          },
        ],
        page_size: 100,
      };
      
      if (nextCursor) {
        body.start_cursor = nextCursor;
      }

      const response = await fetch(`https://api.notion.com/v1/databases/${databaseId}/query`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${notionApiKey}`,
          'Content-Type': 'application/json',
          'Notion-Version': '2022-06-28'
        },
        body: JSON.stringify(body),
        cache: 'no-store'
      });

      if (!response.ok) {
        const errText = await response.text();
        throw new Error(`Notion API Error: ${response.status} ${errText}`);
      }

      const data = await response.json();
      allResults = allResults.concat(data.results);
      
      hasMore = data.has_more;
      nextCursor = data.next_cursor;
    }

    const videos = allResults.map((page) => {
      const titleProp = page.properties['タイトル'];
      const urlProp = page.properties['URL'];
      const channelProp = page.properties['チャンネル'];
      const categoryProp = page.properties['カテゴリ'];

      const title = titleProp?.title?.[0]?.plain_text || 'No Title';
      const url = urlProp?.url || '';
      const channel = channelProp?.rich_text?.[0]?.plain_text || 'Unknown Channel';
      const category = categoryProp?.select?.name || '';
      
      const thumbnail = page.cover?.external?.url || 'https://via.placeholder.com/640x360.png?text=No+Image';

      let videoId = '';
      if (url) {
        try {
          const urlObj = new URL(url);
          videoId = urlObj.searchParams.get('v') || '';
        } catch (e) {
          // invalid url
        }
      }

      return {
        id: page.id,
        title,
        url,
        videoId,
        channel,
        category,
        thumbnail,
        created_time: page.created_time,
      };
    });

    return NextResponse.json({ videos });
  } catch (error) {
    console.error('Error fetching videos from Notion:', error);
    return NextResponse.json({ error: error.message || 'Unknown error occurred in API' }, { status: 500 });
  }
}
