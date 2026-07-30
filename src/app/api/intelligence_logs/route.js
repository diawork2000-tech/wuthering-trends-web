import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

const REPO_OWNER = 'diawork2000-tech';
const REPO_NAME = 'wuthering-trends-web';
const FILE_PATH = 'scraper/intelligence_logs.json';
const BRANCH = 'main';

export async function GET() {
  const githubPat = process.env.GITHUB_PAT;
  
  // GitHub PAT がある場合はクラウド(GitHub)の最新ログファイルを最優先取得！
  if (githubPat) {
    try {
      const url = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${FILE_PATH}?ref=${BRANCH}`;
      const res = await fetch(url, {
        headers: {
          'Authorization': `token ${githubPat}`,
          'Accept': 'application/vnd.github.v3+json',
        },
        cache: 'no-store'
      });
      if (res.ok) {
        const data = await res.json();
        const contentBuffer = Buffer.from(data.content, 'base64');
        const logContent = contentBuffer.toString('utf-8');
        const parsedLogs = JSON.parse(logContent);
        return NextResponse.json({ success: true, logs: parsedLogs });
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
