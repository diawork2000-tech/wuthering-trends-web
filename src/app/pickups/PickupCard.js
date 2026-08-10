'use client';

import styles from './PickupCard.module.css';
import { useHoverAutoplay } from '../components/useHoverAutoplay';

const STATUS_OPTIONS = ['未着手', '制作中', '投稿済み', '見送り'];

// ピックアップ一覧のカード。
// 見た目と自動再生の挙動はYouTubeトレンド収集のカードに合わせつつ、
// 選択チェック・制作状況・解除ボタンを持たせてある。
export default function PickupCard({ item, selected, onToggleSelect, onChangeStatus, onRemove, busy }) {
  const { isPlaying, cardRef, handleMouseEnter, handleMouseLeave } = useHoverAutoplay();

  const thumb =
    item.thumbnail || (item.videoId ? `https://i.ytimg.com/vi/${item.videoId}/hqdefault.jpg` : '');

  return (
    <div
      className={`${styles.card} ${selected ? styles.cardSelected : ''}`}
      ref={cardRef}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onClick={() => onToggleSelect(item.id)}
    >
      <div className={styles.thumbnailContainer}>
        <label className={styles.checkWrap} onClick={(e) => e.stopPropagation()}>
          <input
            type="checkbox"
            className={styles.checkbox}
            checked={selected}
            onChange={() => onToggleSelect(item.id)}
            aria-label={`${item.title} を選択`}
          />
        </label>

        {isPlaying && item.videoId ? (
          <iframe
            className={styles.iframe}
            src={`https://www.youtube.com/embed/${item.videoId}?autoplay=1&mute=1&controls=0&modestbranding=1&loop=1&playlist=${item.videoId}`}
            title={item.title}
            frameBorder="0"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
          />
        ) : thumb ? (
          // 外部サムネイルのドメインが増えても壊れないよう、あえて通常のimgを使う
          // eslint-disable-next-line @next/next/no-img-element
          <img src={thumb} alt="" className={styles.thumbnailImage} loading="lazy" />
        ) : (
          <div className={styles.thumbFallback}>📰</div>
        )}
      </div>

      <div className={styles.content}>
        <div className={styles.metaRow}>
          <span
            className={`${styles.originBadge} ${
              item.origin === 'video' ? styles.originVideo : styles.originTopic
            }`}
          >
            {item.originLabel}
          </span>
          {item.linkedIds?.length > 1 && <span className={styles.metaBadge}>両DB</span>}
          {item.score != null && <span className={styles.metaBadge}>スコア {item.score}</span>}
          {item.viewCount > 0 && (
            <span className={styles.viewCount} title="収集時点の再生数">
              ▶ {item.viewCount.toLocaleString()}
            </span>
          )}
        </div>

        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className={styles.titleLink}
          onClick={(e) => e.stopPropagation()}
        >
          <h3 className={styles.title} title={item.title}>
            {item.title}
          </h3>
        </a>

        {item.subtitle && <p className={styles.subtitle}>{item.subtitle}</p>}

        <div className={styles.actions} onClick={(e) => e.stopPropagation()}>
          <select
            className={styles.statusSelect}
            value={item.status || '未着手'}
            onChange={(e) => onChangeStatus(item, e.target.value)}
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button
            className={styles.removeBtn}
            onClick={() => onRemove(item)}
            disabled={busy}
            title="この1件をピックアップから外す（データは残ります）"
          >
            外す
          </button>
        </div>
      </div>
    </div>
  );
}
