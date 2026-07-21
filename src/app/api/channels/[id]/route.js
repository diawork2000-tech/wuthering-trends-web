import { NextResponse } from 'next/server';

export async function DELETE(request, { params }) {
  const p = await params;
  const { id } = p; // NotionのページID
  const notionApiKey = process.env.NOTION_API_KEY;

  if (!notionApiKey) {
    return NextResponse.json({ error: 'Notion API Key is missing' }, { status: 500 });
  }

  if (!id) {
    return NextResponse.json({ error: 'Page ID is required' }, { status: 400 });
  }

  try {
    // Notion APIでページをアーカイブ (削除と同義)
    const response = await fetch(`https://api.notion.com/v1/pages/${id}`, {
      method: 'PATCH',
      headers: {
        'Authorization': `Bearer ${notionApiKey}`,
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28'
      },
      body: JSON.stringify({
        archived: true
      })
    });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`Notion API Error: ${response.status} ${errText}`);
    }

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('Error deleting channel:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
