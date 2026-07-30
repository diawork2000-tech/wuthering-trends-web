'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import styles from './page.module.css';

export default function IntelligenceStudioPage() {
  const [topics, setTopics] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedTopic, setSelectedTopic] = useState(null);
  const [filter, setFilter] = useState('すべて');
  const [copied, setCopied] = useState(false);

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
      } else {
        alert('動画ネタデータの読込に失敗しました。');
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
    if (filter === 'Togetter / X') return item.sourceType.toLowerCase().includes('togetter') || item.sourceType.toLowerCase().includes('twitter') || item.sourceType.toLowerCase().includes('rss');
    if (filter === 'YouTube 競合') return item.sourceType.toLowerCase().includes('youtube');
    return true;
  });

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.leftNav}>
          <Link href="/" className={styles.backBtn}>
            ◀ 動画トレンド・メインギャラリーに戻る (同一タブ)
          </Link>
          <div className={styles.titleArea}>
            <h1>📚 AIショート動画台本 ＆ ネタ発掘ライブラリ</h1>
            <p>1日数百件の海外Reddit(和訳済)やバズポストから選抜されたゴールデン台本スタジオ</p>
          </div>
        </div>
        <div className={styles.headerActions}>
          <div className={styles.badge}>
            ✨ 7日超 古いカード自動自浄機能つき
          </div>
          <button className={styles.refreshBtn} onClick={fetchTopics}>
            🔄 最新ネタを同期
          </button>
        </div>
      </header>

      {loading ? (
        <div className={styles.emptyState}>
          <div className={styles.spinner} />
          <p>⚡ クラウド Notion ラックから最新ショートネタ一覧を引き出し中...</p>
        </div>
      ) : topics.length === 0 ? (
        <div className={styles.emptyState}>
          <p>📭 現在保存されている有効な動画ネタはありません。次回 20分 定期巡回をお待ちください！</p>
        </div>
      ) : (
        <div className={styles.mainBody}>
          {/* 左側：セレクトカード一覧 */}
          <section className={styles.listColumn}>
            <div className={styles.filterBar}>
              {['すべて', 'Reddit', 'Togetter / X', 'YouTube 競合'].map((btn) => (
                <button
                  key={btn}
                  className={`${styles.filterBtn} ${filter === btn ? styles.filterActive : ''}`}
                  onClick={() => setFilter(btn)}
                >
                  {btn}
                </button>
              ))}
            </div>

            <div className={styles.cardScrollArea}>
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
                    🚀 一次ソース元のページを直接チェックする ( 100% 直リンク確認済 )
                  </a>
                )}
              </>
            ) : (
              <div style={{ textAlign: 'center', padding: '5rem', color: '#64748b' }}>
                👈 左側のリストから興味のあるショート動画ネタを選択してください。
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
