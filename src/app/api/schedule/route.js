import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { readRepoJson } from '@/lib/github';

const EMPTY = { updated_at: null, events: [] };

export async function GET() {
  // GitHub PAT があればクラウド側の最新データを最優先取得
  if (process.env.GITHUB_PAT) {
    try {
      const file = await readRepoJson('src/data/upcoming_schedule.json');
      if (file) {
        return NextResponse.json(file.json);
      }
    } catch (error) {
      console.error('GitHub fetch schedule failed, falling back to local file:', error);
    }
  }

  try {
    const localPath = path.join(process.cwd(), 'src/data/upcoming_schedule.json');
    if (fs.existsSync(localPath)) {
      return NextResponse.json(JSON.parse(fs.readFileSync(localPath, 'utf-8')));
    }
  } catch (err) {
    console.error('Local schedule fallback failed:', err);
  }

  return NextResponse.json(EMPTY);
}
