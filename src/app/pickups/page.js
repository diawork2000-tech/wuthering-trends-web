'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import styles from './page.module.css';

// ピックアップ（採用）済みの一覧。
// YouTube動画DBとトレンド企画DBの両方から採用済みを集め、重複を除いて並べる。
// ここでの「解除」は採用チェックを外すだけで、収集した行そのものは消さない。

const STATUS_OPTIONS = ['未着手', '制作中', '投稿済み', '見送り'];

export default function PickupsPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [confirming, setConfirming] = useState(null); // 'selected' | 'all' | null

  const fetchPickups = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/pickups', { cache: 'no-store' });
      const data = await res.json();
      setItems(Array.isArray(data.items) ? data.items : []);
      setSelected(new Set());
    } catch (err) {
      console.error('Failed to load pickups:', err);
      setMessage('❌ 読み込みに失敗しました。しばらくしてから再度お試しください。');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // 初回のみ取得する。以降は明示的な操作でのみ読み直す。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchPickups();
  }, [fetchPickups]);

  const toggleSelect = (key) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const selectAll = () => setSelected(new Set(items.map((i) => i.id)));
  const clearSelection = () => setSelected(new Set());

  // 解除の実体。単体・複数・一括すべてここを通る。
  // 名寄せで束ねた行も一緒に外さないと、片方だけ採用のまま残ってしまう。
  const release = async (targets, label) => {
    if (busy || targets.length === 0) return;
    const pageIds = targets.flatMap((t) => t.linkedIds || [t.id]);

    setBusy(true);
    setMessage(`⏳ ${label}（${targets.length}件）を解除しています...`);

    const removedIds = new Set(targets.map((t) => t.id));
    const snapshot = items;
    // 通信を待たずに一覧から消す。失敗したら元に戻す。
    setItems((prev) => prev.filter((i) => !removedIds.has(i.id)));
    setSelected((prev) => {
      const next = new Set(prev);
      removedIds.forEach((id) => next.delete(id));
      return next;
    });

    try {
      const res = await fetch('/api/pickups', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: pageIds, adopted: false }),
      });
      const data = await res.json();
      if (!res.ok || data.success === false) {
        throw new Error(`一部の解除に失敗しました（${data.failed?.length ?? '?'}件）`);
      }
      setMessage(`✅ ${label} ${targets.length}件をピックアップから外しました（収集データは残っています）。`);
    } catch (err) {
      console.error('Release failed:', err);
      setItems(snapshot);
      setMessage(`❌ 解除に失敗しました。${err.message}`);
    } finally {
      setBusy(false);
      setConfirming(null);
      setTimeout(() => setMessage(''), 8000);
    }
  };

  const changeStatus = async (item, nextStatus) => {
    const prevStatus = item.status;
    setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, status: nextStatus } : i)));
    try {
      const res = await fetch('/api/pickups', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: item.linkedIds || [item.id], adopted: true, status: nextStatus }),
      });
      if (!res.ok) throw new Error('failed');
    } catch (err) {
      console.error('Status update failed:', err);
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, status: prevStatus } : i)));
    }
  };

  const selectedItems = items.filter((i) => selected.has(i.id));
  const thumbFor = (item) =>
    item.thumbnail || (item.videoId ? `https://i.ytimg.com/vi/${item.videoId}/hqdefault.jpg` : '');

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.leftNav}>
          <Link href="/intelligence" className={styles.backBtn}>
            ◀ 🌐 マルチメディア収集 へ戻る
          </Link>
          <div className={styles.titleArea}>
            <h1>📌 ピックアップ一覧</h1>
            <p>YouTube・マルチメディア両方の採用済みネタをまとめて管理</p>
          </div>
        </div>
        <div className={styles.headerActions}>
          <div className={styles.badge}>採用中 {items.length} 件</div>
          <button className={styles.refreshBtn} onClick={fetchPickups} disabled={busy || loading}>
            🔄 更新
          </button>
        </div>
      </header>

      {message && <div className={styles.messageBar}>{message}</div>}

      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <button className={styles.toolBtn} onClick={selectAll} disabled={items.length === 0}>
            ☑ すべて選択
          </button>
          <button className={styles.toolBtn} onClick={clearSelection} disabled={selected.size === 0}>
            ☐ 選択を解除
          </button>
          <span className={styles.selectionCount}>
            {selected.size > 0 ? `${selected.size} 件を選択中` : '未選択'}
          </span>
        </div>
        <div className={styles.toolbarRight}>
          <button
            className={styles.dangerBtn}
            onClick={() => setConfirming('selected')}
            disabled={selected.size === 0 || busy}
          >
            選択した {selected.size} 件を外す
          </button>
          <button
            className={styles.dangerOutlineBtn}
            onClick={() => setConfirming('all')}
            disabled={items.length === 0 || busy}
          >
            すべて外す
          </button>
        </div>
      </div>

      {confirming && (
        <div className={styles.confirmBar}>
          <span>
            {confirming === 'all'
              ? `ピックアップ ${items.length} 件すべてを一覧から外します。`
              : `選択した ${selected.size} 件を一覧から外します。`}
            {' '}収集した動画・記事そのものは消えません。
          </span>
          <div className={styles.confirmActions}>
            <button
              className={styles.dangerBtn}
              onClick={() =>
                release(confirming === 'all' ? items : selectedItems, confirming === 'all' ? '全件' : '選択分')
              }
              disabled={busy}
            >
              外す
            </button>
            <button className={styles.toolBtn} onClick={() => setConfirming(null)} disabled={busy}>
              やめる
            </button>
          </div>
        </div>
      )}

      <main className={styles.listArea}>
        {loading ? (
          <div className={styles.emptyState}>
            <div className={styles.spinner} />
            <p>ピックアップ済みのネタを集めています...</p>
          </div>
        ) : items.length === 0 ? (
          <div className={styles.emptyState}>
            <p>📭 ピックアップされたネタはまだありません。</p>
            <p className={styles.emptyHint}>
              各収集画面で「採用」をチェックすると、ここに集まります。
            </p>
          </div>
        ) : (
          <ul className={styles.list}>
            {items.map((item) => {
              const isSelected = selected.has(item.id);
              const thumb = thumbFor(item);
              return (
                <li
                  key={item.id}
                  className={`${styles.row} ${isSelected ? styles.rowSelected : ''}`}
                  onClick={() => toggleSelect(item.id)}
                >
                  <input
                    type="checkbox"
                    className={styles.checkbox}
                    checked={isSelected}
                    onChange={() => toggleSelect(item.id)}
                    onClick={(e) => e.stopPropagation()}
                    aria-label={`${item.title} を選択`}
                  />

                  <div className={styles.thumbWrap}>
                    {thumb ? (
                      // 外部サムネイルのドメインが増えても壊れないよう、あえて通常のimgを使う
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={thumb} alt="" className={styles.thumb} loading="lazy" />
                    ) : (
                      <div className={styles.thumbFallback}>📰</div>
                    )}
                  </div>

                  <div className={styles.info}>
                    <div className={styles.badgeRow}>
                      <span
                        className={`${styles.originBadge} ${
                          item.origin === 'video' ? styles.originVideo : styles.originTopic
                        }`}
                      >
                        {item.originLabel}
                      </span>
                      {item.linkedIds?.length > 1 && (
                        <span className={styles.metaBadge}>両DBに登録</span>
                      )}
                      {item.score != null && (
                        <span className={styles.metaBadge}>スコア {item.score}</span>
                      )}
                      {item.viewCount != null && item.viewCount > 0 && (
                        <span className={styles.metaBadge}>▶ {item.viewCount.toLocaleString()}</span>
                      )}
                      {item.subtitle && <span className={styles.subtitle}>{item.subtitle}</span>}
                    </div>
                    <p className={styles.title}>{item.title}</p>
                    {item.url && (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={styles.link}
                        onClick={(e) => e.stopPropagation()}
                      >
                        元のページを開く ↗
                      </a>
                    )}
                  </div>

                  <div className={styles.actions} onClick={(e) => e.stopPropagation()}>
                    <select
                      className={styles.statusSelect}
                      value={item.status || '未着手'}
                      onChange={(e) => changeStatus(item, e.target.value)}
                    >
                      {STATUS_OPTIONS.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                    <button
                      className={styles.removeBtn}
                      onClick={() => release([item], 'このネタ')}
                      disabled={busy}
                      title="この1件をピックアップから外す（データは残ります）"
                    >
                      外す
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </main>
    </div>
  );
}
