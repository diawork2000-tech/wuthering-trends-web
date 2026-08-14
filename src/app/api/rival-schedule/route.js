import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { readRepoJson } from '@/lib/github';

// 競合タイトルのアップデート日程を返す。
// 判明している分はデータファイルに書き、そこから先は各タイトルの更新周期で
// 機械的に伸ばす。伸ばした分は confirmed: false にして、画面上でも予測と分かるようにする。
//
// バージョン番号は小数点以下を1つ進めて推測する。7.8の次が7.9なのか8.0なのかは
// 外からは分からないので外れることがあるが、「次回」とだけ書かれるより
// 何の話か分かるほうが役に立つ。外れうる箇所なので必ず(予測)を添える。
//
// 前半・後半はバージョン開始日と、その phase_offset_days 日後に分かれる。
// ガチャの入れ替えがここで起きるため、動画のネタとしてはバージョン開始と同じくらい重要。

const HORIZON_DAYS = 200; // これより先は予測しない（当たらないので出す意味がない）
const EMPTY = { updated_at: null, games: [], events: [] };

// 日付の足し算は必ずUTC上で行う。JST指定で作った Date を toISOString() に通すと
// 9時間戻って前日になり、生成される予定日が1日ずつ手前にずれる。
function addDays(iso, days) {
  const [y, m, d] = iso.split('-').map(Number);
  const t = Date.UTC(y, m - 1, d) + days * 86400000;
  return new Date(t).toISOString().slice(0, 10);
}

function todayJst() {
  const now = new Date(Date.now() + 9 * 3600000);
  return now.toISOString().slice(0, 10);
}

// 「7.1」→「7.2」。数値として扱うと 7.10 が 7.1 に潰れるので文字列のまま進める。
function nextVersion(v) {
  if (!v) return null;
  const m = String(v).match(/^(\d+)\.(\d+)$/);
  if (!m) return null;
  return `${m[1]}.${Number(m[2]) + 1}`;
}

// 1つのバージョンを、前半・後半のイベントに分解する。
function toPhaseEvents(game, base) {
  const label = base.version ? `${game.name} ${base.version}` : game.name;
  if (!game.has_phases) {
    return [{ ...base, label: base.title ? `${label}「${base.title}」` : label, phase: '' }];
  }
  const offset = Number(game.phase_offset_days) || Math.floor((Number(game.cycle_days) || 42) / 2);
  return [
    { ...base, label: `${label} 前半`, phase: '前半' },
    {
      ...base,
      date: addDays(base.date, offset),
      label: `${label} 後半`,
      phase: '後半',
      // 後半の日付は開始日からの逆算。バージョン自体が確定でも、後半入りは前後しうる。
      confirmed: false,
      note: base.note || `バージョン開始から${offset}日後（推定）`,
    },
  ];
}

function expand(game) {
  const known = [...(game.versions || [])]
    .filter((v) => v.date)
    .sort((a, b) => a.date.localeCompare(b.date));

  const events = known.flatMap((v) =>
    toPhaseEvents(game, {
      game_id: game.id,
      game: game.name,
      color: game.color,
      version: v.version || null,
      title: v.title || '',
      date: v.date,
      confirmed: v.confirmed !== false,
      note: v.note || '',
      predicted: false,
    })
  );

  const cycle = Number(game.cycle_days) || 42;
  const limit = addDays(todayJst(), HORIZON_DAYS);
  let cursor = known.length ? known[known.length - 1].date : null;
  let version = known.length ? known[known.length - 1].version : null;

  while (cursor) {
    const next = addDays(cursor, cycle);
    if (next > limit) break;
    version = nextVersion(version);
    events.push(
      ...toPhaseEvents(game, {
        game_id: game.id,
        game: game.name,
        color: game.color,
        version: version ? `${version}(予測)` : null,
        title: '',
        date: next,
        confirmed: false,
        note: `直近の周期(${cycle}日)からの推定`,
        predicted: true,
      })
    );
    cursor = next;
  }

  return events;
}

async function loadConfig() {
  // GitHub PAT があればリポジトリ側の最新を優先する（既存の /api/schedule と同じ方針）。
  if (process.env.GITHUB_PAT) {
    try {
      const file = await readRepoJson('src/data/rival_schedule.json');
      if (file) return file.json;
    } catch (error) {
      console.error('GitHub fetch rival schedule failed, falling back to local file:', error);
    }
  }
  try {
    const localPath = path.join(process.cwd(), 'src/data/rival_schedule.json');
    if (fs.existsSync(localPath)) {
      return JSON.parse(fs.readFileSync(localPath, 'utf-8'));
    }
  } catch (err) {
    console.error('Local rival schedule fallback failed:', err);
  }
  return null;
}

export async function GET() {
  const cfg = await loadConfig();
  if (!cfg) return NextResponse.json(EMPTY);

  const games = (cfg.games || []).filter((g) => g.enabled !== false);
  const events = games.flatMap(expand).sort((a, b) => a.date.localeCompare(b.date));

  return NextResponse.json({
    updated_at: cfg.updated_at || null,
    games: games.map((g) => ({ id: g.id, name: g.name, color: g.color, source: g.source || '' })),
    events,
  });
}
