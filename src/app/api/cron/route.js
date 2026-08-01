import { NextResponse } from 'next/server';
import { dispatchWorkflow } from '@/lib/github';

// POST のみを受け付ける。GET を残しておくと、リポジトリが公開されている以上
// クローラーやリンクプレビューが URL を踏むだけで収集が 1 回起動してしまい、
// 余裕のない YouTube API クォータ（4キー合計でほぼ毎時実行分ぴったり）を削ってしまう。
// 外部 cron から叩く場合は HTTP メソッドを POST に設定すること。
export async function POST() {
  try {
    await dispatchWorkflow('trigger-scraper', {
      source: 'Vercel-Cron-Hourly (POST)',
      timestamp: new Date().toISOString(),
    });

    console.log('✅ [Vercel Cron] Successfully forced GitHub Actions scraper run at:', new Date().toISOString());
    return NextResponse.json({
      success: true,
      message: 'Hourly Vercel Cron successfully triggered trend collector on GitHub Actions.',
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    console.error('CRON Trigger Exception:', error);
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
