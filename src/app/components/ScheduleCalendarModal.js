'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from './ScheduleCalendarModal.module.css';

const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土'];
const MAX_LANES = 5; // これ以上重なったら「+N件」で畳む

function toDateOnly(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function parseDate(str) {
  if (!str) return null;
  const d = new Date(`${str}T00:00:00+09:00`);
  return Number.isNaN(d.getTime()) ? null : toDateOnly(d);
}

// 日付の加減算はローカル時刻の日付部分だけで行う。
// parseDate が JST 基準で「その日の0時」を作っているので、
// ここで時差をまたぐ演算を挟むと1日ずれる余地が生まれる。
function addDays(d, n) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
}

const ONE_DAY = 24 * 60 * 60 * 1000;

export default function ScheduleCalendarModal({ isOpen, onClose, events }) {
  const [viewDate, setViewDate] = useState(() => new Date());
  // 競合タイトルのアップデート日。鳴潮の予定とは別系統で持ち、表示は個別に切り替えられる。
  const [rivalGames, setRivalGames] = useState([]);
  const [rivalEvents, setRivalEvents] = useState([]);
  const [hiddenGames, setHiddenGames] = useState(() => new Set());

  const fetchRivals = useCallback(async () => {
    try {
      const res = await fetch('/api/rival-schedule', { cache: 'no-store' });
      const data = await res.json();
      setRivalGames(Array.isArray(data.games) ? data.games : []);
      setRivalEvents(Array.isArray(data.events) ? data.events : []);
    } catch (err) {
      // 取得できなくても鳴潮側のカレンダーは出したいので、握って続行する
      console.error('Failed to load rival schedule:', err);
    }
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    // 開いたときに読み直す。データファイルを直したあと、開き直せば反映される。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchRivals();
  }, [isOpen, fetchRivals]);

  const toggleGame = (id) => {
    setHiddenGames((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (!isOpen) return null;

  const year = viewDate.getFullYear();
  const month = viewDate.getMonth(); // 0-indexed
  const today = toDateOnly(new Date());

  const firstOfMonth = new Date(year, month, 1);
  const firstWeekday = firstOfMonth.getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const totalCells = Math.ceil((firstWeekday + daysInMonth) / 7) * 7;
  const gridStart = addDays(firstOfMonth, -firstWeekday);

  const weeks = [];
  for (let w = 0; w < totalCells / 7; w++) {
    const weekStart = addDays(gridStart, w * 7);
    weeks.push(Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)));
  }

  // start_date/end_date を持つイベントを正規化。end_date が無い(単発)ものは単日として扱う。
  // 期間が長い予定を先に並べ、レーン割り当て時に上段へ来やすくして見やすくする。
  const normalizedOwn = (events || [])
    .map((ev) => {
      const s = parseDate(ev.start_date);
      if (!s) return null;
      const e = parseDate(ev.end_date) || s;
      return e < s ? { ...ev, _start: s, _end: s } : { ...ev, _start: s, _end: e };
    })
    .filter(Boolean);

  // 終了日が入っていない予定は、そのバージョンが終わる日まで伸ばす。
  // 伸ばさないと幅が1日しかなく、キャラ名やイベント名が読めない。
  //
  // バージョンだけを対象にしていた時期があったが、ガチャ・イベント・ストーリーも
  // 同じ状態だった（Ver3.6の8件が全部1日分になっていた）。未発表の新バージョンは
  // 個別の終了日が出ていないことが多く、これは今後も繰り返し起きる。
  const versionStarts = normalizedOwn
    .filter((ev) => ev.category === 'version')
    .map((ev) => ev._start)
    .sort((a, b) => a - b);

  // そのバージョンの実際の終了日が分かっていれば、それを共通の終端として使う。
  // 6週間で一律に伸ばすと、5週間で終わる回では次のバージョンへ食い込む。
  const versionEnds = normalizedOwn
    .filter((ev) => ev.category === 'version' && ev.end_date)
    .map((ev) => ({ start: ev._start, end: ev._end }))
    .sort((a, b) => a.start - b.start);

  normalizedOwn.forEach((ev) => {
    if (ev.end_date) return;
    // 1) 自分が属するバージョンの終了日（判明していれば最優先）
    const owner = versionEnds.filter((v) => v.start <= ev._start).pop();
    if (owner && owner.end >= ev._start) {
      ev._end = owner.end;
      ev._inferredEnd = true;
      return;
    }
    // 2) 次のバージョンが始まる前日まで
    const next = versionStarts.find((d) => d > ev._start);
    // 3) どちらも無ければ更新周期(6週間)ぶん
    ev._end = next ? addDays(next, -1) : addDays(ev._start, 41);
    ev._inferredEnd = true;
  });

  // 競合タイトルのアップデートは単日の印として扱う。
  // 期間の長い鳴潮の予定を上段に出したいので、こちらは後ろに並べる。
  const rivalNormalized = rivalEvents
    .filter((ev) => !hiddenGames.has(ev.game_id))
    .map((ev) => {
      const s2 = parseDate(ev.date);
      if (!s2) return null;
      // 新キャラ実装がある回だけ印を付ける。読み取れなかった場合(null)は何も出さない。
      // 「無し」と断言できないものを「無し」に見せないため。
      const newChar = ev.newCharacter === true;
      return {
        character: `${ev.label || ev.game}${newChar ? ' 🆕' : ''}`,
        event: (ev.phase ? `アップデート ${ev.phase}` : 'アップデート') + (newChar ? '・新キャラ実装あり' : ''),
        category: 'rival',
        confirmed: ev.confirmed,
        _color: ev.color,
        _note: ev.note,
        _start: s2,
        _end: s2,
      };
    })
    .filter(Boolean);

  // 競合分は鳴潮の予定と同じ場所に並べない。
  // 単日なのでレーン割り当てでは最後尾に回り、予定が多い週だと「他N件」に
  // 畳まれて消えてしまう（実際に原神のアップデートが隠れた）。専用の行に出す。
  const normalizedEvents = [...normalizedOwn].sort(
    (a, b) => (b._end - b._start) - (a._end - a._start)
  );

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <button className={styles.navBtn} onClick={() => setViewDate(new Date(year, month - 1, 1))}>◀</button>
          <h3 className={styles.title}>{year}年{month + 1}月</h3>
          <button className={styles.navBtn} onClick={() => setViewDate(new Date(year, month + 1, 1))}>▶</button>
          <button className={styles.todayBtn} onClick={() => setViewDate(new Date())}>今日</button>
          <button className={styles.closeBtn} onClick={onClose}>×</button>
        </div>

        {rivalGames.length > 0 && (
          <div className={styles.gameFilterRow}>
            <span className={styles.gameFilterLabel}>他タイトル:</span>
            {rivalGames.map((g) => {
              const on = !hiddenGames.has(g.id);
              return (
                <button
                  key={g.id}
                  className={`${styles.gameChip} ${on ? styles.gameChipOn : ''}`}
                  style={on ? { borderColor: g.color, color: g.color } : {}}
                  onClick={() => toggleGame(g.id)}
                  title={on ? 'クリックで非表示' : 'クリックで表示'}
                >
                  <span className={styles.gameChipDot} style={{ background: g.color }} />
                  {g.name}
                </button>
              );
            })}
          </div>
        )}

        <div className={styles.weekdaysRow}>
          {WEEKDAYS.map((w) => (
            <div key={w} className={styles.weekdayCell}>{w}</div>
          ))}
        </div>

        {weeks.map((days, wi) => {
          const weekStart = days[0];
          const weekEnd = days[6];

          const weekEvents = normalizedEvents.filter(
            (ev) => ev._start <= weekEnd && ev._end >= weekStart
          );

          // 貪欲法でレーン(段)を割り当て、同じ週内で期間が重ならない予定は同じ段を使い回す
          const placed = [];
          weekEvents.forEach((ev) => {
            const startCol = Math.max(0, Math.round((ev._start - weekStart) / ONE_DAY));
            const endCol = Math.min(6, Math.round((ev._end - weekStart) / ONE_DAY));
            let lane = 0;
            while (placed.some((p) => p.lane === lane && !(endCol < p.startCol || startCol > p.endCol))) {
              lane++;
            }
            placed.push({ ev, lane, startCol, endCol });
          });

          const visible = placed.filter((p) => p.lane < MAX_LANES);
          const hiddenCount = placed.length - visible.length;
          const laneCount = visible.reduce((m, p) => Math.max(m, p.lane), -1) + 1;

          return (
            <div key={wi} className={styles.weekBlock}>
              <div className={styles.dayNumRow}>
                {days.map((d, di) => {
                  const inMonth = d.getMonth() === month;
                  const isToday = d.getTime() === today.getTime();
                  return (
                    <div
                      key={di}
                      className={`${styles.dayNumCell} ${!inMonth ? styles.dayNumOutside : ''} ${isToday ? styles.dayNumToday : ''}`}
                    >
                      {d.getDate()}
                    </div>
                  );
                })}
              </div>

              {(() => {
                const marks = days.map((d) =>
                  rivalNormalized.filter((ev) => ev._start.getTime() === d.getTime())
                );
                if (!marks.some((m) => m.length)) return null;
                return (
                  <div className={styles.rivalRow}>
                    {marks.map((list, di) => (
                      <div key={di} className={styles.rivalCell}>
                        {list.map((ev, ei) => (
                          <span
                            key={ei}
                            className={`${styles.rivalChip} ${ev.confirmed ? '' : styles.rivalChipUnconfirmed}`}
                            style={{ borderLeftColor: ev._color, color: ev._color }}
                            title={`${ev.character}（${ev.event}）${ev.confirmed ? '' : ' [未確定]'}${ev._note ? ` ${ev._note}` : ''}`}
                          >
                            {ev.character}
                          </span>
                        ))}
                      </div>
                    ))}
                  </div>
                );
              })()}

              {laneCount > 0 && (
                <div className={styles.barsArea} style={{ gridTemplateRows: `repeat(${laneCount}, auto)` }}>
                  {visible.map((p, i) => {
                    const isEvent = p.ev.category === 'event';
                    const isRival = p.ev.category === 'rival';
                    const startsHere = p.ev._start >= weekStart;
                    const endsHere = p.ev._end <= weekEnd;
                    return (
                      <div
                        key={i}
                        className={[
                          styles.eventBar,
                          isRival ? styles.eventBarRival : isEvent ? styles.eventBarEvent : styles.eventBarImportant,
                          !p.ev.confirmed ? styles.eventBarUnconfirmed : '',
                          !startsHere ? styles.barOpenLeft : '',
                          !endsHere ? styles.barOpenRight : '',
                        ].join(' ')}
                        style={{
                          gridColumn: `${p.startCol + 1} / ${p.endCol + 2}`,
                          gridRow: p.lane + 1,
                          ...(isRival ? { borderLeftColor: p.ev._color, color: p.ev._color } : {}),
                        }}
                        title={
                          `${p.ev.character}（${p.ev.event}）` +
                          `${p.ev.confirmed ? '' : ' [未確定]'}` +
                          `${p.ev._inferredEnd ? ' ※終了日は未発表のためバージョン期間で表示' : ''}` +
                          `${p.ev._note ? ` ${p.ev._note}` : ''}`
                        }
                      >
                        {/* 週をまたぐ帯は各週で見出しを出す。開始週だけだと2週目以降が無地になり、
                            どの期間が何なのか分からなくなる。 */}
                        {p.endCol - p.startCol >= 1 || startsHere ? p.ev.character : ''}
                      </div>
                    );
                  })}
                </div>
              )}

              {hiddenCount > 0 && (
                <div className={styles.moreLabel}>他 {hiddenCount} 件</div>
              )}
            </div>
          );
        })}

        <p className={styles.legend}>
          <span className={styles.legendDot} /> 重要項目（キャラ/武器/バージョン）
          <span className={`${styles.legendDot} ${styles.legendDotEvent}`} /> ゲーム内イベント
          <span className={`${styles.legendDot} ${styles.legendDotUnconfirmed}`} /> 未確定（リーク・予想）
          <span className={styles.legendSep}>|</span>
          他タイトルは枠線の色で区別。🆕は新キャラ実装あり。点線は更新周期からの推定で、公式発表ではありません。
        </p>
      </div>
    </div>
  );
}
