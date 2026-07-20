import { NextResponse } from 'next/server';

export async function POST() {
  const githubToken = process.env.GITHUB_PAT; // Personal Access Token
  const repoOwner = 'diawork2000-tech';
  const repoName = 'wuthering-trends-web';

  if (!githubToken) {
    return NextResponse.json({ error: 'GitHub PAT is not configured on Vercel.' }, { status: 500 });
  }

  try {
    const response = await fetch(`https://api.github.com/repos/${repoOwner}/${repoName}/dispatches`, {
      method: 'POST',
      headers: {
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': `token ${githubToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        event_type: 'trigger-scraper',
      }),
    });

    if (!response.ok) {
      const errText = await response.text();
      console.error('GitHub API Error:', response.status, errText);
      return NextResponse.json({ error: `GitHub API failed: ${response.status}` }, { status: 500 });
    }

    return NextResponse.json({ success: true, message: 'Scraper triggered successfully.' });
  } catch (error) {
    console.error('Error triggering GitHub Actions:', error);
    return NextResponse.json({ error: error.message || 'Internal Server Error' }, { status: 500 });
  }
}
