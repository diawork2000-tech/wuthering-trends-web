import { Client } from '@notionhq/client';
import { NextResponse } from 'next/server';

const notion = new Client({ auth: process.env.NOTION_API_KEY });
const databaseId = process.env.NOTION_DATABASE_ID;

export async function GET() {
  if (!databaseId) {
    return NextResponse.json({ error: 'Database ID is not defined' }, { status: 500 });
  }

  try {
    const response = await notion.databases.query({
      database_id: databaseId,
      sorts: [
        {
          timestamp: 'created_time',
          direction: 'descending',
        },
      ],
      page_size: 100, // 最新の100件を取得
    });

    const videos = response.results.map((page) => {
      // データの安全な抽出
      const titleProp = page.properties['タイトル'];
      const urlProp = page.properties['URL'];
      const channelProp = page.properties['チャンネル'];
      const categoryProp = page.properties['カテゴリ'];

      const title = titleProp?.title?.[0]?.plain_text || 'No Title';
      const url = urlProp?.url || '';
      const channel = channelProp?.rich_text?.[0]?.plain_text || 'Unknown Channel';
      const category = categoryProp?.select?.name || '';
      
      // サムネイル画像（カバー画像）
      const thumbnail = page.cover?.external?.url || 'https://via.placeholder.com/640x360.png?text=No+Image';

      // YouTubeのVideo IDを抽出
      let videoId = '';
      if (url) {
        const urlObj = new URL(url);
        videoId = urlObj.searchParams.get('v') || '';
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
    return NextResponse.json({ error: 'Failed to fetch videos' }, { status: 500 });
  }
}
