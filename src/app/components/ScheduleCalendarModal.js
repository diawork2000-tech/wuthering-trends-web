'use client';

import { useState } from 'react';
import styles from './ScheduleCalendarModal.module.css';

const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土'];

function pad(n) {
  return String(n).padStart(2, '0');
}

function dateKey(year, monthIndex, day) {
  return `${year}-${pad(monthIndex + 1)}-${pad(day)}`;
}

export default function ScheduleCalendarModal({ isOpen, onClose, events }) {
  const [viewDate, setViewDate] = useState(() => new Date());

  if (!isOpen) return null;

  const year = viewDate.getFullYear();
  const month = viewDate.getMonth(); // 0-indexed
  const todayKey = (() => {
    const t = new Date();
    return dateKey(t.getFullYear(), t.getMonth(), t.getDate());
  })();

  const firstWeekday = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const cells = [];
  for (let i = 0; i < firstWeekday; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);

  // start_date のみを対象にした簡易カレンダー（期間表示は今後の拡張余地）
  const eventsByDate = {};
  (events || []).forEach((ev) => {
    if (!ev.start_date) return;
    if (!eventsByDate[ev.start_date]) eventsByDate[ev.start_date] = [];
    eventsByDate[ev.start_date].push(ev);
  });

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

        <div className={styles.grid}>
          {cells.map((d, idx) => {
            if (d === null) return <div key={idx} className={styles.emptyCell} />;
            const key = dateKey(year, month, d);
            const dayEvents = eventsByDate[key] || [];
            const isToday = key === todayKey;
            return (
              <div key={idx} className={`${styles.dayCell} ${isToday ? styles.todayCell : ''}`}>
                <span className={styles.dayNum}>{d}</span>
                {dayEvents.slice(0, 3).map((ev, i) => (
                  <div
                    key={i}
                    className={`${styles.eventChip} ${!ev.confirmed ? styles.unconfirmedChip : ''}`}
                    title={`${ev.character}（${ev.event}）${ev.confirmed ? '' : ' [未確定]'}`}
                  >
                    {ev.character}
                  </div>
                ))}
                {dayEvents.length > 3 && (
                  <div className={styles.moreLabel}>+{dayEvents.length - 3}件</div>
                )}
              </div>
            );
          })}
        </div>

        <p className={styles.legend}>
          <span className={styles.legendDot} /> 公式確定
          <span className={`${styles.legendDot} ${styles.legendDotUnconfirmed}`} /> 未確定（リーク・予想）
        </p>
      </div>
    </div>
  );
}
