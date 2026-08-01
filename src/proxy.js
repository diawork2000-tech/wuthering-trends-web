import { NextResponse } from 'next/server';

// 個人専用ツールのための最小限のアクセスゲート。
// 公開 URL を知られると /api/trigger や /api/cron 経由で YouTube API クォータと
// GitHub Actions の実行時間を第三者に消費されうるため、外周だけ塞ぐ。
//
// 使い方（一度だけ）:
//   1. Vercel の環境変数に APP_SECRET を設定する
//   2. ブラウザで https://<app>/?key=<APP_SECRET> を一度開く
//      → Cookie が入り、以降はいつも通り URL を開くだけで使える
//   3. cron-job.org などの外部からは ?key=<APP_SECRET> か
//      Authorization: Bearer <APP_SECRET> を付けて叩く
//
// APP_SECRET を設定するまではゲートを開けたままにする。未設定でいきなり閉じると
// ローカルの npm run dev も既存デプロイも動かなくなってしまうため。

const COOKIE_NAME = 'wt_access';
const ONE_YEAR_SECONDS = 60 * 60 * 24 * 365;

function hasValidCredential(request, secret) {
  if (request.cookies.get(COOKIE_NAME)?.value === secret) return true;

  const auth = request.headers.get('authorization');
  if (auth === `Bearer ${secret}`) return true;

  return false;
}

export function proxy(request) {
  const secret = process.env.APP_SECRET;
  if (!secret) {
    return NextResponse.next();
  }

  const url = request.nextUrl;
  const keyParam = url.searchParams.get('key');
  const isApiRoute = url.pathname.startsWith('/api/');

  if (keyParam === secret) {
    // 外部 cron は Cookie を保持できないので、API は key 付きならそのまま通す。
    if (isApiRoute) {
      return NextResponse.next();
    }
    // 画面遷移は Cookie に移し替えて、URL からシークレットを消す。
    const cleanUrl = url.clone();
    cleanUrl.searchParams.delete('key');
    const res = NextResponse.redirect(cleanUrl);
    res.cookies.set({
      name: COOKIE_NAME,
      value: secret,
      httpOnly: true,
      sameSite: 'lax',
      secure: url.protocol === 'https:',
      maxAge: ONE_YEAR_SECONDS,
      path: '/',
    });
    return res;
  }

  if (hasValidCredential(request, secret)) {
    return NextResponse.next();
  }

  if (isApiRoute) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  return new NextResponse('401 Unauthorized', {
    status: 401,
    headers: { 'content-type': 'text/plain; charset=utf-8' },
  });
}

export const config = {
  // 静的アセットは素通し。ここを絞らないと CSS/JS まで 401 になり画面が壊れる。
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
