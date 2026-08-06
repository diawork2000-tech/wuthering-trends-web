import { NextResponse } from 'next/server';

// トピックカードの「採用」チェックを ON/OFF する。
// Notion 側のプロパティのみ更新し、スキーマ作成は scraper 側の
// ensure_notion_db_schema() が担当するのでここでは触らない。
export async function PATCH(request, { params }) {
  const { id } = await params;
  const notionApiKey = process.env.NOTION_API_KEY;

  if (!notionApiKey) {
    return NextResponse.json({ error: 'Notion API Key is missing' }, { status: 500 });
  }
  if (!id) {
    return NextResponse.json({ error: 'Page ID is required' }, { status: 400 });
  }

  try {
    const body = await request.json();
    const properties = {};

    if (typeof body.adopted === 'boolean') {
      properties['採用'] = { checkbox: body.adopted };
    }
    // 制作状況は「未着手 → 制作中 → 投稿済み」を追えるようにするためのもの。
    // 採用チェックだけだと、後から作ったのかどうかが分からなくなる。
    if (typeof body.status === 'string' && body.status) {
      properties['制作状況'] = { select: { name: body.status } };
    }

    if (Object.keys(properties).length === 0) {
      return NextResponse.json({ error: 'No updatable field provided' }, { status: 400 });
    }

    const response = await fetch(`https://api.notion.com/v1/pages/${id}`, {
      method: 'PATCH',
      headers: {
        'Authorization': `Bearer ${notionApiKey}`,
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28'
      },
      body: JSON.stringify({ properties })
    });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`Notion API Error: ${response.status} ${errText}`);
    }

    return NextResponse.json({ success: true, ...body });
  } catch (error) {
    console.error('Error updating adoption status:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
