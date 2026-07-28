import { NextResponse } from 'next/server';

export async function GET(request) {
  return await triggerScraper('GET');
}

export async function POST(request) {
  return await triggerScraper('POST');
}

async function triggerScraper(method) {
  const githubToken = process.env.GITHUB_PAT;
  const repoOwner = 'diawork2000-tech';
  const repoName = 'wuthering-trends-web';

  if (!githubToken) {
    console.error('CRON EXECUTION FAILED: GITHUB_PAT missing from Vercel environment.');
    return NextResponse.json({ success: false, error: 'GITHUB_PAT is missing.' }, { status: 500 });
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
        client_payload: {
          source: `Vercel-Cron-Hourly (${method})`,
          timestamp: new Date().toISOString()
        }
      }),
      cache: 'no-store'
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error('CRON GitHub Dispatch Error:', response.status, errorText);
      return NextResponse.json({ success: false, status: response.status, details: errorText }, { status: 502 });
    }

    console.log('✅ [Vercel Cron] Successfully forced GitHub Actions scraper run at:', new Date().toISOString());
    return NextResponse.json({ 
      success: true, 
      message: 'Hourly Vercel Cron successfully triggered trend collector on GitHub Actions.',
      timestamp: new Date().toISOString() 
    }, { status: 200 });

  } catch (error) {
    console.error('CRON Trigger Exception:', error);
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
