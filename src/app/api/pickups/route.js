import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

// ピックアップ（採用チェック）済みの行を、YouTube動画DBとトレンド企画DBの
// 両方から集めて1つのリストとして返す。
// 収集の中身には一切触らず、「採用」「制作状況」という人の判断の欄だけを扱う。

const NOTION_VERSION = '2022-06-28';
const VIDEO_DB_ID = process.env.NOTION_DATABASE_ID;
const TOPIC_DB_ID =
  process.env.NOTION_INTELLIGENCE_DB_ID || '3ad82a7701b08067bf5de4694df49d9b';

function notionHeaders(key) {
  return {
    Authorization: `Bearer ${key}`,
    'Content-Type': 'application/json',
    'Notion-Version': NOTION_VERSION,
  };
}

// 採用=true の行だけを全ページ取得する。
// 「採用」列がまだ無いDBに対しては Notion が 400 を返すので、その場合は空で返す
// （収集が一度走ればスキーマが自動追加される）。
async function queryAdopted(dbId, key) {
  if (!dbId) return [];

  const results = [];
  let cursor;

  while (true) {
    const body = {
      filter: { property: '採用', checkbox: { equals: true } },
      sorts: [{ timestamp: 'created_time', direction: 'descending' }],
      page_size: 100,
    };
    if (cursor) body.start_cursor = cursor;

    const res = await fetch(`https://api.notion.com/v1/databases/${dbId}/query`, {
      method: 'POST',
      headers: notionHeaders(key),
      body: JSON.stringify(body),
      cache: 'no-store',
    });

    if (!res.ok) {
      // 「採用」列が未作成のうちは 400 が返る。異常ではないので空扱いにする。
      console.warn(`[pickups] query failed for ${dbId}: ${res.status}`);
      break;
    }

    const data = await res.json();
    results.push(...(data.results || []));
    if (!data.has_more || !data.next_cursor) break;
    cursor = data.next_cursor;
  }

  return results;
}

function readTitle(props) {
  for (const key in props) {
    if (props[key]?.type === 'title' && props[key].title?.length > 0) {
      return props[key].title.map((t) => t.plain_text).join('');
    }
  }
  return '無題';
}

function extractVideoId(url) {
  if (!url) return '';
  try {
    const u = new URL(url);
    if (u.hostname.includes('youtu.be')) return u.pathname.slice(1);
    const v = u.searchParams.get('v');
    if (v) return v;
    const m = u.pathname.match(/\/shorts\/([\w-]+)/);
    if (m) return m[1];
  } catch {
    // URLとして壊れている場合は素通し
  }
  return '';
}

function mapVideo(page) {
  const props = page.properties || {};
  const url = props['URL']?.url || '';
  return {
    id: page.id,
    origin: 'video',
    originLabel: 'YouTube',
    title: readTitle(props),
    url,
    videoId: extractVideoId(url),
    thumbnail: page.cover?.external?.url || '',
    subtitle: props['チャンネル']?.rich_text?.[0]?.plain_text || '',
    category: props['カテゴリ']?.select?.name || '',
    viewCount: props['再生数']?.number ?? null,
    score: null,
    status: props['制作状況']?.select?.name || '未着手',
    createdTime: page.created_time,
  };
}

function mapTopic(page) {
  const props = page.properties || {};
  const url = props['一次URL']?.url || '';
  return {
    id: page.id,
    origin: 'topic',
    originLabel: 'マルチメディア',
    title: readTitle(props),
    url,
    videoId: extractVideoId(url),
    thumbnail: page.cover?.external?.url || '',
    subtitle: props['メディアソース']?.select?.name || '',
    category: props['メディアソース']?.select?.name || '',
    viewCount: props['再生数']?.number ?? null,
    score: props['スコア']?.number ?? null,
    status: props['制作状況']?.select?.name || '未着手',
    createdTime: page.created_time,
  };
}

export async function GET() {
  const key = process.env.NOTION_API_KEY;
  if (!key) {
    return NextResponse.json({ success: true, items: [], notice: 'Notion未接続' });
  }

  try {
    const [videos, topics] = await Promise.all([
      queryAdopted(VIDEO_DB_ID, key),
      queryAdopted(TOPIC_DB_ID, key),
    ]);

    const items = [...videos.map(mapVideo), ...topics.map(mapTopic)];

    // 同じ動画が両方のDBに入っていることがあるため、動画IDで名寄せする。
    // 解除は行単位で必要なので、束ねた相手のページIDも持たせておく。
    const byKey = new Map();
    for (const item of items) {
      const dedupeKey = item.videoId || item.url || item.id;
      const found = byKey.get(dedupeKey);
      if (found) {
        found.linkedIds.push(item.id);
        if (found.score == null && item.score != null) found.score = item.score;
        if (found.viewCount == null && item.viewCount != null) found.viewCount = item.viewCount;
        if (!found.thumbnail && item.thumbnail) found.thumbnail = item.thumbnail;
        if (!found.originLabel.includes(item.originLabel)) {
          found.originLabel = `${found.originLabel}・${item.originLabel}`;
        }
        continue;
      }
      byKey.set(dedupeKey, { ...item, linkedIds: [item.id] });
    }

    const merged = [...byKey.values()].sort(
      (a, b) => new Date(b.createdTime) - new Date(a.createdTime)
    );

    return NextResponse.json({ success: true, items: merged, count: merged.length });
  } catch (error) {
    console.error('[pickups] GET failed:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// ピックアップの解除（単体・複数・一括共通）。
// 行は消さず、採用チェックを外すだけ。制作状況を同時に変えることもできる。
export async function PATCH(request) {
  const key = process.env.NOTION_API_KEY;
  if (!key) {
    return NextResponse.json({ error: 'Notion API Key is missing' }, { status: 500 });
  }

  try {
    const body = await request.json();
    const ids = Array.isArray(body.ids) ? body.ids.filter(Boolean) : [];
    if (ids.length === 0) {
      return NextResponse.json({ error: 'ids is required' }, { status: 400 });
    }

    const properties = {};
    properties['採用'] = { checkbox: body.adopted === true };
    if (typeof body.status === 'string' && body.status) {
      properties['制作状況'] = { select: { name: body.status } };
    }

    // Notion のレート制限は毎秒3リクエスト程度。一括解除で数十件来ても
    // 弾かれないよう、3件ずつに区切って送る。
    const failed = [];
    for (let i = 0; i < ids.length; i += 3) {
      const chunk = ids.slice(i, i + 3);
      const settled = await Promise.all(
        chunk.map(async (id) => {
          const res = await fetch(`https://api.notion.com/v1/pages/${id}`, {
            method: 'PATCH',
            headers: notionHeaders(key),
            body: JSON.stringify({ properties }),
          });
          return res.ok ? null : id;
        })
      );
      failed.push(...settled.filter(Boolean));
      if (i + 3 < ids.length) {
        await new Promise((r) => setTimeout(r, 350));
      }
    }

    return NextResponse.json({
      success: failed.length === 0,
      updated: ids.length - failed.length,
      failed,
    });
  } catch (error) {
    console.error('[pickups] PATCH failed:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
