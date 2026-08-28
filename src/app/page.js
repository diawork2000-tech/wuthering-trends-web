'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import VideoCard from './components/VideoCard';
import styles from './page.module.css';
// 収集側と同じ定義ファイルをそのまま読む。画面用に別で持つと、片方だけ
// 直したときに「画面には載っているのに集めていない」状態が生まれる。
import officialAccounts from '../../scraper/official_accounts.json';

// 既読の記録は VideoCard が localStorage に持っている。同じ鍵を読む。
const WATCHED_STORAGE_KEY = 'wt_watched_video_ids';

const SNS_TARGETS = officialAccounts.accounts.filter((a) => a.collect);

// 収集側（sns_collector.py）の表示名と揃えてある
const SNS_PLATFORM_LABELS = { x: 'X', bilibili: 'BiliBili', weibo: 'Weibo', reddit: 'Reddit' };
const SNS_LANG_LABELS = { ja: '日本語', en: '英語', ko: '韓国語', 'zh-CN': '中国語', 'zh-TW': '中国語(繁体)' };

// 出稿期間「2026-07-31 〜 2026-08-03」から開始日・終了日を取り出す。
// 片方しか無い場合はその日付が開始日として入っている。
const adStart = (video) => (video.adPeriod || '').slice(0, 10);
const adEnd = (video) => {
  const parts = (video.adPeriod || '').split('〜');
  return (parts[1] || parts[0] || '').trim();
};

