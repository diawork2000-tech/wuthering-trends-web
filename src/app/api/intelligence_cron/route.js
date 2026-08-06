import { NextResponse } from 'next/server';
import { dispatchWorkflow } from '@/lib/github';

// POST のみを受け付ける（理由は /api/cron と同じ）。
// 外部 cron から叩く場合は HTTP メソッドを POST に設定すること。
export async function POST(request) {
  try {
    // 画面の「今すぐ即時発掘」ボタンからは ?force=1 が付く。
    // 定期 cron からの呼び出しには付かないので、収集側の間隔ガードが効いたままになる。
    const force = new URL(request.url).searchParams.get('force') === '1';

    await dispatchWorkflow('trigger-intelligence', {
      source: 'Vercel-Intelligence-Cron (POST)',
      force,
      timestamp: new Date().toISOString(),
    });

    console.log('✅ [Intelligence Cron] Successfully forced GitHub Actions run at:', new Date().toISOString());
    return NextResponse.json({
      success: true,
      message: 'High-speed Intelligence Cron successfully triggered topic generator on GitHub Actions.',
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    console.error('INTELLIGENCE CRON Trigger Exception:', error);
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
