import { NextResponse } from 'next/server';

// Twitter の動画配信は、どこから来た読み込みかを見て他サイトからの再生を拒む。
// ブラウザは必ず参照元を名乗るため、カードに動画URLをそのまま書くと必ず 403 になる。
// 実測:
//   参照元なし            → 200 / video/mp4 / 2.3MB（範囲指定も 206 で通る）
//   参照元を付ける        → 403 / 0 bytes
// そこでサーバ側が参照元を名乗らずに取りに行き、そのまま流す。
// 画像(pbs.twimg.com)は他サイトからでも読めるので中継しない。

// 中継先はここに挙げたものだけ。絞らないと、誰でも好きなURLを
// このサーバー経由で読める踏み台になってしまう。
const ALLOWED_HOSTS = new Set(['video.twimg.com']);

export async function GET(request) {
  const target = new URL(request.url).searchParams.get('u');
  if (!target) {
    return NextResponse.json({ error: 'u is required' }, { status: 400 });
  }

  let upstream;
  try {
    upstream = new URL(target);
  } catch {
    return NextResponse.json({ error: 'URLとして解釈できません' }, { status: 400 });
  }
  if (upstream.protocol !== 'https:' || !ALLOWED_HOSTS.has(upstream.hostname)) {
    return NextResponse.json({ error: '中継できない宛先です' }, { status: 403 });
  }

  // 再生位置の指定はそのまま渡す。動画要素は範囲指定で読みに来るため、
  // ここを落とすと頭出しや途中再生ができない。
  const range = request.headers.get('range');

  try {
    const res = await fetch(upstream.toString(), {
      headers: range ? { Range: range } : {},
      // 参照元を名乗らないことが要点。名乗ると 403 で拒まれる。
      referrerPolicy: 'no-referrer',
      cache: 'no-store',
    });

    if (!res.ok && res.status !== 206) {
      return NextResponse.json(
        { error: `配信元が ${res.status} を返しました` },
        { status: res.status === 404 ? 404 : 502 }
      );
    }

    const headers = new Headers();
    for (const key of ['content-type', 'content-length', 'content-range', 'accept-ranges']) {
      const value = res.headers.get(key);
      if (value) headers.set(key, value);
    }
    // 部分取得ごとに中身が違うので、範囲の指定まで含めて別物として扱わせる。
    // これを書かずに public で置かせたところ、動画要素が末尾を読みに来た
    // ときの応答（末尾10KB）が居座り、以後どの読み込みにもそれが返って
    // 再生できなくなった。
    headers.set('Vary', 'Range');
    // public にすると共有の置き場に乗って同じ事故が起きる。手元だけに置かせる。
    headers.set('Cache-Control', 'private, max-age=3600');

    return new NextResponse(res.body, { status: res.status, headers });
  } catch (error) {
    console.error('[media] 中継に失敗:', error);
    return NextResponse.json({ error: error.message }, { status: 502 });
  }
}
