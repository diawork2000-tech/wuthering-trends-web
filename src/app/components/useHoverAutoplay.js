'use client';

import { useEffect, useRef, useState } from 'react';

// カードにマウスを乗せる（PC）／画面中央に留める（スマホ）と再生を始める挙動。
// YouTubeトレンド収集のカードとピックアップ一覧のカードで同じ挙動にするため、
// 両方から使えるようここに切り出してある。
//
// 戻り値の ref を再生させたい要素に付け、isPlaying が true のときだけ
// iframe を描画する。再生していない間は iframe を作らないので、
// 一覧に何十枚並んでも重くならない。
export function useHoverAutoplay() {
  const [isPlaying, setIsPlaying] = useState(false);
  const cardRef = useRef(null);
  const timerRef = useRef(null);

  useEffect(() => {
    // マウスでホバーできるPCではスクロール再生を使わない（ホバーと二重に発火するため）
    const isHoverable = window.matchMedia('(hover: hover)').matches;
    if (isHoverable) return;

    const node = cardRef.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          // 画面中央にしっかり留まったときだけ、1.3秒待ってから再生する。
          // スクロールで素通りしただけで再生が始まると鬱陶しいため。
          if (entry.isIntersecting && entry.intersectionRatio >= 0.7) {
            if (!timerRef.current) {
              timerRef.current = setTimeout(() => setIsPlaying(true), 1300);
            }
          } else {
            if (timerRef.current) {
              clearTimeout(timerRef.current);
              timerRef.current = null;
            }
            setIsPlaying(false);
          }
        });
      },
      { root: null, rootMargin: '-22% 0px -22% 0px', threshold: [0, 0.7] }
    );

    observer.observe(node);
    return () => {
      observer.unobserve(node);
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

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

  return { isPlaying, cardRef, handleMouseEnter, handleMouseLeave };
}
