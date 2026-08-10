'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import styles from './page.module.css';
import PickupCard from './PickupCard';

// ピックアップ（採用）済みの一覧。
// YouTube動画DBとトレンド企画DBの両方から採用済みを集め、重複を除いて並べる。
// ここでの「解除」は採用チェックを外すだけで、収集した行そのものは消さない。

export default function PickupsPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [confirming, setConfirming] = useState(null); // 'selected' | 'all' | null
  const [zoomLevel, setZoomLevel] = useState(300);

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

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.leftNav}>
          {/* 両方の収集画面から来られるので、両方へ戻れるようにしてある */}
          <div className={styles.backLinks}>
            <Link href="/" className={styles.backBtn}>
              ◀ 🎥 YouTubeトレンド収集
            </Link>
            <Link href="/intelligence" className={styles.backBtn}>
              ◀ 🌐 マルチメディア収集
            </Link>
          </div>
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

        <div className={styles.zoomControl}>
          <span title="カードを小さく">➖</span>
          <input
            type="range"
            min="220"
            max="520"
            step="20"
            value={zoomLevel}
            onChange={(e) => setZoomLevel(Number(e.target.value))}
            className={styles.zoomSlider}
          />
          <span title="カードを大きく">➕</span>
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
          <div className={styles.gallery} style={{ '--card-width': `${zoomLevel}px` }}>
            {items.map((item) => (
              <PickupCard
                key={item.id}
                item={item}
                selected={selected.has(item.id)}
                onToggleSelect={toggleSelect}
                onChangeStatus={changeStatus}
                onRemove={(i) => release([i], 'このネタ')}
                busy={busy}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
