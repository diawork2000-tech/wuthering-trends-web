import { NextResponse } from 'next/server';

const REPO_OWNER = 'diawork2000-tech';
const REPO_NAME = 'wuthering-trends-web';
const FILE_PATH = 'scraper/config.json';
const BRANCH = 'main';

// config.json を取得
export async function GET() {
  const githubPat = process.env.GITHUB_PAT;
  if (!githubPat) {
    return NextResponse.json({ error: 'GITHUB_PAT is missing' }, { status: 500 });
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
      throw new Error(`GitHub API Error: ${res.status}`);
    }

    const data = await res.json();
    const contentBuffer = Buffer.from(data.content, 'base64');
    const configContent = contentBuffer.toString('utf-8');

    return NextResponse.json({ config: JSON.parse(configContent), sha: data.sha });
  } catch (error) {
    console.error('Error fetching config from GitHub:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// config.json を更新
export async function PUT(request) {
  const githubPat = process.env.GITHUB_PAT;
  if (!githubPat) {
    return NextResponse.json({ error: 'GITHUB_PAT is missing' }, { status: 500 });
  }

  try {
    const { config, sha } = await request.json();
    if (!config || !sha) {
      return NextResponse.json({ error: 'Config content and SHA are required' }, { status: 400 });
    }

    const contentBuffer = Buffer.from(JSON.stringify(config, null, 2), 'utf-8');
    const base64Content = contentBuffer.toString('base64');

    const url = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${FILE_PATH}`;
    const res = await fetch(url, {
      method: 'PUT',
      headers: {
        'Authorization': `token ${githubPat}`,
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message: 'Update config.json from Web UI',
        content: base64Content,
        sha: sha,
        branch: BRANCH
      }),
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`GitHub API Error: ${res.status} ${errText}`);
    }

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('Error updating config on GitHub:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
