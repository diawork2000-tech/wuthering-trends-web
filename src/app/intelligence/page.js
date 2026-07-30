'use client';

import { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import styles from './page.module.css';

export default function IntelligenceStudioPage() {
  const [topics, setTopics] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedTopic, setSelectedTopic] = useState(null);
  const [filter, setFilter] = useState('すべて');
  const [copied, setCopied] = useState(false);
  const [gridCols, setGridCols] = useState(2); // ズーム列数：初期2列
  const scrollAreaRef = useRef(null);

  useEffect(() => {
    fetchTopics();
  }, []);

  const fetchTopics = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/intelligence');
      if (res.ok) {
        const data = await res.json();
        const items = data.items || [];
        setTopics(items);
        if (items.length > 0 && !selectedTopic) {
          setSelectedTopic(items[0]);
        }
      }
    } catch (err) {
      console.error('Error:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleCopyScript = () => {
    if (!selectedTopic) return;
    const textToCopy = `【見出し】${selectedTopic.title}\n【メディア】${selectedTopic.sourceType}\n【動画台本構成】\n${selectedTopic.scriptOutline}\n\n【期待値と根拠】\n${selectedTopic.reason}\n【一次ソース】${selectedTopic.sourceUrl}`;
    navigator.clipboard.writeText(textToCopy);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  const filteredTopics = topics.filter((item) => {
    if (filter === 'すべて') return true;
    if (filter === 'Reddit') return item.sourceType.toLowerCase().includes('reddit');
    if (filter === 'TikTok / 攻略 / SNS') return !item.sourceType.toLowerCase().includes('reddit');
    return true;
  });

  // ズーム（列の増減）ハンドラ
  const zoomIn = () => {
    // ズームイン ➔ 大きくする ➔ 列数を減らす (最小1列)
    setGridCols((prev) => Math.max(1, prev - 1));
  };

  const zoomOut = () => {
    // ズームアウト ➔ 一望を広げる ➔ 列数を増やす (最大4列)
    setGridCols((prev) => Math.min(4, prev + 1));
  };

  // Ctrl + マウスホイールでヌルヌル動的に拡大縮小
  const handleWheel = (e) => {
    if (e.ctrlKey) {
      e.preventDefault();
      if (e.deltaY < 0) {
        zoomIn();
      } else {
        zoomOut();
      }
    }
  };

  // グリッドスタイル動的最適化
  const getGridStyle = () => {
    switch (gridCols) {
      case 1:
        return { gridTemplateColumns: '1fr', gap: '1rem' };
      case 2:
        return { gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '0.9rem' };
      case 3:
        return { gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))', gap: '0.7rem' };
      case 4:
        return { gridTemplateColumns: 'repeat(auto-fill, minmax(165px, 1fr))', gap: '0.55rem' };
      default:
        return { gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' };
    }
  };

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.leftNav}>
          <Link href="/" className={styles.backBtn}>
            ◀ 動画トレンド・メインギャラリーに戻る (同一タブ)
          </Link>
          <div className={styles.titleArea}>
            <h1>📚 AIショート動画台本 ＆ ネタ発掘ライブラリ</h1>
            <p>1日数百件の海外Reddit(完全和訳)やSNSトレンドから選抜されたゴールデン台本スタジオ</p>
          </div>
        </div>
        <div className={styles.headerActions}>
          <div className={styles.badge}>
            ✨ 7日超 古いカード自動自浄＆翻訳ガード標準装備
          </div>
          <button className={styles.refreshBtn} onClick={fetchTopics}>
            🔄 最新ネタを同期
          </button>
        </div>
      </header>

      {loading ? (
        <div className={styles.emptyState}>
          <div className={styles.spinner} />
          <p>⚡ クラウド Notion ラックおよび安心キャッシュから最新ショートネタ一覧を引き出し中...</p>
        </div>
      ) : topics.length === 0 ? (
        <div className={styles.emptyState}>
          <p>📭 現在保存されている有効な動画ネタはありません。次回 20分 定期巡回便をお待ちください！</p>
        </div>
      ) : (
        <div className={styles.mainBody}>
          {/* 左側：セレクトカード一覧＆ズーム・スケーリングコントロール */}
          <section className={styles.listColumn}>
            <div className={styles.listHeaderRow}>
              <div className={styles.filterBar}>
                {['すべて', 'Reddit', 'TikTok / 攻略 / SNS'].map((btn) => (
                  <button
                    key={btn}
                    className={`${styles.filterBtn} ${filter === btn ? styles.filterActive : ''}`}
                    onClick={() => setFilter(btn)}
                  >
                    {btn}
                  </button>
                ))}
              </div>

              {/* グリッドズームイン・アウト調整コントローラー */}
              <div className={styles.zoomControlBar}>
                <span className={styles.zoomLabel}>🔍 表示列ズーム : </span>
                <button 
                  className={styles.zoomBtn} 
                  onClick={zoomIn} 
                  disabled={gridCols === 1}
                  title="拡大して詳細表示 (列数を減らす)"
                >
                  ➕ 拡大 (詳細)
                </button>
                <div className={styles.colButtonGroup}>
                  {[1, 2, 3, 4].map((col) => (
                    <button
                      key={col}
                      className={`${styles.colBtn} ${gridCols === col ? styles.colBtnActive : ''}`}
                      onClick={() => setGridCols(col)}
                    >
                      {col}列
                    </button>
                  ))}
                </div>
                <button 
                  className={styles.zoomBtn} 
                  onClick={zoomOut} 
                  disabled={gridCols === 4}
                  title="縮小して一望表示 (列数を増やす)"
                >
                  ➖ 縮小 (俯瞰)
                </button>
              </div>
            </div>

            <div 
              className={`${styles.cardScrollArea} ${styles[`zoomLevel${gridCols}`]}`}
              style={getGridStyle()}
              ref={scrollAreaRef}
              onWheel={handleWheel}
            >
              {filteredTopics.map((topic) => {
                const isSelected = selectedTopic && selectedTopic.id === topic.id;
                return (
                  <div
                    key={topic.id}
                    className={`${styles.topicCard} ${isSelected ? styles.activeCard : ''}`}
                    onClick={() => setSelectedTopic(topic)}
                  >
                    <div className={styles.cardHeader}>
                      <span className={styles.sourceBadge}>{topic.sourceType}</span>
                      <span className={styles.cardDate}>{topic.date}</span>
                    </div>
                    <div className={styles.cardTitle}>{topic.title}</div>
                    <div className={styles.cardSnippet}>{topic.scriptOutline}</div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* 右側：没入型・スタジオ台本メインエディター */}
          <section className={styles.studioColumn}>
            {selectedTopic ? (
              <>
                <div className={styles.studioTitleRow}>
                  <div className={styles.studioMeta}>
                    <span className={styles.sourceBadge} style={{ fontSize: '0.9rem', padding: '0.4rem 1rem' }}>
                      {selectedTopic.sourceType}
                    </span>
                    <span style={{ color: '#94a3b8', fontSize: '0.9rem' }}>
                      🕒 登録日 : {selectedTopic.date}
                    </span>
                  </div>
                  <h2 className={styles.studioTitle}>{selectedTopic.title}</h2>
                </div>

                <div className={styles.scriptSection}>
                  <div className={styles.sectionHeading}>
                    <span>🎬 冒頭 3 秒 ＆ 3行ショート台本骨格</span>
                    <button className={styles.copyBtn} onClick={handleCopyScript}>
                      {copied ? '✅ クリップボードへ保存しました！' : '📋 この台本＆論点をコピー'}
                    </button>
                  </div>
                  <div className={styles.scriptBox}>{selectedTopic.scriptOutline}</div>
                </div>

                <div className={styles.reasonSection}>
                  <div className={styles.reasonTitle}>💡 なぜこのトピックがファン層にバズるかの見立て</div>
                  <p className={styles.reasonText}>{selectedTopic.reason}</p>
                </div>

                {selectedTopic.sourceUrl && (
                  <a
                    href={selectedTopic.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={styles.externalBtn}
                  >
                    🚀 この記事の一次情報 ＆ 検証ページを開く (100%安全直撃リンク)
                  </a>
                )}
              </>
            ) : (
              <div className={styles.emptyState} style={{ height: '350px' }}>
                <p>👈 左の一覧（または俯瞰グリッド）から気になる動画ネタをクリックして台本を開きましょう！</p>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
