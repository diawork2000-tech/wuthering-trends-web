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

// 投稿日時は日本時間で見せる。保存側は世界標準時のまま持っているので、
// ここで変換する。何日前かも添えないと、日付だけでは古さが掴みにくい。
function formatPostedAt(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const stamp = d.toLocaleString('ja-JP', {
    timeZone: 'Asia/Tokyo',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
  const hours = Math.floor((Date.now() - d.getTime()) / 3600000);
  if (hours < 1) return `${stamp}（さっき）`;
  if (hours < 24) return `${stamp}（${hours}時間前）`;
  return `${stamp}（${Math.floor(hours / 24)}日前）`;
}

// 画像が無いときに入る仮の画像。提供元のサービスが終了しており、
// そのまま出すと壊れた画像の枠だけが残る。
const NO_IMAGE = 'via.placeholder.com';

export default function VideoCard({ video }) {
  // カードは videos 読み込み後（＝クライアント側）でしか描画されないため、
  // 初期値をここで localStorage から直接読んでも SSR とのズレは起きない。
  const [isWatched, setIsWatched] = useState(() => getWatchedIds().has(video.id));
  // 採用（お気に入り）。企画画面には前からあったが、動画一覧側には無かった。
  // 押した瞬間に見た目を変え、失敗したら戻す。通信待ちで固まらせない。
  const [adopted, setAdopted] = useState(!!video.adopted);
  const [adoptBusy, setAdoptBusy] = useState(false);
  // SNSの投稿は本文がそのまま見出しになるため長い。既定は畳んでおく。
  const [expanded, setExpanded] = useState(false);
  const [showOriginal, setShowOriginal] = useState(false);

  // SNSの投稿は本文がそのまま見出しになる。動画のタイトルと同じ2行で
  // 切ると、ほぼ全ての投稿が読めなくなる。行数を広げて、はみ出すほど
  // 長いものだけ畳む。
  const isPost = !!video.platform;
  const hasImage = video.thumbnail && !video.thumbnail.includes(NO_IMAGE);
  // 画像を持たない投稿で16:9の枠を確保すると、空白が本文を押し下げる。
  const showThumbnail = !isPost || hasImage;

  const toggleAdopt = async () => {
    if (adoptBusy) return;
    const next = !adopted;
    setAdopted(next);
    setAdoptBusy(true);
    try {
      const res = await fetch('/api/pickups', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: [video.id], adopted: next }),
      });
      if (!res.ok) throw new Error(`Status: ${res.status}`);
    } catch {
      setAdopted(!next); // 失敗したら元に戻す。押せたように見せたままにしない
    } finally {
      setAdoptBusy(false);
    }
  };
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
      <div className={`${styles.thumbnailContainer} ${showThumbnail ? '' : styles.thumbnailContainerFlat}`}>
        {isWatched && <span className={styles.watchedBadge}>✓ 視聴済み</span>}
        <button
          type="button"
          className={`${styles.adoptStar} ${adopted ? styles.adoptStarOn : ''}`}
          onClick={toggleAdopt}
          disabled={adoptBusy}
          title={adopted ? '採用を解除' : 'このネタを採用する（ピックアップ一覧に集まります）'}
        >
          {adopted ? '⭐' : '☆'}
        </button>
        {/* IFrame player only loads/shows when isPlaying is true */}
        {showThumbnail && (isPlaying && video.videoId ? (
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
        ))}
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
          <h3
            className={`${styles.title} ${isPost ? styles.titlePost : ''} ${expanded ? styles.titleExpanded : ''}`}
            title={video.title}
          >
            {video.title}
          </h3>
        </a>
        {/* 畳んだ状態でもほぼ全文が読める行数にしてある。ここに引っかかるのは
            よほど長い告知だけ。しきい値は畳んだときの行数に合わせた目安。 */}
        {isPost && video.title.length > 170 && (
          <button
            type="button"
            className={styles.textToggle}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? '▲ 閉じる' : '▼ 全文を表示'}
          </button>
        )}
        {/* 訳が怪しいときに元を確かめられるようにする */}
        {video.originalTitle && (
          <>
            <button
              type="button"
              className={styles.textToggle}
              onClick={() => setShowOriginal((v) => !v)}
            >
              {showOriginal ? '▲ 原文を隠す' : '🌐 原文を表示'}
            </button>
            {showOriginal && <p className={styles.originalText}>{video.originalTitle}</p>}
          </>
        )}
        {/* 広告として実際に配信されていた期間。どのPVをいつ推していたかが分かる */}
        {video.adPeriod && (
          <span className={styles.adPeriod} title="この動画が広告として配信されていた期間">
            📣 {video.adPeriod}
          </span>
        )}
        {/* 公式SNSの投稿は媒体も言語も混ざって並ぶ。どこの誰の投稿なのかを
            一目で分かるようにしておかないと、一覧として使えない。 */}
        {video.platform && (
          <div className={styles.snsMeta}>
            <span className={styles.snsSource} title={`情報元: ${video.channel}`}>
              📡 {video.platform}{video.lang ? ` ・ ${video.lang}` : ''}{video.account ? ` ・ ${video.account}` : ''}
            </span>
            {/* 収集日ではなく、実際に投稿された日時 */}
            {video.postedAt && (
              <span className={styles.postedAt} title="投稿された日時">
                🕒 {formatPostedAt(video.postedAt)}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
