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
// 戻り値は { rows, complete, reason }。
// 途中で失敗したまま「取れた分だけ」を返すと、画面には全件のように見えて
// 「すべて外す」が一部にしか効かない。取り切れたかどうかを必ず添える。
async function queryAdopted(dbId, key) {
  if (!dbId) return { rows: [], complete: false, reason: 'DB ID未設定' };

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
      // 「採用」列が未作成のうちは 400 が返る（列は収集が一度走れば作られる）。
      // その場合だけは 0件で正常とみなし、それ以外は不完全として扱う。
      const text = await res.text();
      const missingColumn = res.status === 400 && text.includes('採用');
      console.warn(`[pickups] query failed for ${dbId}: ${res.status}`);
      if (missingColumn && results.length === 0) {
        return { rows: [], complete: true, reason: '' };
      }
      return { rows: results, complete: false, reason: `Notion ${res.status}` };
    }

    const data = await res.json();
    results.push(...(data.results || []));
    if (!data.has_more || !data.next_cursor) break;
    cursor = data.next_cursor;
  }

  return { rows: results, complete: true, reason: '' };
}

function readTitle(props) {
  for (const key in props) {
    if (props[key]?.type === 'title' && props[key].title?.length > 0) {
      return props[key].title.map((t) => t.plain_text).join('');
    }
  }
  return '無題';
}

// 名寄せのキーになるため、YouTubeの動画IDだけを厳密に取り出す。
//
// 以前は任意ドメインの ?v= を動画ID扱いしていた。名寄せは「同じIDなら同じ動画」
// として複数行を1枚のカードに束ね、解除時はその全行をまとめて外すので、
// 無関係なURLが同じ ?v= を持っているだけで巻き込んで解除する事故になりうる。
const YOUTUBE_HOSTS = new Set([
  'youtube.com',
  'www.youtube.com',
  'm.youtube.com',
  'music.youtube.com',
  'youtu.be',
  'www.youtu.be',
]);

const VIDEO_ID = /^[\w-]{11}$/;

function extractVideoId(url) {
  if (!url) return '';
  try {
    const u = new URL(url);
    if (!YOUTUBE_HOSTS.has(u.hostname.toLowerCase())) return '';

    if (u.hostname.toLowerCase().endsWith('youtu.be')) {
      const id = u.pathname.slice(1).split('/')[0];
      return VIDEO_ID.test(id) ? id : '';
    }
    const v = u.searchParams.get('v');
    if (v && VIDEO_ID.test(v)) return v;

    const m = u.pathname.match(/\/(?:shorts|embed|live)\/([\w-]{11})(?:$|\/)/);
    if (m) return m[1];
  } catch {
    // URLとして壊れている場合は名寄せに使わない
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

    const items = [...videos.rows.map(mapVideo), ...topics.rows.map(mapTopic)];
    const partial = !videos.complete || !topics.complete;
    const partialReason = [
      videos.complete ? '' : `YouTube動画DB: ${videos.reason}`,
      topics.complete ? '' : `トレンド企画DB: ${topics.reason}`,
    ]
      .filter(Boolean)
      .join(' / ');

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

    // partial のときは「全件外す」等の一括操作を画面側で止める。
    return NextResponse.json({
      success: true,
      items: merged,
      count: merged.length,
      partial,
      partialReason,
    });
  } catch (error) {
    console.error('[pickups] GET failed:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// ピックアップの解除・制作状況の更新（単体・複数・一括共通）。
// 行は消さず、指定された欄だけを書き換える。
//
// 設計上の要点:
//   1. 渡されたフィールドだけ更新する。以前は adopted を無条件に代入しており、
//      status だけ送ると採用が外れる（body.adopted === true が false になる）。
//      制作状況を変えたつもりでピックアップから消える事故につながっていた。
//   2. Notion のレート制限に合わせて直列送信する。並列3件は上限を超えうる。
//   3. 429/5xx は Retry-After を見て再試行する。
//   4. 結果はID単位で返す。どれが失敗したか分からないと再同期できない。

const MAX_IDS = 200; // 一度に扱う上限。取り違えで全件消すのを防ぐ
const ALLOWED_STATUSES = new Set(['未着手', '制作中', '投稿済み', '見送り']);
const NOTION_ID = /^[0-9a-f]{32}$|^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 1件を更新する。一時的な失敗（429/5xx）は指数バックオフで再試行する。
async function patchPage(id, properties, key) {
  let waitMs = 400;
  for (let attempt = 0; attempt < 4; attempt++) {
    const res = await fetch(`https://api.notion.com/v1/pages/${id}`, {
      method: 'PATCH',
      headers: notionHeaders(key),
      body: JSON.stringify({ properties }),
    });
    if (res.ok) return { id, ok: true };

    const transient = res.status === 429 || res.status >= 500;
    if (!transient) {
      const text = await res.text();
      return { id, ok: false, status: res.status, error: text.slice(0, 200) };
    }
    // Notion が待ち時間を指定してきたら従う
    const retryAfter = Number(res.headers.get('retry-after'));
    await sleep(Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : waitMs);
    waitMs *= 2;
  }
  return { id, ok: false, status: 429, error: '再試行の上限に達しました' };
}

export async function PATCH(request) {
  const key = process.env.NOTION_API_KEY;
  if (!key) {
    return NextResponse.json({ error: 'Notion API Key is missing' }, { status: 500 });
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'JSONとして解釈できません' }, { status: 400 });
  }

  // --- 入力検証 ---
  if (!Array.isArray(body.ids)) {
    return NextResponse.json({ error: 'ids は配列で指定してください' }, { status: 400 });
  }
  const invalid = body.ids.filter((id) => typeof id !== 'string' || !NOTION_ID.test(id.trim()));
  if (invalid.length > 0) {
    return NextResponse.json(
      { error: `NotionのページIDとして不正な値が含まれています (${invalid.length}件)` },
      { status: 400 }
    );
  }
  // 名寄せで束ねた行を平坦化して送るため、同じIDが重複しうる
  const ids = [...new Set(body.ids.map((id) => id.trim()))];
  if (ids.length === 0) {
    return NextResponse.json({ error: 'ids is required' }, { status: 400 });
  }
  if (ids.length > MAX_IDS) {
    return NextResponse.json(
      { error: `一度に更新できるのは ${MAX_IDS} 件までです (${ids.length}件が指定されました)` },
      { status: 400 }
    );
  }

  const properties = {};
  if (typeof body.adopted === 'boolean') {
    properties['採用'] = { checkbox: body.adopted };
  }
  if (body.status !== undefined) {
    if (typeof body.status !== 'string' || !ALLOWED_STATUSES.has(body.status)) {
      return NextResponse.json(
        { error: `status は ${[...ALLOWED_STATUSES].join(' / ')} のいずれかです` },
        { status: 400 }
      );
    }
    properties['制作状況'] = { select: { name: body.status } };
  }
  if (Object.keys(properties).length === 0) {
    return NextResponse.json(
      { error: 'adopted か status のどちらかを指定してください' },
      { status: 400 }
    );
  }

  // --- 送信（直列） ---
  try {
    const results = [];
    for (const id of ids) {
      results.push(await patchPage(id, properties, key));
      await sleep(350); // Notion の毎秒3リクエスト制限に合わせる
    }

    const failed = results.filter((r) => !r.ok);
    return NextResponse.json(
      {
        success: failed.length === 0,
        requested: ids.length,
        updated: ids.length - failed.length,
        results,
        failed: failed.map((r) => r.id),
      },
      { status: failed.length === 0 ? 200 : 207 }
    );
  } catch (error) {
    console.error('[pickups] PATCH failed:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
