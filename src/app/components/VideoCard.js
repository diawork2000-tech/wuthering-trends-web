'use client';

import { useState, useEffect, useRef } from 'react';
import styles from './VideoCard.module.css';

export default function VideoCard({ video }) {
  const [isPlaying, setIsPlaying] = useState(false);
  const cardRef = useRef(null);
  const timerRef = useRef(null);

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
      className={styles.card} 
      ref={cardRef}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <div className={styles.thumbnailContainer}>
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
          <span className={styles.channelName}>{video.channel}</span>
        </div>
        <a href={video.url} target="_blank" rel="noopener noreferrer" className={styles.titleLink}>
          <h3 className={styles.title} title={video.title}>{video.title}</h3>
        </a>
      </div>
    </div>
  );
}
