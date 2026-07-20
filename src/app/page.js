'use client';

import { useEffect, useState } from 'react';
import VideoCard from './components/VideoCard';
import styles from './page.module.css';

export default function Home() {
  const [videos, setVideos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState('すべて');

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

  return (
    <main className={styles.main}>
      <div className={styles.header}>
        <h1 className={styles.title}>Wuthering Trends</h1>
        <p className={styles.subtitle}>Daily updated gallery of popular and latest videos.</p>
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
