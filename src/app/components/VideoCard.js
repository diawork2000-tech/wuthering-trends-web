'use client';

import { useState } from 'react';
import styles from './VideoCard.module.css';
import { useHoverAutoplay } from './useHoverAutoplay';

const WATCHED_STORAGE_KEY = 'wt_watched_video_ids';

// タイトルを開いた動画だけを既読扱いにする。ボタンでの手動管理は
// ひと手間増えるので、実際に見に行った操作をそのまま既読の合図として使う。
function getWatchedIds() {
  if (typeof window === 'undefined') return new Set();
  try {
    return new Set(JSON.parse(localStorage.getItem(WATCHED_STORAGE_KEY) || '[]'));
  } catch {
    return new Set();
  }
}

function markAsWatched(id) {
  if (typeof window === 'undefined') return;
  const ids = getWatchedIds();
  ids.add(id);
  try {
    localStorage.setItem(WATCHED_STORAGE_KEY, JSON.stringify([...ids]));
  } catch {
    // ストレージ書き込み不可（プライベートモード等）は既読管理を諦めるだけで動作に影響しない
  }
}

export default function VideoCard({ video }) {
  // カードは videos 読み込み後（＝クライアント側）でしか描画されないため、
  // 初期値をここで localStorage から直接読んでも SSR とのズレは起きない。
  const [isWatched, setIsWatched] = useState(() => getWatchedIds().has(video.id));
  // ホバー／画面中央での自動再生。ピックアップ一覧のカードと共通の挙動。
  const { isPlaying, cardRef, handleMouseEnter, handleMouseLeave } = useHoverAutoplay();

  const handleTitleClick = () => {
    markAsWatched(video.id);
    setIsWatched(true);
  };

  return (
    <div
      className={`${styles.card} ${isWatched ? styles.watched : ''}`}
      ref={cardRef}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <div className={styles.thumbnailContainer}>
        {isWatched && <span className={styles.watchedBadge}>✓ 視聴済み</span>}
        {/* IFrame player only loads/shows when isPlaying is true */}
        {isPlaying && video.videoId ? (
          <iframe
            className={styles.iframe}
            src={`https://www.youtube.com/embed/${video.videoId}?autoplay=1&mute=1&controls=0&modestbranding=1&loop=1&playlist=${video.videoId}`}
            title={video.title}
            frameBorder="0"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
          ></iframe>
        ) : (
          <img 
            src={video.thumbnail} 
            alt={video.title} 
            className={styles.thumbnailImage} 
            loading="lazy"
          />
        )}
      </div>

      <div className={styles.content}>
        <div className={styles.metaRow}>
          <span className={styles.categoryBadge}>{video.category}</span>
          {video.viewCount > 0 && (
            <span className={styles.viewCount} title="収集時点の再生数">
              ▶ {video.viewCount.toLocaleString()}
            </span>
          )}
          <span className={styles.channelName}>{video.channel}</span>
        </div>
        <a href={video.url} target="_blank" rel="noopener noreferrer" className={styles.titleLink} onClick={handleTitleClick}>
          <h3 className={styles.title} title={video.title}>{video.title}</h3>
        </a>
      </div>
    </div>
  );
}
