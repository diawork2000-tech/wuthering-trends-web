'use client';

import { useState } from 'react';
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

function addDays(d, n) {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

const ONE_DAY = 24 * 60 * 60 * 1000;

export default function ScheduleCalendarModal({ isOpen, onClose, events }) {
  const [viewDate, setViewDate] = useState(() => new Date());

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
  const normalizedEvents = (events || [])
    .map((ev) => {
      const s = parseDate(ev.start_date);
      if (!s) return null;
      const e = parseDate(ev.end_date) || s;
      return e < s ? { ...ev, _start: s, _end: s } : { ...ev, _start: s, _end: e };
    })
    .filter(Boolean)
    .sort((a, b) => (b._end - b._start) - (a._end - a._start));

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

              {laneCount > 0 && (
                <div className={styles.barsArea} style={{ gridTemplateRows: `repeat(${laneCount}, auto)` }}>
                  {visible.map((p, i) => {
                    const isEvent = p.ev.category === 'event';
                    const startsHere = p.ev._start >= weekStart;
                    const endsHere = p.ev._end <= weekEnd;
                    return (
                      <div
                        key={i}
                        className={[
                          styles.eventBar,
                          isEvent ? styles.eventBarEvent : styles.eventBarImportant,
                          !p.ev.confirmed ? styles.eventBarUnconfirmed : '',
                          !startsHere ? styles.barOpenLeft : '',
                          !endsHere ? styles.barOpenRight : '',
                        ].join(' ')}
                        style={{ gridColumn: `${p.startCol + 1} / ${p.endCol + 2}`, gridRow: p.lane + 1 }}
                        title={`${p.ev.character}（${p.ev.event}）${p.ev.confirmed ? '' : ' [未確定]'}`}
                      >
                        {startsHere ? p.ev.character : ''}
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
        </p>
      </div>
    </div>
  );
}
