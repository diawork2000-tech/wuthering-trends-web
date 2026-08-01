import { NextResponse } from 'next/server';
import { readRepoJson, writeRepoJson } from '@/lib/github';

const FILE_PATH = 'scraper/config_intelligence.json';

/**
 * 競合時のマージ方針。
 * Actions 側は巡回のたびにハンドル名から解決した channel の `id` を書き戻している。
 * Web UI の保存でそれを消してしまうと次回巡回で再解決が走り YouTube API を余計に消費するため、
 * リモートで解決済みの id だけは拾い直す。
 */
function preserveResolvedChannelIds(remote, local) {
  const resolved = new Map();
  for (const ch of remote?.target_channels || []) {
    if (ch?.id && ch?.url) resolved.set(ch.url, ch.id);
  }

  return {
    ...local,
    target_channels: (local.target_channels || []).map((ch) =>
      ch.id ? ch : { ...ch, ...(resolved.has(ch.url) ? { id: resolved.get(ch.url) } : {}) }
    ),
  };
}

// config_intelligence.json を取得
export async function GET() {
  try {
    const file = await readRepoJson(FILE_PATH);
    if (!file) {
      return NextResponse.json(
        { error: 'config_intelligence.json not found in repository' },
        { status: 404 }
      );
    }
    return NextResponse.json({ config: file.json, sha: file.sha });
  } catch (error) {
    console.error('Error fetching intelligence config from GitHub:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// config_intelligence.json を更新・保存
export async function PUT(request) {
  try {
    const { config, sha } = await request.json();
    if (!config || !sha) {
      return NextResponse.json({ error: 'Config content and SHA are required' }, { status: 400 });
    }

    await writeRepoJson(FILE_PATH, config, sha, 'Update config_intelligence.json from Web UI', {
      onConflict: preserveResolvedChannelIds,
    });
    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('Error updating intelligence config on GitHub:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
