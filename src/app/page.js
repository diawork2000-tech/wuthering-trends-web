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

  // 除外ワード管理用の状態
  const [excludeWords, setExcludeWords] = useState([]);
  const [newExcludeWord, setNewExcludeWord] = useState('');
  const [isUpdatingConfig, setIsUpdatingConfig] = useState(false);
  const [configSha, setConfigSha] = useState('');
  const [configData, setConfigData] = useState(null);

  // 大元設定用の状態
  const [activeSettingsTab, setActiveSettingsTab] = useState('general');
  const [searchQueries, setSearchQueries] = useState([]);
  const [newSearchQuery, setNewSearchQuery] = useState('');
  const [maxResults, setMaxResults] = useState(50);
  const [shortsRatio, setShortsRatio] = useState(0.85);
  const [jpRatio, setJpRatio] = useState(0.85);

  // ズーム機能用の状態 (カード幅: 200px 〜 500px 程度)
  const [zoomLevel, setZoomLevel] = useState(300);

  const tabs = ['すべて', '最新 (Shorts)', '最新 (通常)', '週間人気 (Shorts)', '週間人気 (通常)', '登録チャンネル'];

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

  const handleDeleteChannel = async (id) => {
    if (!window.confirm('このチャンネルを削除してもよろしいですか？')) return;
    
    try {
      const res = await fetch(`/api/channels/${id}`, { method: 'DELETE' });
      if (res.ok) {
        fetchChannels();
      } else {
        const err = await res.json();
        alert('削除エラー: ' + err.error);
      }
    } catch (err) {
      alert('エラーが発生しました: ' + err.message);
    }
  };

  const fetchConfig = async () => {
    try {
      const res = await fetch('/api/config');
      if (res.ok) {
        const data = await res.json();
        setConfigData(data.config);
        setConfigSha(data.sha);
        setExcludeWords(data.config.youtube?.exclude_words || []);
        setSearchQueries(data.config.youtube?.search_queries || []);
        setMaxResults(data.config.youtube?.max_results_per_query || 50);
        setShortsRatio(data.config.youtube?.shorts_ratio ?? 0.85);
        setJpRatio(data.config.youtube?.jp_ratio ?? 0.85);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const updateConfig = async (newExcludeWords) => {
    if (!configData || !configSha) return;
    setIsUpdatingConfig(true);
    
    try {
      const newConfig = { ...configData };
      if (!newConfig.youtube) newConfig.youtube = {};
      
      // newExcludeWordsが引数で渡された場合はそれを使用し、そうでない場合は現在の状態を使用
      newConfig.youtube.exclude_words = newExcludeWords || excludeWords;
      
      // searchQueriesが引数で渡された場合はそれを使用
      newConfig.youtube.search_queries = arguments.length > 1 && arguments[1] ? arguments[1] : searchQueries;
      
      // 他のプロパティも現在の状態を反映
      newConfig.youtube.max_results_per_query = maxResults;
      newConfig.youtube.shorts_ratio = shortsRatio;
      newConfig.youtube.jp_ratio = jpRatio;

      const res = await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: newConfig, sha: configSha })
      });

      if (res.ok) {
        fetchConfig(); // SHAを更新するために再取得
      } else {
        const err = await res.json();
        alert('設定更新エラー: ' + err.error);
        fetchConfig(); // 失敗時も再取得して状態を戻す
      }
    } catch (err) {
      alert('エラーが発生しました: ' + err.message);
    } finally {
      setIsUpdatingConfig(false);
    }
  };

  const handleAddExcludeWord = (e) => {
    e.preventDefault();
    if (!newExcludeWord.trim()) return;
    const word = newExcludeWord.trim();
    if (excludeWords.includes(word)) {
      alert('既に登録されています');
      return;
    }
    
    const newWords = [...excludeWords, word];
    setExcludeWords(newWords);
    setNewExcludeWord('');
    updateConfig(newWords);
  };

  const handleDeleteExcludeWord = (word) => {
    if (!window.confirm(`「${word}」を除外ワードから削除しますか？`)) return;
    const newWords = excludeWords.filter(w => w !== word);
    setExcludeWords(newWords);
    updateConfig(newWords);
  };

  const handleAddSearchQuery = (e) => {
    e.preventDefault();
    if (!newSearchQuery.trim()) return;
    const q = newSearchQuery.trim();
    if (searchQueries.includes(q)) {
      alert('既に登録されています');
      return;
    }
    
    const newQs = [...searchQueries, q];
    setSearchQueries(newQs);
    setNewSearchQuery('');
    updateConfig(null, newQs);
  };

  const handleDeleteSearchQuery = (q) => {
    if (!window.confirm(`「${q}」を検索キーワードから削除しますか？`)) return;
    const newQs = searchQueries.filter(w => w !== q);
    setSearchQueries(newQs);
    updateConfig(null, newQs);
  };

  const handleSaveGeneralSettings = () => {
    updateConfig();
  };

  const openSettings = () => {
    setShowSettings(true);
    fetchChannels();
    fetchConfig();
  };

  return (
    <main className={styles.main}>
      <div className={styles.header}>
        <div className={styles.topBar}>
          <h1 className={styles.title}>Wuthering Trends</h1>
          <div className={styles.topControls}>
            <div className={styles.zoomControl}>
              <span title="動画サイズを縮小">➖</span>
              <input 
                type="range" 
                min="150" 
                max="500" 
                value={zoomLevel} 
                onChange={(e) => setZoomLevel(Number(e.target.value))}
                className={styles.zoomSlider}
              />
              <span title="動画サイズを拡大">➕</span>
            </div>
            <button className={styles.settingsIconBtn} onClick={openSettings}>⚙️</button>
          </div>
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
        <div className={styles.gallery} style={{ '--card-width': `${zoomLevel}px` }}>
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
              <h2>⚙️ システム設定</h2>
              <button className={styles.closeBtn} onClick={() => setShowSettings(false)}>×</button>
            </div>
            
            <div className={styles.settingsTabs}>
              <button 
                className={`${styles.settingsTab} ${activeSettingsTab === 'general' ? styles.activeSettingsTab : ''}`}
                onClick={() => setActiveSettingsTab('general')}
              >大元設定</button>
              <button 
                className={`${styles.settingsTab} ${activeSettingsTab === 'channels' ? styles.activeSettingsTab : ''}`}
                onClick={() => setActiveSettingsTab('channels')}
              >登録チャンネル</button>
              <button 
                className={`${styles.settingsTab} ${activeSettingsTab === 'exclude' ? styles.activeSettingsTab : ''}`}
                onClick={() => setActiveSettingsTab('exclude')}
              >除外ワード</button>
            </div>

            <div className={styles.settingsBody}>
              {activeSettingsTab === 'general' && (
                <div className={styles.settingsSection}>
                  <h3>🔍 検索キーワード</h3>
                  <p className={styles.modalDesc}>YouTubeで検索するキーワード。複数ある場合、それぞれに対して検索が実行されます。</p>
                  <form className={styles.addForm} onSubmit={handleAddSearchQuery}>
                    <input 
                      type="text" 
                      placeholder="キーワード (例: 鳴潮)" 
                      value={newSearchQuery}
                      onChange={(e) => setNewSearchQuery(e.target.value)}
                      required
                    />
                    <button type="submit" disabled={isUpdatingConfig}>追加</button>
                  </form>
                  <div className={styles.tagList}>
                    {searchQueries.map(q => (
                      <span key={q} className={styles.tag}>
                        {q} <button onClick={() => handleDeleteSearchQuery(q)} className={styles.tagDelBtn}>×</button>
                      </span>
                    ))}
                  </div>

                  <hr className={styles.divider} />

                  <h3>📊 収集パラメータ設定</h3>
                  <div className={styles.paramGroup}>
                    <label>
                      1キーワードあたりの最大収集件数 (現在の設定: {maxResults}件)
                      <input 
                        type="number" 
                        min="5" 
                        max="50" 
                        value={maxResults}
                        onChange={(e) => setMaxResults(Number(e.target.value))}
                        className={styles.numberInput}
                      />
                    </label>
                  </div>
                  
                  <div className={styles.paramGroup}>
                    <label>
                      Shortsと通常動画の割合 (Shorts: {Math.round(shortsRatio * 100)}% / 通常: {100 - Math.round(shortsRatio * 100)}%)
                      <input 
                        type="range" 
                        min="0" 
                        max="1" 
                        step="0.05"
                        value={shortsRatio}
                        onChange={(e) => setShortsRatio(Number(e.target.value))}
                        className={styles.rangeInput}
                      />
                    </label>
                  </div>

                  <div className={styles.paramGroup}>
                    <label>
                      日本と海外動画の割合 (日本: {Math.round(jpRatio * 100)}% / 海外: {100 - Math.round(jpRatio * 100)}%)
                      <input 
                        type="range" 
                        min="0" 
                        max="1" 
                        step="0.05"
                        value={jpRatio}
                        onChange={(e) => setJpRatio(Number(e.target.value))}
                        className={styles.rangeInput}
                      />
                    </label>
                  </div>

                  <button 
                    className={styles.saveBtn} 
                    onClick={handleSaveGeneralSettings}
                    disabled={isUpdatingConfig}
                  >
                    {isUpdatingConfig ? '保存中...' : '設定を保存'}
                  </button>
                </div>
              )}

              {activeSettingsTab === 'channels' && (
                <div className={styles.settingsSection}>
                  <h3>📺 登録チャンネル</h3>
                  <p className={styles.modalDesc}>ここに登録されたチャンネルの動画は、検索から漏れることなく確実に収集されます。</p>
                  <form className={styles.addForm} onSubmit={handleAddChannel}>
                    <input 
                      type="text" 
                      placeholder="チャンネル名 (例: 鳴潮公式)" 
                      value={newChannelName}
                      onChange={(e) => setNewChannelName(e.target.value)}
                      required
                    />
                    <input 
                      type="text" 
                      placeholder="URL または チャンネルID" 
                      value={newChannelId}
                      onChange={(e) => setNewChannelId(e.target.value)}
                      required
                    />
                    <button type="submit" disabled={isAddingChannel}>
                      {isAddingChannel ? '追加中...' : '追加'}
                    </button>
                  </form>
                  <div className={styles.itemList}>
                    {channels.length === 0 ? (
                      <p className={styles.emptyList}>登録されていません</p>
                    ) : (
                      <ul>
                        {channels.map(ch => (
                          <li key={ch.id}>
                            <div className={styles.itemInfo}>
                              <span className={styles.itemName}>{ch.name}</span>
                              <span className={styles.itemId}>{ch.channelId}</span>
                            </div>
                            <button className={styles.deleteBtn} onClick={() => handleDeleteChannel(ch.id)}>削除</button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              )}

              {activeSettingsTab === 'exclude' && (
                <div className={styles.settingsSection}>
                  <h3>🚫 除外ワード</h3>
                  <p className={styles.modalDesc}>ここに登録した単語がタイトルに完全に一致する動画は収集されません。</p>
                  <form className={styles.addForm} onSubmit={handleAddExcludeWord}>
                    <input 
                      type="text" 
                      placeholder="除外する単語 (例: MMD)" 
                      value={newExcludeWord}
                      onChange={(e) => setNewExcludeWord(e.target.value)}
                      required
                    />
                    <button type="submit" disabled={isUpdatingConfig}>
                      {isUpdatingConfig ? '追加中...' : '追加'}
                    </button>
                  </form>
                  <div className={styles.itemList}>
                    {excludeWords.length === 0 ? (
                      <p className={styles.emptyList}>登録されていません</p>
                    ) : (
                      <ul>
                        {excludeWords.map(word => (
                          <li key={word}>
                            <span className={styles.itemName}>{word}</span>
                            <button className={styles.deleteBtn} onClick={() => handleDeleteExcludeWord(word)} disabled={isUpdatingConfig}>
                              削除
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
