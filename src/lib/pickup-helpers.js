// ピックアップAPIの判定部分。
// ルート本体から切り出してあるのは、Notionに繋がずにテストできるようにするため。
// ここが壊れると「関係ない行を巻き込んで解除する」「制作状況を変えたら
// 採用が外れる」といった、人の判断を壊す事故に直結する。

export const MAX_IDS = 200; // 一度に扱う上限。取り違えで全件消すのを防ぐ
export const ALLOWED_STATUSES = ['未着手', '制作中', '投稿済み', '見送り'];

const NOTION_ID =
  /^[0-9a-f]{32}$|^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// 名寄せのキーになるため、YouTubeの動画IDだけを厳密に取り出す。
//
// 任意ドメインの ?v= を動画ID扱いすると、名寄せが無関係な行を1枚のカードに
// 束ね、解除時にまとめて外してしまう。ホストと11文字IDの両方を確かめる。
const YOUTUBE_HOSTS = new Set([
  'youtube.com',
  'www.youtube.com',
  'm.youtube.com',
  'music.youtube.com',
  'youtu.be',
  'www.youtu.be',
]);

const VIDEO_ID = /^[\w-]{11}$/;

export function extractVideoId(url) {
  if (!url) return '';
  try {
    const u = new URL(url);
    const host = u.hostname.toLowerCase();
    if (!YOUTUBE_HOSTS.has(host)) return '';

    if (host.endsWith('youtu.be')) {
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

// PATCH の入力を検証する。戻り値は { error } か { ids, properties }。
//
// 要点は「渡されたフィールドだけ更新する」こと。以前は採用を無条件に
// 代入しており、status だけ送ると採用が外れていた。
export function parsePatchBody(body) {
  if (!body || typeof body !== 'object') {
    return { error: 'リクエストの形式が不正です' };
  }
  if (!Array.isArray(body.ids)) {
    return { error: 'ids は配列で指定してください' };
  }

  const invalid = body.ids.filter(
    (id) => typeof id !== 'string' || !NOTION_ID.test(id.trim())
  );
  if (invalid.length > 0) {
    return { error: `NotionのページIDとして不正な値が含まれています (${invalid.length}件)` };
  }

  // 名寄せで束ねた行を平坦化して送るため、同じIDが重複しうる
  const ids = [...new Set(body.ids.map((id) => id.trim()))];
  if (ids.length === 0) return { error: 'ids is required' };
  if (ids.length > MAX_IDS) {
    return { error: `一度に更新できるのは ${MAX_IDS} 件までです (${ids.length}件が指定されました)` };
  }

  const properties = {};
  if (typeof body.adopted === 'boolean') {
    properties['採用'] = { checkbox: body.adopted };
  }
  if (body.status !== undefined) {
    if (typeof body.status !== 'string' || !ALLOWED_STATUSES.includes(body.status)) {
      return { error: `status は ${ALLOWED_STATUSES.join(' / ')} のいずれかです` };
    }
    properties['制作状況'] = { select: { name: body.status } };
  }
  if (Object.keys(properties).length === 0) {
    return { error: 'adopted か status のどちらかを指定してください' };
  }

  return { ids, properties };
}
