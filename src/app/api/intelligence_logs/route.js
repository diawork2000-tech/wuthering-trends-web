import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { readRepoJson } from '@/lib/github';

export async function GET() {
  // GitHub PAT がある場合はクラウド(GitHub)の最新ログファイルを最優先取得！
  if (process.env.GITHUB_PAT) {
    try {
      const file = await readRepoJson('scraper/intelligence_logs.json');
      if (file) {
        return NextResponse.json({ success: true, logs: file.json });
      }
    } catch (error) {
      console.error('GitHub fetch log failed, falling back to local storage:', error);
    }
  }

  // GitHub経由で取れない場合または開発環境・初回時はローカルプロジェクト内ログファイルを安全リターン！
  try {
    const localPath = path.join(process.cwd(), 'scraper/intelligence_logs.json');
    if (fs.existsSync(localPath)) {
      const fileText = fs.readFileSync(localPath, 'utf-8');
      return NextResponse.json({ success: true, logs: JSON.parse(fileText) });
    }
  } catch (err) {
    console.error('Local fallback failed:', err);
  }

  // どれも存在しない場合の空配列フォールバック
  return NextResponse.json({ success: true, logs: [] });
}
