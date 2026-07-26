import { NextResponse } from 'next/server';

const REPO_OWNER = 'diawork2000-tech';
const REPO_NAME = 'wuthering-trends-web';
const FILE_PATH = 'scraper/logs.json';
const BRANCH = 'main';

export async function GET() {
  const githubPat = process.env.GITHUB_PAT;
  if (!githubPat) {
    return NextResponse.json({ error: 'GITHUB_PAT is missing in environment variables' }, { status: 500 });
  }

  try {
    const url = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${FILE_PATH}?ref=${BRANCH}`;
    const res = await fetch(url, {
      headers: {
        'Authorization': `token ${githubPat}`,
        'Accept': 'application/vnd.github.v3+json',
      },
      cache: 'no-store'
    });

    if (!res.ok) {
      if (res.status === 404) {
        return NextResponse.json({ logs: [] });
      }
      throw new Error(`GitHub API Error: ${res.status}`);
    }

    const data = await res.json();
    const contentBuffer = Buffer.from(data.content, 'base64');
    const logContent = contentBuffer.toString('utf-8');
    const parsedLogs = JSON.parse(logContent);

    return NextResponse.json({ logs: parsedLogs });
  } catch (error) {
    console.error('Error fetching logs from GitHub:', error);
    return NextResponse.json({ error: error.message, logs: [] }, { status: 500 });
  }
}
