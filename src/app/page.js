'use client';

import { useEffect, useState } from 'react';
import VideoCard from './components/VideoCard';
import styles from './page.module.css';

export default function Home() {
  const [videos, setVideos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState('すべて');
  const [isSyncing, setIsSyncing] = useState(false);

  const tabs = ['すべて', '最新 (Shorts)', '最新 (通常)', '週間人気 (Shorts)', '週間人気 (通常)'];

  useEffect(() => {
    async function fetchVideos() {
      try {
        const res = await fetch('/api/videos');
        if (!res.ok) {
          const text = await res.text();
          throw new Error(`Status: ${res.status}, Details: ${text}`);
        }
        const data = JSON.parse(await res.text());
        setVideos(data.videos || []);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    fetchVideos();
  }, []);

  const handleSync = async () => {
    if (!window.confirm('クラウドで情報収集を開始しますか？完了まで数分かかり、Discordに通知されます。')) return;
    
    setIsSyncing(true);
    try {
      const res = await fetch('/api/trigger', { method: 'POST' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(`起動に失敗しました: ${err.error || res.status}`);
      } else {
        alert('情報収集スクリプトを起動しました！数分後にDiscordへ通知が届きます。');
      }
    } catch (err) {
      alert('エラーが発生しました: ' + err.message);
    } finally {
      setIsSyncing(false);
    }
  };

  return (
    <main className={styles.main}>
      <div className={styles.header}>
        <h1 className={styles.title}>Wuthering Trends</h1>
        <p className={styles.subtitle}>Daily updated gallery of popular and latest videos.</p>
        <button 
          className={styles.syncButton} 
          onClick={handleSync} 
          disabled={isSyncing}
        >
          {isSyncing ? '起動中...' : '🔄 最新情報を収集'}
        </button>
      </div>

      <div className={styles.tabsContainer}>
        {tabs.map((tab) => (
          <button
            key={tab}
            className={`${styles.tabButton} ${activeTab === tab ? styles.activeTab : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      {loading ? (
        <div className={styles.loadingContainer}>
          <div className={styles.spinner}></div>
          <p>Loading the latest trends...</p>
        </div>
      ) : error ? (
        <div className={styles.errorContainer}>
          <p>Error: {error}</p>
        </div>
      ) : (
        <div className={styles.gallery}>
          {videos
            .filter((video) => activeTab === 'すべて' || video.category === activeTab)
            .map((video) => (
              <VideoCard key={video.id} video={video} />
          ))}
        </div>
      )}
    </main>
  );
}
