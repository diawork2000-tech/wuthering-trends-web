'use client';

import { useEffect, useState } from 'react';
import VideoCard from './components/VideoCard';
import styles from './page.module.css';

export default function Home() {
  const [videos, setVideos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    async function fetchVideos() {
      try {
        const res = await fetch('/api/videos');
        if (!res.ok) throw new Error('Failed to fetch data');
        const data = await res.json();
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
          {videos.map((video) => (
            <VideoCard key={video.id} video={video} />
          ))}
        </div>
      )}
    </main>
  );
}
