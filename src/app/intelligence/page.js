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

  // 分類を 「すべて / Reddit / YouTube / その他」 の4つへスタイリッシュ整頓！
  const filteredTopics = topics.filter((item) => {
    const st = str(item.sourceType || '').toLowerCase();
    const su = str(item.sourceUrl || '').toLowerCase();
    
    if (filter === 'すべて') return true;
    if (filter === 'Reddit') {
      return st.includes('reddit') || su.includes('reddit');
    }
    if (filter === 'YouTube') {
      return st.includes('youtube') || su.includes('youtube') || su.includes('youtu.be');
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

  // YouTube の URL やリンクから 動画 ID (11桁等) を抜き出す天才解析ヘルパー
  const getYouTubeId = (url) => {
    if (!url || typeof url !== 'string') return null;
    // watch?v=XXXXX, youtu.be/XXXXX, /shorts/XXXXX などを網羅！
    const regExp = /(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=|shorts\/)|youtu\.be\/)([^"&?\/\s]{11})/i;
    const match = url.match(regExp);
    return match && match[1].length === 11 ? match[1] : null;
  };

  // YouTubeの場合に、カード一覧や詳細でサムネイル画像を鮮やかに表示するジェネレーター！
  const renderThumbnail = (topic) => {
    const st = str(topic.sourceType).toLowerCase();
    const su = str(topic.sourceUrl).toLowerCase();
    
    if (st.includes('youtube') || su.includes('youtube') || su.includes('youtu.be')) {
      let vid = getYouTubeId(topic.sourceUrl);
      // 万が一検索用リンクや未検出で動画IDが取れなかった場合も、
      // データ内に指定されたthumbnailがあるか、または鳴潮動画の高品質実例IDを賢くフォールバック！
      if (!vid && topic.thumbnailUrl) {
        return (
          <div className={styles.thumbnailWrapper}>
            <img src={topic.thumbnailUrl} alt={topic.title} className={styles.thumbnailImg} loading="lazy" />
            <span className={styles.thumbPlayIcon}>▶</span>
          </div>
        );
      }
      if (vid) {
        // 公式高品質サムネイル (hqdefault / mqdefault)
        const thumbUrl = `https://img.youtube.com/vi/${vid}/hqdefault.jpg`;
        return (
          <div className={styles.thumbnailWrapper}>
            <img src={thumbUrl} alt={topic.title} className={styles.thumbnailImg} loading="lazy" />
            <span className={styles.thumbPlayIcon}>▶</span>
          </div>
        );
      }
      // 動画IDがないYouTube総合ハブ等はスタイリッシュな YouTube マークアップバナーを表示！
      return (
        <div className={styles.thumbnailWrapperFallback}>
          <span className={styles.thumbFallbackLogo}>📺 YouTube バズ解析スレッド</span>
        </div>
      );
    }
    return null;
  };

  // ズーム（列の増減）ハンドラ
  const zoomIn = () => {
    setGridCols((prev) => Math.max(1, prev - 1));
  };

  const zoomOut = () => {
    setGridCols((prev) => Math.min(4, prev + 1));
  };

  // Ctrl + マウスホイールで動的に拡大縮小
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

  // 列数を100%厳密に一致させるための直列割り当て構文
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
            ◀ 動画トレンド・メインギャラリーに戻る (同一タブ)
          </Link>
          <div className={styles.titleArea}>
            <h1>📚 AIショート動画台本 ＆ ネタ発掘ライブラリ</h1>
            <p>海外Reddit(和訳)・YouTubeショート動画(サムネ表示対応)・SNS急上昇バズを最速選抜！</p>
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

          {/* 右側：没入型・スタジオ台本メインエディター */}
          <section className={styles.studioColumn}>
            {selectedTopic ? (
              <>
                <div className={styles.studioTitleRow}>
                  {renderThumbnail(selectedTopic) && (
                    <div className={styles.studioThumbPreview}>
                      {renderThumbnail(selectedTopic)}
                    </div>
                  )}
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
                    🚀 この記事の一次情報 ＆ 該当動画を開く (100%安全直撃リンク)
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
