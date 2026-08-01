import { NextResponse } from 'next/server';
import { readRepoJson } from '@/lib/github';

export async function GET() {
  try {
    const file = await readRepoJson('scraper/logs.json');
    return NextResponse.json({ logs: file ? file.json : [] });
  } catch (error) {
    console.error('Error fetching logs from GitHub:', error);
    return NextResponse.json({ error: error.message, logs: [] }, { status: 500 });
  }
}
