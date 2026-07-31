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
  const [gridCols, setGridCols] = useState(2); // ズーム列数：初期は標準2列
  const [logs, setLogs] = useState([]);
  const [showLogs, setShowLogs] = useState(false); // 活動実績ログの開閉ステート
  const [triggering, setTriggering] = useState(false);
  const [triggerMsg, setTriggerMsg] = useState('');
  const scrollAreaRef = useRef(null);

  useEffect(() => {
    fetchTopics();
    fetchLogs();
  }, []);

  const handleManualTrigger = async () => {
    if (triggering) return;
    setTriggering(true);
    setTriggerMsg('⏳ クラウド自動発掘エンジンへ即時起動シグナルを送信中...');
    try {
      const res = await fetch('/api/intelligence_cron', { method: 'POST', cache: 'no-store' });
      if (res.ok) {
        setTriggerMsg('🚀 起動成功！現在クラウドAIがバックグラウンドで全力全巡回を開始しました！1〜2分後にお手元の「🔄 更新」ボタンを押して最新カードをお確かめください！');
      } else {
        setTriggerMsg('❌ 起動シグナル送信に問題が発生しました。しばらく時間をおいてから再度お試しください。');
      }
    } catch (e) {
      setTriggerMsg('❌ ネットワーク通信エラーが発生しました。');
    } finally {
      setTriggering(false);
      setTimeout(() => setTriggerMsg(''), 15000);
    }
  };

  const fetchTopics = async () => {
    setLoading(true);
    try {
      const timestamp = new Date().getTime();
      const res = await fetch(`/api/intelligence?_t=${timestamp}`, {
        cache: 'no-store',
        headers: { 'Cache-Control': 'no-cache, no-store, max-age=0, must-revalidate' }
      });
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

  const fetchLogs = async () => {
    try {
      const timestamp = new Date().getTime();
      const res = await fetch(`/api/intelligence_logs?_t=${timestamp}`, {
        cache: 'no-store',
        headers: { 'Cache-Control': 'no-cache, no-store, max-age=0, must-revalidate' }
      });
      if (res.ok) {
        const data = await res.json();
        setLogs(data.logs || []);
      }
    } catch (err) {
      console.error('Logs Error:', err);
    }
  };

  const filteredTopics = topics.filter((item) => {
    const st = str(item.sourceType || '').toLowerCase();
    const su = str(item.sourceUrl || '').toLowerCase();
    
    if (filter === 'すべて') return true;
    if (filter === 'Reddit') {
      return st.includes('reddit') || su.includes('reddit');
    }
    if (filter === 'YouTube') {
      const isYouTube = st.includes('youtube') || su.includes('youtube') || su.includes('youtu.be');
      return isYouTube;
    }
    if (filter === 'その他') {
      const isReddit = st.includes('reddit') || su.includes('reddit');
      const isYouTube = st.includes('youtube') || su.includes('youtube') || su.includes('youtu.be');
      return !isReddit && !isYouTube;
    }
    return true;
  });

  function str(val) {
    return typeof val === 'string' ? val : String(val || '');
  }

  const getYouTubeId = (url) => {
    if (!url || typeof url !== 'string') return null;
    const regExp = /(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=|shorts\/)|youtu\.be\/)([^"&?\/\s]{11})/i;
    const match = url.match(regExp);
    return match && match[1].length === 11 ? match[1] : null;
  };

  const renderThumbnail = (topic) => {
    const st = str(topic.sourceType).toLowerCase();
    const su = str(topic.sourceUrl).toLowerCase();
    
    if (st.includes('youtube') || su.includes('youtube') || su.includes('youtu.be')) {
      let vid = getYouTubeId(topic.sourceUrl);
      if (!vid && topic.thumbnailUrl) {
        return (
          <div className={styles.thumbnailWrapper}>
            <img src={topic.thumbnailUrl} alt={topic.title} className={styles.thumbnailImg} loading="lazy" />
            <span className={styles.thumbPlayIcon}>▶</span>
          </div>
        );
      }
      if (vid) {
        const thumbUrl = `https://img.youtube.com/vi/${vid}/hqdefault.jpg`;
        return (
          <div className={styles.thumbnailWrapper}>
            <img src={thumbUrl} alt={topic.title} className={styles.thumbnailImg} loading="lazy" />
            <span className={styles.thumbPlayIcon}>▶</span>
          </div>
        );
      }
      return (
        <div className={styles.thumbnailWrapperFallback}>
          <span className={styles.thumbFallbackLogo}>📺 YouTube バズ解析</span>
        </div>
      );
    }
    return null;
  };

  const zoomIn = () => {
    setGridCols((prev) => Math.max(1, prev - 1));
  };

  const zoomOut = () => {
    setGridCols((prev) => Math.min(4, prev + 1));
  };

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

  const getGridStyle = () => {
    switch (gridCols) {
      case 1:
        return { gridTemplateColumns: 'repeat(1, 1fr)', gap: '1.1rem' };
      case 2:
        return { gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.9rem' };
      case 3:
        return { gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem' };
      case 4:
        return { gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.6rem' };
      default:
        return { gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.9rem' };
    }
  };

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.leftNav}>
          <Link href="/" className={styles.backBtn}>
            ◀ メインギャラリーへ
          </Link>
          <div className={styles.titleArea}>
            <h1>📚 鳴潮トレンド・ネタ自動発掘スタジオ</h1>
            <p>海外Reddit・YouTube競合動向・最強攻略をダブりゼロで継続発掘</p>
          </div>
        </div>
        <div className={styles.headerActions}>
          <button 
            className={styles.triggerBtn} 
            onClick={handleManualTrigger} 
            disabled={triggering}
            title="ワンクリックで今すぐクラウド発掘とAI深層解析を実行します"
          >
            {triggering ? '⚡ 起動発信中...' : '⚡ 今すぐ即時発掘を実行'}
          </button>
          <button 
            className={`${styles.logToggleBtn} ${showLogs ? styles.logToggleActive : ''}`} 
            onClick={() => setShowLogs(!showLogs)}
            title="活動実績と内訳ログを確認"
          >
            📜 {showLogs ? 'ログを閉じる' : '活動実績ログ'} ({logs.length})
          </button>
          <div className={styles.badge}>
            ✨ 自動更新 ＆ ダブり排除稼働中
          </div>
          <button className={styles.refreshBtn} onClick={() => { fetchTopics(); fetchLogs(); }}>
            🔄 更新
          </button>
        </div>
      </header>

      {triggerMsg && (
        <div className={styles.triggerBanner}>
          {triggerMsg}
        </div>
      )}

      {/* 📜 美麗・トグル式 収集活動＆実績ログ ダッシュボード */}
      {showLogs && (
        <section className={styles.logDashboard}>
          <div className={styles.logHeader}>
            <h3>🚀 定期AI巡回 ＆ ショート企画ハント 活動実績ヒストリー</h3>
            <span className={styles.logSubText}>※ 各便における収穫数・厳選採用数・各プラットフォーム別メディア内訳をリアルタイム監視</span>
          </div>
          <div className={styles.logTableContainer}>
            {logs.length === 0 ? (
              <p className={styles.noLogsText}>現在記録された活動ログはありません。間もなく第一便の実戦完了が記録されます！</p>
            ) : (
              <table className={styles.logTable}>
                <thead>
                  <tr>
                    <th>実行完了タイムスタンプ (JST)</th>
                    <th>ステータス</th>
                    <th>収穫総数 ➔ 採用件数</th>
                    <th>プラットフォーム別・獲得実績内訳 (多様性バリュー)</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((log, index) => (
                    <tr key={index}>
                      <td className={styles.logTimeCell}>🕒 {log.timestamp}</td>
                      <td>
                        <span className={styles.logStatusSuccess}>● {log.status || 'Success'}</span>
                      </td>
                      <td className={styles.logCountCell}>
                        計 <strong>{log.total_harvested || '-'}</strong> 件探索 ➔ <span className={styles.selectedHighlight}>{log.final_selected || '12'}件厳選！</span>
                      </td>
                      <td>
                        <div className={styles.breakdownTags}>
                          {log.breakdown ? (
                            Object.entries(log.breakdown).map(([media, cnt]) => (
                              <span key={media} className={styles.mediaTag}>
                                {media}: <strong>{cnt}</strong>件
                              </span>
                            ))
                          ) : (
                            <span className={styles.mediaTag}>バランス最適抽出完了</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>
      )}

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
          <section className={styles.listColumn}>
            <div className={styles.listHeaderRow}>
              <div className={styles.filterBar}>
                {['すべて', 'Reddit', 'YouTube', 'その他'].map((btn) => (
                  <button
                    key={btn}
                    className={`${styles.filterBtn} ${filter === btn ? styles.filterActive : ''}`}
                    onClick={() => setFilter(btn)}
                  >
                    {btn}
                  </button>
                ))}
              </div>

              <div className={styles.zoomControlBar}>
                <span className={styles.zoomLabel}>🔍 列数切替 : </span>
                <button 
                  className={styles.zoomBtn} 
                  onClick={zoomIn} 
                  disabled={gridCols === 1}
                  title="拡大して詳細表示 (列数を減らす)"
                >
                  ➕ 拡大
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
                  ➖ 縮小
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
                const thumbElem = renderThumbnail(topic);
                return (
                  <div
                    key={topic.id}
                    className={`${styles.topicCard} ${isSelected ? styles.activeCard : ''}`}
                    onClick={() => setSelectedTopic(topic)}
                  >
                    {thumbElem && <div className={styles.cardThumbArea}>{thumbElem}</div>}
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

          <section className={styles.studioColumn}>
            {selectedTopic ? (
              <>
                <div className={styles.studioTitleRow}>
                  {(() => {
                    const ytId = getYouTubeId(selectedTopic.sourceUrl);
                    if (ytId) {
                      return (
                        <div className={styles.studioVideoContainer}>
                          <iframe
                            className={styles.youtubeIframe}
                            src={`https://www.youtube.com/embed/${ytId}?rel=0`}
                            title="YouTube video player"
                            frameBorder="0"
                            allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                            allowFullScreen
                          ></iframe>
                        </div>
                      );
                    }
                    return renderThumbnail(selectedTopic) ? (
                      <div className={styles.studioThumbPreview}>
                        {renderThumbnail(selectedTopic)}
                      </div>
                    ) : null;
                  })()}
                  <div className={styles.studioMeta}>
                    <span className={styles.sourceBadge} style={{ fontSize: '0.85rem', padding: '0.35rem 0.85rem' }}>
                      {selectedTopic.sourceType}
                    </span>
                    <span style={{ color: '#94a3b8', fontSize: '0.85rem' }}>
                      🕒 {selectedTopic.date}
                    </span>
                  </div>
                  <h2 className={styles.studioTitle}>{selectedTopic.title}</h2>
                </div>

                <div className={styles.scriptSection}>
                  <div className={styles.sectionHeading}>
                    <span>📄 動画・記事の網羅的詳細 (全容解説)</span>
                  </div>
                  <div className={styles.scriptBox}>{selectedTopic.scriptOutline}</div>
                </div>

                <div className={styles.reasonSection}>
                  <div className={styles.reasonTitle}>💡 バズ予測と注目ポイント</div>
                  <p className={styles.reasonText}>{selectedTopic.reason}</p>
                </div>

                {selectedTopic.sourceUrl && (
                  <a
                    href={selectedTopic.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={styles.externalBtn}
                  >
                    {getYouTubeId(selectedTopic.sourceUrl) ? '📺 YouTubeで開く ↗' : '🌐 元サイトを開く ↗'}
                  </a>
                )}
              </>
            ) : (
              <div className={styles.emptyState} style={{ height: '350px' }}>
                <p>👈 左のリストから気になるトピックを選択すると、動画の自動再生や記事詳細を確認できます</p>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
