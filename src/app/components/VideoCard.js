'use client';

import { useState, useEffect, useRef } from 'react';
import styles from './VideoCard.module.css';

export default function VideoCard({ video }) {
  const [isPlaying, setIsPlaying] = useState(false);
  const cardRef = useRef(null);

  // Intersection Observer for mobile scroll auto-play
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          // 画面の中央付近（intersection ratioが高い）で再生開始
          if (entry.isIntersecting && entry.intersectionRatio >= 0.7) {
            setIsPlaying(true);
          } else {
            setIsPlaying(false);
          }
        });
      },
      {
        root: null,
        rootMargin: '-10% 0px -10% 0px', // 画面の上下10%を除外した領域
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
    };
  }, []);

  // Hover handlers for PC
  const handleMouseEnter = () => setIsPlaying(true);
  const handleMouseLeave = () => setIsPlaying(false);

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
