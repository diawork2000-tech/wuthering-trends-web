'use client';

import { useState, useEffect, useRef } from 'react';
import styles from './VideoCard.module.css';

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
  const [isPlaying, setIsPlaying] = useState(false);
  // カードは videos 読み込み後（＝クライアント側）でしか描画されないため、
  // 初期値をここで localStorage から直接読んでも SSR とのズレは起きない。
  const [isWatched, setIsWatched] = useState(() => getWatchedIds().has(video.id));
  const cardRef = useRef(null);
  const timerRef = useRef(null);

  const handleTitleClick = () => {
    markAsWatched(video.id);
    setIsWatched(true);
  };

  // Intersection Observer for mobile scroll auto-play with intelligent hold delay
  useEffect(() => {
    // マウスでホバー可能なPC環境ではスクロール再生（Observer）を無効化
    const isHoverable = window.matchMedia('(hover: hover)').matches;
    if (isHoverable) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          // 画面中央領域にしっかり定着した場合のみ、1.3秒じっくり待ってからスマートに自動再生開始
          if (entry.isIntersecting && entry.intersectionRatio >= 0.7) {
            if (!timerRef.current) {
              timerRef.current = setTimeout(() => {
                setIsPlaying(true);
              }, 1300); // 1.3秒間 画面中央に留まり続けたときだけ発火！
            }
          } else {
            // スクロールによる素通りや画面外への離脱時は、即座にタイマーをキャンセルし再生させない
            if (timerRef.current) {
              clearTimeout(timerRef.current);
              timerRef.current = null;
            }
            setIsPlaying(false);
          }
        });
      },
      {
        root: null,
        rootMargin: '-22% 0px -22% 0px', // スマホ画面の上下22%ずつを除外した確信の「中央フォーカスゾーン」
        threshold: [0, 0.7], // 70%見えたらトリガー
      }
    );

    if (cardRef.current) {
      observer.observe(cardRef.current);
    }

    return () => {
      if (cardRef.current) {
        observer.unobserve(cardRef.current);
      }
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  // Hover handlers for PC
  const handleMouseEnter = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setIsPlaying(true), 200);
  };
  const handleMouseLeave = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setIsPlaying(false);
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
