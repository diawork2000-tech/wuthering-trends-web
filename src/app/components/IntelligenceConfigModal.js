'use client';

import React, { useState, useEffect } from 'react';
import styles from './IntelligenceConfigModal.module.css';

export default function IntelligenceConfigModal({ isOpen, onClose }) {
  const [activeTab, setActiveTab] = useState('channels'); // 'channels' or 'web'
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [sha, setSha] = useState('');
  
  const [targetChannels, setTargetChannels] = useState([]);
  const [targetWebSources, setTargetWebSources] = useState([]);

  // 新規登録用の入力State
  const [newChName, setNewChName] = useState('');
  const [newChUrl, setNewChUrl] = useState('');
  const [newWebName, setNewWebName] = useState('');
  const [newWebUrl, setNewWebUrl] = useState('');

  useEffect(() => {
    if (isOpen) {
      fetchConfig();
    }
  }, [isOpen]);

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/intelligence_config');
      if (res.ok) {
        const data = await res.json();
        setSha(data.sha || '');
        if (data.config) {
          setTargetChannels(data.config.target_channels || []);
          setTargetWebSources(data.config.target_web_sources || []);
        }
      } else {
        alert('設定の取得に失敗しました。時間をおいて再試行してください。');
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = {
        config: {
          target_channels: targetChannels,
          target_web_sources: targetWebSources,
          settings: {
            target_items_per_run: 15,
            min_score_threshold: 60,
            enable_gemini_summary: true
          }
        },
        sha: sha
      };
      const res = await fetch('/api/intelligence_config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        alert('✨ ご指定の調査ソース・チャンネル設定を全AIエンジンへ保存＆同期完了しました！次回定期巡回からただちに反映されます！');
        onClose();
      } else {
        const errData = await res.json();
        alert(`保存に失敗しました: ${errData.error || '通信エラー'}`);
      }
    } catch (err) {
      console.error(err);
      alert('エラーが発生しました。');
    } finally {
      setSaving(false);
    }
  };

  const handleAddChannel = (e) => {
    e.preventDefault();
    if (!newChName || !newChUrl) {
      alert('チャンネル名とURLの両方を入力してください。');
      return;
    }
    const newEntry = { name: newChName, url: newChUrl, enabled: true };
    setTargetChannels([...targetChannels, newEntry]);
    setNewChName('');
    setNewChUrl('');
  };

  const handleAddWebSource = (e) => {
    e.preventDefault();
    if (!newWebName || !newWebUrl) {
      alert('メディアサイト名とRSS/URLを両方入力してください。');
      return;
    }
    const stype = newWebUrl.includes('reddit.com') ? 'reddit' : 'rss';
    const newEntry = { name: newWebName, url: newWebUrl, type: stype, enabled: true };
    setTargetWebSources([...targetWebSources, newEntry]);
    setNewWebName('');
    setNewWebUrl('');
  };

  if (!isOpen) return null;

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
        <header className={styles.header}>
          <div className={styles.titleBox}>
            <h2>🌐 自律調査ソース＆ターゲットチャンネル 統括パネル</h2>
            <p>AIが30分ごとにショート動画のネタを収集する「調査先サイト・競合」を指一本で編集・監視できます！</p>
          </div>
          <button className={styles.closeButton} onClick={onClose}>×</button>
        </header>

        <div className={styles.body}>
          {loading ? (
            <div style={{ textAlign: 'center', padding: '3rem', color: '#facc15', fontSize: '1.1rem' }}>
              ⚡ 調査ソース構成・最新ステータスを読込中...
            </div>
          ) : (
            <>
              <div className={styles.tabs}>
                <button
                  className={`${styles.tabButton} ${activeTab === 'channels' ? styles.tabActive : ''}`}
                  onClick={() => setActiveTab('channels')}
                >
                  📺 YouTube 競合＆自社モニター ({targetChannels.length})
                </button>
                <button
                  className={`${styles.tabButton} ${activeTab === 'web' ? styles.tabActive : ''}`}
                  onClick={() => setActiveTab('web')}
                >
                  🌍 WEB＆SNS (Reddit/X/Togetter/TikTok) ({targetWebSources.length})
                </button>
              </div>

              {activeTab === 'channels' && (
                <>
                  <div className={styles.cardGrid}>
                    {targetChannels.map((ch, idx) => (
                      <div key={idx} className={styles.itemCard}>
                        <div className={styles.cardTop}>
                          <input
                            type="text"
                            className={styles.cardTitleInput}
                            value={ch.name}
                            onChange={(e) => {
                              const copy = [...targetChannels];
                              copy[idx].name = e.target.value;
                              setTargetChannels(copy);
                            }}
                          />
                          <label className={styles.switch}>
                            <input
                              type="checkbox"
                              checked={ch.enabled !== false}
                              onChange={(e) => {
                                const copy = [...targetChannels];
                                copy[idx].enabled = e.target.checked;
                                setTargetChannels(copy);
                              }}
                            />
                            <span className={styles.slider} />
                          </label>
                        </div>
                        <input
                          type="text"
                          className={styles.cardUrlInput}
                          value={ch.url}
                          onChange={(e) => {
                            const copy = [...targetChannels];
                            copy[idx].url = e.target.value;
                            setTargetChannels(copy);
                          }}
                        />
                        <button
                          className={styles.deleteBtn}
                          onClick={() => setTargetChannels(targetChannels.filter((_, i) => i !== idx))}
                        >
                          🗑 この対象を解除
                        </button>
                      </div>
                    ))}
                  </div>

                  <div className={styles.addSection}>
                    <h3 className={styles.addTitle}>＋ 新しい監視 YouTube チャンネルを追加</h3>
                    <form className={styles.formRow} onSubmit={handleAddChannel}>
                      <input
                        type="text"
                        placeholder="例： 新しいライバルch"
                        className={styles.formInput}
                        value={newChName}
                        onChange={(e) => setNewChName(e.target.value)}
                      />
                      <input
                        type="text"
                        placeholder="例： https://www.youtube.com/@example_handle"
                        className={styles.formInput}
                        style={{ flex: 2 }}
                        value={newChUrl}
                        onChange={(e) => setNewChUrl(e.target.value)}
                      />
                      <button type="submit" className={styles.addButton}>
                        ✨ リストに登録
                      </button>
                    </form>
                  </div>
                </>
              )}

              {activeTab === 'web' && (
                <>
                  <div className={styles.cardGrid}>
                    {targetWebSources.map((src, idx) => (
                      <div key={idx} className={styles.itemCard}>
                        <div className={styles.cardTop}>
                          <input
                            type="text"
                            className={styles.cardTitleInput}
                            value={src.name}
                            onChange={(e) => {
                              const copy = [...targetWebSources];
                              copy[idx].name = e.target.value;
                              setTargetWebSources(copy);
                            }}
                          />
                          <label className={styles.switch}>
                            <input
                              type="checkbox"
                              checked={src.enabled !== false}
                              onChange={(e) => {
                                const copy = [...targetWebSources];
                                copy[idx].enabled = e.target.checked;
                                setTargetWebSources(copy);
                              }}
                            />
                            <span className={styles.slider} />
                          </label>
                        </div>
                        <input
                          type="text"
                          className={styles.cardUrlInput}
                          value={src.url}
                          onChange={(e) => {
                            const copy = [...targetWebSources];
                            copy[idx].url = e.target.value;
                            setTargetWebSources(copy);
                          }}
                        />
                        <button
                          className={styles.deleteBtn}
                          onClick={() => setTargetWebSources(targetWebSources.filter((_, i) => i !== idx))}
                        >
                          🗑 このソースを解除
                        </button>
                      </div>
                    ))}
                  </div>

                  <div className={styles.addSection}>
                    <h3 className={styles.addTitle}>＋ 新しいニュース・掲示板・RSS調査ソースを追加</h3>
                    <form className={styles.formRow} onSubmit={handleAddWebSource}>
                      <input
                        type="text"
                        placeholder="例： 〇〇ゲーム攻略まとめRSS"
                        className={styles.formInput}
                        value={newWebName}
                        onChange={(e) => setNewWebName(e.target.value)}
                      />
                      <input
                        type="text"
                        placeholder="例： https://example.com/rss.xml または Reddit json"
                        className={styles.formInput}
                        style={{ flex: 2 }}
                        value={newWebUrl}
                        onChange={(e) => setNewWebUrl(e.target.value)}
                      />
                      <button type="submit" className={styles.addButton}>
                        ✨ リストに登録
                      </button>
                    </form>
                  </div>
                </>
              )}
            </>
          )}
        </div>

        <footer className={styles.footer}>
          <button className={styles.saveButton} onClick={handleSave} disabled={saving || loading}>
            {saving ? '⏳ クラウド全AIへ反映処理中...' : '🚀 この構成で保存＆ AI 採掘エンジンに即適用！'}
          </button>
        </footer>
      </div>
    </div>
  );
}
