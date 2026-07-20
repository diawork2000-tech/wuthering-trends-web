import { NextResponse } from 'next/server';

export async function GET() {
  const notionApiKey = process.env.NOTION_API_KEY;
  const channelsDbId = process.env.NOTION_CHANNELS_DB_ID;

  if (!notionApiKey || !channelsDbId) {
    return NextResponse.json({ error: 'Notion Configuration Missing' }, { status: 500 });
  }

  try {
    const response = await fetch(`https://api.notion.com/v1/databases/${channelsDbId}/query`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${notionApiKey}`,
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28'
      },
      body: JSON.stringify({}),
      cache: 'no-store'
    });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`Notion API Error: ${response.status} ${errText}`);
    }

    const data = await response.json();
    const channels = data.results.map((page) => {
      // ユーザーの作成したプロパティ名に依存しないように取得
      // 「名前」や「Name」のようなタイトルプロパティを探す
      let nameProp = '';
      for (const key in page.properties) {
        if (page.properties[key].type === 'title') {
          nameProp = page.properties[key].title?.[0]?.plain_text || '';
        }
      }
      
      const idProp = page.properties['チャンネルID']?.rich_text?.[0]?.plain_text || '';
      
      return {
        id: page.id,
        name: nameProp || 'No Name',
        channelId: idProp
      };
    });

    return NextResponse.json({ channels });
  } catch (error) {
    console.error('Error fetching channels:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

export async function POST(request) {
  const notionApiKey = process.env.NOTION_API_KEY;
  const channelsDbId = process.env.NOTION_CHANNELS_DB_ID;

  if (!notionApiKey || !channelsDbId) {
    return NextResponse.json({ error: 'Notion Configuration Missing' }, { status: 500 });
  }

  try {
    const { name, channelId } = await request.json();

    if (!name || !channelId) {
      return NextResponse.json({ error: 'Name and Channel ID are required' }, { status: 400 });
    }

    const payload = {
      parent: { database_id: channelsDbId },
      properties: {
        // タイトルプロパティは名前不定なので、プロパティタイプで指定できればいいが、
        // 典型的には「名前」または「Name」
        "名前": {
          title: [
            {
              text: { content: name }
            }
          ]
        },
        "チャンネルID": {
          rich_text: [
            {
              text: { content: channelId }
            }
          ]
        }
      }
    };

    const response = await fetch('https://api.notion.com/v1/pages', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${notionApiKey}`,
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28'
      },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      // プロパティ名「名前」が見つからなかった場合のフォールバック（英語のNameの場合）
      if (response.status === 400) {
        const fallbackPayload = { ...payload };
        delete fallbackPayload.properties["名前"];
        fallbackPayload.properties["Name"] = payload.properties["名前"];
        
        const fallbackRes = await fetch('https://api.notion.com/v1/pages', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${notionApiKey}`,
            'Content-Type': 'application/json',
            'Notion-Version': '2022-06-28'
          },
          body: JSON.stringify(fallbackPayload)
        });
        
        if (!fallbackRes.ok) {
          const errText = await fallbackRes.text();
          throw new Error(`Notion API Error (Fallback): ${fallbackRes.status} ${errText}`);
        }
      } else {
        const errText = await response.text();
        throw new Error(`Notion API Error: ${response.status} ${errText}`);
      }
    }

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('Error adding channel:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
