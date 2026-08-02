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
  const [scheduleSources, setScheduleSources] = useState([]);
  // settings は画面に出さないが、保存時に丸ごと書き戻すので取得した値を保持しておく。
  // ここを固定値で組み直すと auto_source_expansion などが保存のたびに消えてしまう。
  const [settings, setSettings] = useState(null);

  // 新規登録用の入力State
  const [newChName, setNewChName] = useState('');
  const [newChUrl, setNewChUrl] = useState('');
  const [newWebName, setNewWebName] = useState('');
  const [newWebUrl, setNewWebUrl] = useState('');
  const [newScheduleName, setNewScheduleName] = useState('');
  const [newScheduleUrl, setNewScheduleUrl] = useState('');

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
          setScheduleSources(data.config.schedule_sources || []);
          setSettings(data.config.settings || null);
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

  useEffect(() => {
    if (isOpen) {
      // setLoading(true) が同期的に走る点を react-hooks/set-state-in-effect が指摘するが、
      // モーダルを開いた瞬間にローディング表示するための意図した挙動のため許容する。
      // eslint-disable-next-line react-hooks/set-state-in-effect
      fetchConfig();
    }
  }, [isOpen]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = {
        config: {
          target_channels: targetChannels,
          target_web_sources: targetWebSources,
          schedule_sources: scheduleSources,
          settings: settings || {
            target_items_per_run: 12,
            min_score_threshold: 60,
            enable_gemini_summary: true,
            auto_source_expansion: true
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

  const handleAddScheduleSource = (e) => {
    e.preventDefault();
    if (!newScheduleName || !newScheduleUrl) {
      alert('サイト名とURLを両方入力してください。');
      return;
    }
    const newEntry = { name: newScheduleName, url: newScheduleUrl, enabled: true };
    setScheduleSources([...scheduleSources, newEntry]);
    setNewScheduleName('');
    setNewScheduleUrl('');
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
                <button
                  className={`${styles.tabButton} ${activeTab === 'schedule' ? styles.tabActive : ''}`}
                  onClick={() => setActiveTab('schedule')}
                >
                  📅 更新カレンダー情報源 ({scheduleSources.length})
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

              {activeTab === 'schedule' && (
                <>
                  <p style={{ color: '#94a3b8', fontSize: '0.85rem', margin: '0 0 1rem' }}>
                    新キャラ・バージョン実装予定日などを定期チェックする情報源です。約20時間に1回、AIが表を読み取ってスケジュールを更新します（リーク・非公式情報を含むため画面上には「未確定」表示が付きます）。
                  </p>
                  <div className={styles.cardGrid}>
                    {scheduleSources.map((src, idx) => (
                      <div key={idx} className={styles.itemCard}>
                        <div className={styles.cardTop}>
                          <input
                            type="text"
                            className={styles.cardTitleInput}
                            value={src.name}
                            onChange={(e) => {
                              const copy = [...scheduleSources];
                              copy[idx].name = e.target.value;
                              setScheduleSources(copy);
                            }}
                          />
                          <label className={styles.switch}>
                            <input
                              type="checkbox"
                              checked={src.enabled !== false}
                              onChange={(e) => {
                                const copy = [...scheduleSources];
                                copy[idx].enabled = e.target.checked;
                                setScheduleSources(copy);
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
                            const copy = [...scheduleSources];
                            copy[idx].url = e.target.value;
                            setScheduleSources(copy);
                          }}
                        />
                        <button
                          className={styles.deleteBtn}
                          onClick={() => setScheduleSources(scheduleSources.filter((_, i) => i !== idx))}
                        >
                          🗑 この情報源を解除
                        </button>
                      </div>
                    ))}
                  </div>

                  <div className={styles.addSection}>
                    <h3 className={styles.addTitle}>＋ 新しいスケジュール情報源を追加</h3>
                    <form className={styles.formRow} onSubmit={handleAddScheduleSource}>
                      <input
                        type="text"
                        placeholder="例： 攻略Wikiのバナースケジュールページ"
                        className={styles.formInput}
                        value={newScheduleName}
                        onChange={(e) => setNewScheduleName(e.target.value)}
                      />
                      <input
                        type="text"
                        placeholder="例： https://example.com/banner-schedule"
                        className={styles.formInput}
                        style={{ flex: 2 }}
                        value={newScheduleUrl}
                        onChange={(e) => setNewScheduleUrl(e.target.value)}
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
