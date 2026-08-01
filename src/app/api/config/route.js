import { NextResponse } from 'next/server';
import { readRepoJson, writeRepoJson } from '@/lib/github';

const FILE_PATH = 'scraper/config.json';

// config.json を取得
export async function GET() {
  try {
    const file = await readRepoJson(FILE_PATH);
    if (!file) {
      return NextResponse.json({ error: 'config.json not found in repository' }, { status: 404 });
    }
    return NextResponse.json({ config: file.json, sha: file.sha });
  } catch (error) {
    console.error('Error fetching config from GitHub:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// config.json を更新
export async function PUT(request) {
  try {
    const { config, sha } = await request.json();
    if (!config || !sha) {
      return NextResponse.json({ error: 'Config content and SHA are required' }, { status: 400 });
    }

    await writeRepoJson(FILE_PATH, config, sha, 'Update config.json from Web UI');
    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('Error updating config on GitHub:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
