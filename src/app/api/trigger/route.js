import { NextResponse } from 'next/server';
import { dispatchWorkflow } from '@/lib/github';

export async function POST() {
  try {
    await dispatchWorkflow('trigger-scraper', { source: 'Web UI' });
    return NextResponse.json({ success: true, message: 'Scraper triggered successfully.' });
  } catch (error) {
    console.error('Error triggering GitHub Actions:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
