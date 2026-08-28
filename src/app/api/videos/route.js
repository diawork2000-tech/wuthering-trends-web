import { NextResponse } from 'next/server';

export async function GET(request) {
  const notionApiKey = process.env.NOTION_API_KEY;
  const databaseId = process.env.NOTION_DATABASE_ID;

  if (!databaseId || !notionApiKey) {
    return NextResponse.json({ error: 'Database ID or API Key is not defined' }, { status: 500 });
  }

  // 広告だけは別枠で引く。通常の一覧は新しい順に500件で打ち切るため、
  // 広告をまとめて取り込んだ日に古い広告が全部その枠から押し出される。
  // 出稿期間が入っている行だけを対象にすれば、件数に関係なく全部揃う。
  const params = new URL(request.url).searchParams;
  const adsOnly = params.get('ads') === '1';
  // 公式SNSも広告と同じ理由で別枠。毎時14アカウント分が積み上がるため、
  // 通常の500件枠に入れると数日で他のカテゴリを押し出してしまう。
  const snsOnly = params.get('sns') === '1';
  const maxItems = adsOnly || snsOnly ? 2000 : 500;

  try {
    let allResults = [];
    let hasMore = true;
    let nextCursor = undefined;

    while (hasMore && allResults.length < maxItems) {
      const body = {
        sorts: [
          {
            timestamp: 'created_time',
            direction: 'descending',
          },
        ],
        page_size: 100,
      };

      if (adsOnly) {
        body.filter = { property: '出稿期間', rich_text: { is_not_empty: true } };
      } else if (snsOnly) {
        body.filter = { property: 'カテゴリ', select: { equals: 'SNS' } };
      }

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
      const viewCount = page.properties['再生数']?.number ?? null;
      const likeCount = page.properties['高評価数']?.number ?? null;
      // ピックアップの状態。列がまだ無いDBでも undefined になるだけで壊れない。
      const adopted = page.properties['採用']?.checkbox || false;
      // 広告として実際に配信されていた期間。広告以外は空になる。
      const adPeriod = page.properties['出稿期間']?.rich_text?.[0]?.plain_text || '';
      const status = page.properties['制作状況']?.select?.name || '未着手';
      // 公式SNSの投稿だけが持つ。どこから来た情報かを行単位で示すために使う。
      const platform = page.properties['媒体']?.select?.name || '';
      const lang = page.properties['言語']?.select?.name || '';
      const account = page.properties['アカウント']?.rich_text?.[0]?.plain_text || '';
      // 収集日ではなく、実際に投稿された日時。並べ替えの基準になる。
      const postedAt = page.properties['投稿日時']?.date?.start || '';
      // 翻訳前の原文。訳が怪しいときに元を確かめられるようにする。
      const originalTitle = page.properties['原文']?.rich_text?.[0]?.plain_text || '';
      // 動画付き投稿のMP4。カード上でそのまま再生する。
      const postVideoUrl = page.properties['動画URL']?.rich_text?.[0]?.plain_text || '';
      
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
        viewCount,
        likeCount,
        adopted,
        status,
        adPeriod,
        platform,
        lang,
        account,
        postedAt,
        originalTitle,
        postVideoUrl,
        created_time: page.created_time,
      };
    });

    return NextResponse.json({ videos });
  } catch (error) {
    console.error('Error fetching videos from Notion:', error);
    return NextResponse.json({ error: error.message || 'Unknown error occurred in API' }, { status: 500 });
  }
}
