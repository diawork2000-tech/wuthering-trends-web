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
  
  // チャンネル管理用の状態
  const [showSettings, setShowSettings] = useState(false);
  const [channels, setChannels] = useState([]);
  const [newChannelName, setNewChannelName] = useState('');
  const [newChannelId, setNewChannelId] = useState('');
  const [isAddingChannel, setIsAddingChannel] = useState(false);

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

  const fetchChannels = async () => {
    try {
      const res = await fetch('/api/channels');
      if (res.ok) {
        const data = await res.json();
        setChannels(data.channels || []);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleAddChannel = async (e) => {
    e.preventDefault();
    if (!newChannelName || !newChannelId) return;
    
    // URLが入力された場合、UCから始まるチャンネルIDを抽出する
    let extractedId = newChannelId.trim();
    const match = extractedId.match(/(?:channel\/)?(UC[\w-]{22})/);
    if (match) {
      extractedId = match[1];
    }
    
    setIsAddingChannel(true);
    try {
      const res = await fetch('/api/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newChannelName, channelId: extractedId })
      });
      
      if (res.ok) {
        setNewChannelName('');
        setNewChannelId('');
        fetchChannels(); // 一覧を再取得
      } else {
        const err = await res.json();
        alert('追加エラー: ' + err.error);
      }
    } catch (err) {
      alert('エラーが発生しました: ' + err.message);
    } finally {
      setIsAddingChannel(false);
    }
  };

  const openSettings = () => {
    setShowSettings(true);
    fetchChannels();
  };

  return (
    <main className={styles.main}>
      <div className={styles.header}>
        <div className={styles.topBar}>
          <h1 className={styles.title}>Wuthering Trends</h1>
          <button className={styles.settingsIconBtn} onClick={openSettings}>⚙️</button>
        </div>
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

      {/* チャンネル設定モーダル */}
      {showSettings && (
        <div className={styles.modalOverlay} onClick={() => setShowSettings(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2>⚙️ 確実収集チャンネル設定</h2>
              <button className={styles.closeBtn} onClick={() => setShowSettings(false)}>×</button>
            </div>
            
            <p className={styles.modalDesc}>ここに登録されたチャンネルの動画は、検索から漏れることなく確実に収集されます。</p>
            
            <form className={styles.addChannelForm} onSubmit={handleAddChannel}>
              <input 
                type="text" 
                placeholder="チャンネル名 (例: 鳴潮公式)" 
                value={newChannelName}
                onChange={(e) => setNewChannelName(e.target.value)}
                required
              />
              <input 
                type="text" 
                placeholder="チャンネルID (例: UC...)" 
                value={newChannelId}
                onChange={(e) => setNewChannelId(e.target.value)}
                required
              />
              <button type="submit" disabled={isAddingChannel}>
                {isAddingChannel ? '追加中...' : '追加する'}
              </button>
            </form>

            <div className={styles.channelList}>
              <h3>登録済みチャンネル一覧</h3>
              {channels.length === 0 ? (
                <p className={styles.emptyList}>登録されていません</p>
              ) : (
                <ul>
                  {channels.map(ch => (
                    <li key={ch.id}>
                      <span className={styles.chName}>{ch.name}</span>
                      <span className={styles.chId}>{ch.channelId}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