export default function Home() {
  const [videos, setVideos] = useState([]);
  // 広告は件数が多く別枠で取るため、通常の一覧とは別に持つ
  const [adVideos, setAdVideos] = useState(null);
  const adsRequested = useRef(false);
  // 公式SNSも広告と同じ理由で別枠。媒体と言語で絞り込めるようにする。
  const [snsVideos, setSnsVideos] = useState(null);
  const snsRequested = useRef(false);
  const [snsPlatform, setSnsPlatform] = useState('すべて');
  const [snsLang, setSnsLang] = useState('すべて');
  const [snsAccount, setSnsAccount] = useState('すべて');
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [watchedIds, setWatchedIds] = useState(() => new Set());
  const [showTargets, setShowTargets] = useState(false);
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

  // 稼働ログ管理用の状態
  const [logs, setLogs] = useState([]);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [expandedLogId, setExpandedLogId] = useState(null);

  // ズーム機能用の状態 (カード幅: 200px 〜 500px 程度)
  const [zoomLevel, setZoomLevel] = useState(300);

  // 検索・並び替え用の状態
  const [searchQuery, setSearchQuery] = useState('');
  const [sortOrder, setSortOrder] = useState('newest'); // newest | oldest | title | channel

  const tabs = ['すべて', '最新 (Shorts)', '最新 (通常)', '週間人気 (Shorts)', '週間人気 (通常)', '登録チャンネル', '広告', 'SNS'];

  const fetchLogs = async () => {
    setLoadingLogs(true);
    try {
      const res = await fetch('/api/logs');
      if (res.ok) {
        const data = await res.json();
        setLogs(data.logs || []);
        if (data.logs && data.logs.length > 0) {
          setExpandedLogId(data.logs[0].id); // 最初のログを自動展開
        }
      }
    } catch (err) {
      console.error('Error fetching logs:', err);
    } finally {
      setLoadingLogs(false);
    }
  };

  const openLogsModal = () => {
    setShowSettings(true);
    setActiveSettingsTab('logs');
    fetchLogs();
  };


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

  // 広告は通常の一覧の500件枠に収まらないので、タブを開いたときに別で取る。
  // 一度取ったら覚えておき、タブを行き来しても取り直さない。
  useEffect(() => {
    if (activeTab !== '広告' || adVideos !== null || adsRequested.current) return;
    adsRequested.current = true;
    fetch('/api/videos?ads=1')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`Status: ${res.status}`))))
      .then((data) => setAdVideos(data.videos || []))
      .catch((err) => {
        adsRequested.current = false; // 失敗したらタブを開き直したときに再挑戦する
        setError(err.message);
      });
  }, [activeTab, adVideos]);

  // 公式SNSも同じく別枠。開いたときに一度だけ取る。
  useEffect(() => {
    if (activeTab !== 'SNS' || snsVideos !== null || snsRequested.current) return;
    snsRequested.current = true;
    fetch('/api/videos?sns=1')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`Status: ${res.status}`))))
      .then((data) => setSnsVideos(data.videos || []))
      .catch((err) => {
        snsRequested.current = false; // 失敗したらタブを開き直したときに再挑戦する
        setError(err.message);
      });
  }, [activeTab, snsVideos]);

  // タブごとに選べる並び順が違う。切り替えた先に無い並び順が残っていると
  // 選択欄が空白になり、何で並んでいるのか分からなくなる。持っている値は
  // そのままに、表示と並べ替えに使う値だけをここで補正する。
  const sortAvailable =
    (['adEnd', 'adStart'].includes(sortOrder) && !['広告', 'すべて'].includes(activeTab)) ||
    (['postedNew', 'postedOld'].includes(sortOrder) && !['SNS', 'すべて'].includes(activeTab))
      ? 'newest'
      : sortOrder;

  // 「未読のみ」を押した時点の既読一覧で絞る。表示中に読み直さないので、
  // 一覧を見ている最中にカードが目の前から消えることはない。
  const toggleUnreadOnly = () => {
    const next = !unreadOnly;
    if (next) {
      try {
        setWatchedIds(new Set(JSON.parse(localStorage.getItem(WATCHED_STORAGE_KEY) || '[]')));
      } catch {
        setWatchedIds(new Set());
      }
    }
    setUnreadOnly(next);
  };

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
          <h1 className={styles.title}>🎥 YouTubeトレンド収集 ダッシュボード</h1>
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
            <button className={styles.settingsIconBtn} onClick={openLogsModal} title="システム稼働ログ (1週間分)">📜</button>
            <button className={styles.settingsIconBtn} onClick={openSettings} title="システム設定">⚙️</button>
          </div>
        </div>
        <p className={styles.subtitle}>『鳴潮』YouTube専門トレンド情報 ＆ 競合チャンネル実績データの全自動追跡センター</p>
        <div style={{ display: 'flex', gap: '0.8rem', justifyContent: 'center', marginTop: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
          <button 
            className={styles.syncButton} 
            onClick={handleSync} 
            disabled={isSyncing}
          >
            {isSyncing ? '起動中...' : '🔄 最新情報を収集'}
          </button>
          <Link href="/intelligence" style={{ textDecoration: 'none' }}>
            <button
              className={styles.syncButton}
              style={{ background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)', color: '#fff', fontWeight: '700', boxShadow: '0 0 18px rgba(16, 185, 129, 0.45)', border: '1px solid rgba(255,255,255,0.2)' }}
            >
              🌐 マルチメディア収集 スタジオへ進む
            </button>
          </Link>
          <Link href="/pickups" style={{ textDecoration: 'none' }}>
            <button
              className={styles.syncButton}
              style={{ background: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)', color: '#fff', fontWeight: '700', boxShadow: '0 0 18px rgba(245, 158, 11, 0.4)', border: '1px solid rgba(255,255,255,0.2)' }}
            >
              📌 ピックアップ一覧
            </button>
          </Link>
        </div>
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

      {/* 公式SNSは媒体も言語も混ざって並ぶ。どこの情報かで絞れないと使えない。 */}
      {activeTab === 'SNS' && (
        <div className={styles.snsFilters}>
          <div className={styles.snsFilterGroup}>
            <span className={styles.snsFilterLabel}>媒体</span>
            {['すべて', 'X', 'BiliBili', 'Weibo', 'Reddit'].map((p) => (
              <button
                key={p}
                className={`${styles.snsChip} ${snsPlatform === p ? styles.snsChipActive : ''}`}
                onClick={() => setSnsPlatform(p)}
              >
                {p}
              </button>
            ))}
          </div>
          <div className={styles.snsFilterGroup}>
            <span className={styles.snsFilterLabel}>言語</span>
            {['すべて', '日本語', '英語', '韓国語', '中国語'].map((l) => (
              <button
                key={l}
                className={`${styles.snsChip} ${snsLang === l ? styles.snsChipActive : ''}`}
                onClick={() => setSnsLang(l)}
              >
                {l}
              </button>
            ))}
          </div>

          {/* アカウント単位。日本語Xだけで6アカウントあるため、媒体と言語では絞りきれない。
              選択肢は実際に届いた投稿から作る。定義を二重に持つとズレるため。 */}
          <div className={styles.snsFilterGroup}>
            <span className={styles.snsFilterLabel}>アカウント</span>
            {['すべて', ...new Set(
              (snsVideos || [])
                .filter((v) => snsPlatform === 'すべて' || v.platform === snsPlatform)
                .filter((v) => snsLang === 'すべて' || v.lang === snsLang)
                .map((v) => v.account)
                .filter(Boolean)
            )].map((acc) => (
              <button
                key={acc}
                className={`${styles.snsChip} ${snsAccount === acc ? styles.snsChipActive : ''}`}
                onClick={() => setSnsAccount(acc)}
              >
                {acc}
              </button>
            ))}
          </div>

          <div className={styles.snsFilterGroup}>
            <button
              className={`${styles.snsChip} ${unreadOnly ? styles.snsChipActive : ''}`}
              onClick={toggleUnreadOnly}
              title="まだ開いていない投稿だけを表示します"
            >
              {unreadOnly ? '✓ 未読のみ' : '未読のみ'}
            </button>
            <button
              className={styles.snsChip}
              onClick={() => setShowTargets((v) => !v)}
              title="いま収集しているアカウントの一覧"
            >
              {showTargets ? '▲ 収集中の一覧' : `📋 収集中のアカウント (${SNS_TARGETS.length})`}
            </button>
          </div>

          {/* どのアカウントを見に行っているのかを、設定ファイルを開かずに確認できるようにする */}
          {showTargets && (
            <div className={styles.snsTargets}>
              {SNS_TARGETS.map((a) => (
                <a
                  key={`${a.platform}-${a.id}`}
                  href={a.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.snsTargetRow}
                >
                  <span className={styles.snsTargetPlatform}>{SNS_PLATFORM_LABELS[a.platform] || a.platform}</span>
                  <span className={styles.snsTargetLang}>{SNS_LANG_LABELS[a.lang] || a.lang}</span>
                  <span className={styles.snsTargetName}>{a.name}</span>
                  <span className={styles.snsTargetId}>{a.id}</span>
                </a>
              ))}
              <p className={styles.snsTargetsNote}>
                この一覧は収集側の設定ファイル（scraper/official_accounts.json）と同じものを読んでいます。
                増減させたい場合はお知らせください。
              </p>
            </div>
          )}
        </div>
      )}

      <div className={styles.searchBar}>
        <input
          type="text"
          className={styles.searchInput}
          placeholder="🔍 タイトル・チャンネル名で検索..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        {searchQuery && (
          <button className={styles.searchClearBtn} onClick={() => setSearchQuery('')} title="検索をクリア">×</button>
        )}
        <select
          className={styles.sortSelect}
          value={sortAvailable}
          onChange={(e) => setSortOrder(e.target.value)}
        >
          <option value="newest">新しい順（収集日）</option>
          <option value="oldest">古い順（収集日）</option>
          {/* 広告はまとめて登録されるため収集日では並ばない。
              いつ流れていた広告かで並べられるようにする。 */}
          {/* 出稿期間を持つのは広告だけ。他のタブで選べても並び順は変わらないので出さない。 */}
          {(activeTab === '広告' || activeTab === 'すべて') && (
            <>
              <option value="adEnd">出稿の新しい順（終了日）</option>
              <option value="adStart">出稿の古い順（開始日）</option>
            </>
          )}
          {/* SNSは収集日ではなく、実際に投稿された日時で並べたい */}
          {(activeTab === 'SNS' || activeTab === 'すべて') && (
            <>
              <option value="postedNew">投稿の新しい順</option>
              <option value="postedOld">投稿の古い順</option>
            </>
          )}
          <option value="title">タイトル順</option>
          <option value="channel">チャンネル順</option>
        </select>
      </div>

      {loading || (activeTab === '広告' && adVideos === null) || (activeTab === 'SNS' && snsVideos === null) ? (
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
          {/* 「広告」はカテゴリで絞れない。広告に使われた動画の多くは公式チャンネルの
              通常投稿で、別カテゴリで先に登録されているため。出稿期間の有無だけが
              広告として流れた目印になるので、絞り込みごとサーバー側に任せている。 */}
          {(activeTab === '広告' ? adVideos || [] : activeTab === 'SNS' ? snsVideos || [] : videos)
            .filter((video) => activeTab === 'すべて' || activeTab === '広告' || activeTab === 'SNS' || video.category === activeTab)
            .filter((video) => activeTab !== 'SNS' || snsPlatform === 'すべて' || video.platform === snsPlatform)
            .filter((video) => activeTab !== 'SNS' || snsLang === 'すべて' || video.lang === snsLang)
            .filter((video) => activeTab !== 'SNS' || snsAccount === 'すべて' || video.account === snsAccount)
            .filter((video) => !unreadOnly || !watchedIds.has(video.id))
            .filter((video) => {
              if (!searchQuery.trim()) return true;
              const q = searchQuery.trim().toLowerCase();
              return (
                video.title?.toLowerCase().includes(q) ||
                video.channel?.toLowerCase().includes(q)
              );
            })
            .sort((a, b) => {
              switch (sortAvailable) {
                case 'oldest':
                  return new Date(a.created_time) - new Date(b.created_time);
                case 'title':
                  return (a.title || '').localeCompare(b.title || '', 'ja');
                case 'channel':
                  return (a.channel || '').localeCompare(b.channel || '', 'ja');
                // 投稿日時が無い行（SNS以外）は末尾に寄せる。先頭に来ると
                // 並べ替えたのに何も変わっていないように見える。
                case 'postedNew':
                  return (b.postedAt || '').localeCompare(a.postedAt || '');
                case 'postedOld':
                  if (!a.postedAt) return 1;
                  if (!b.postedAt) return -1;
                  return a.postedAt.localeCompare(b.postedAt);
                case 'adStart':
                  // 出稿期間は「2026-07-31 〜 2026-08-03」の形。日付が
                  // YYYY-MM-DD なので、文字列のまま比べても日付順になる。
                  // 期間を持たない動画は末尾へ送る。
                  return (adStart(a) || '9999').localeCompare(adStart(b) || '9999');
                case 'adEnd':
                  return (adEnd(b) || '').localeCompare(adEnd(a) || '');
                case 'newest':
                default:
                  return new Date(b.created_time) - new Date(a.created_time);
              }
            })
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
              <button 
                className={`${styles.settingsTab} ${activeSettingsTab === 'logs' ? styles.activeSettingsTab : ''}`}
                onClick={() => { setActiveSettingsTab('logs'); fetchLogs(); }}
              >📜 稼働ログ (1週分)</button>
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

              {activeSettingsTab === 'logs' && (
                <div className={styles.settingsSection}>
                  <div className={styles.logsHeader}>
                    <h3>📊 全自動トレンド収集 ＆ APIキー運用の足跡</h3>
                    <button className={styles.refreshLogsBtn} onClick={fetchLogs} disabled={loadingLogs}>
                      {loadingLogs ? '読込中...' : '🔄 ログ再読込'}
                    </button>
                  </div>
                  <p className={styles.modalDesc}>
                    毎日1時間おきに連続稼働する自動システムの過去1週間（最高約170回分）の全稼働・APIスワップ記録です。
                  </p>
                  
                  {loadingLogs ? (
                    <div className={styles.loadingLogs}>過去のログファイルを同期中...</div>
                  ) : logs.length === 0 ? (
                    <p className={styles.emptyList}>記録されたログはまだありません。次回の収集動作完了後に自動表示されます。</p>
                  ) : (
                    <div className={styles.logsContainer}>
                      {logs.map(log => {
                        const isExpanded = expandedLogId === log.id;
                        return (
                          <div 
                            key={log.id} 
                            className={`${styles.logItem} ${log.status === 'Error' ? styles.logError : ''}`}
                            onClick={() => setExpandedLogId(isExpanded ? null : log.id)}
                          >
                            <div className={styles.logSummaryRow}>
                              <span className={log.status === 'Success' ? styles.statusSuccess : styles.statusError}>
                                {log.status === 'Success' ? '🟢 正常完了' : '🔴 停止・例外'}
                              </span>
                              <span className={styles.logTime}>{log.timestamp}</span>
                              <span className={styles.logKeyBadge}>{log.api_key_status || 'Key #1'}</span>
                            </div>
                            <div className={styles.logTextRow}>
                              <strong>{log.summary}</strong>
                              <span className={styles.expandHint}>{isExpanded ? '▲ 詳細を閉じる' : '▼ 詳しい足跡を開く'}</span>
                            </div>
                            {isExpanded && log.details && (
                              <div className={styles.logDetailsBox}>
                                {log.details.map((line, index) => (
                                  <div key={index} className={styles.logLine}>{line}</div>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

    </main>
  );
}
