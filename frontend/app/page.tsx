'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import Link from 'next/link';
import {
  Job, JobStats, XAccount, AppSettings,
  API_BASE, createJob, getJobs, getStats, getXAccounts, getSettings,
  retryJob, connectWebSocket, deleteJob, generateCover,
  updateJob, regenerateCover, rewriteScript, writeScript, cancelJob, publishJob,
} from '@/lib/api';

// ── Agent activity per pipeline stage ──────────────────────
const STAGE: Record<string, { label: string; tool: string; svc: string }> = {
  pending:      { label: 'Queued',                                   tool: '—',                     svc: 'Queue' },
  downloading:  { label: 'Fetching source video',                    tool: 'download_video',        svc: 'yt-dlp' },
  transcribing: { label: 'Transcribing speech',                      tool: 'transcribe_video',      svc: 'Whisper' },
  translating:  { label: 'Translating + writing caption',            tool: 'translate_content',     svc: 'Kimi K2.6' },
  rendering:    { label: 'Burning subtitles into video',             tool: 'render_with_subtitles', svc: 'FFmpeg' },
  publishing:   { label: 'Publishing to X / Twitter',                tool: 'publish_to_x',          svc: 'Playwright' },
  completed:    { label: 'Pipeline complete',                         tool: '—',                     svc: '—' },
  failed:       { label: 'Pipeline halted',                          tool: '—',                     svc: '—' },
};

const STEPS = ['downloading', 'transcribing', 'translating', 'rendering', 'publishing'];

function stepIdx(status: string) {
  if (status === 'completed') return STEPS.length;
  if (status === 'failed') return -1;
  return STEPS.indexOf(status);
}

// ── Small helpers ───────────────────────────────────────────
function PlatBadge({ p }: { p: string | null }) {
  const key = p || 'other';
  const labels: Record<string, string> = { youtube: 'YT', tiktok: 'TK', douyin: 'DY', other: '?' };
  return <span className={`plat ${key}`}>{labels[key] ?? '?'}</span>;
}

function StatusBadge({ status }: { status: string }) {
  const active = !['completed', 'failed', 'pending'].includes(status);
  return (
    <span className={`badge ${status}`}>
      {active && <span className="pulse" />}
      {status}
    </span>
  );
}

function PipelineTrack({ status }: { status: string }) {
  const cur = stepIdx(status);
  return (
    <div className="pipeline-track">
      {STEPS.map((s, i) => {
        let cls = '';
        if (status === 'failed') cls = i <= Math.max(cur, 0) ? 'error' : '';
        else if (i < cur) cls = 'done';
        else if (i === cur) cls = 'active';
        return <div key={s} className={`pipeline-seg ${cls}`} title={s} />;
      })}
    </div>
  );
}

function ProgBar({ progress, status }: { progress: number; status: string }) {
  const cls = status === 'completed' ? 'done' : status === 'failed' ? 'fail' : '';
  return <div className="prog-bar"><div className={`prog-fill ${cls}`} style={{ width: `${Math.min(progress, 100)}%` }} /></div>;
}

// ── Log Viewer ──────────────────────────────────────────────
function LogViewer({ logs }: { logs: string | null }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [logs]);

  if (!logs) return <div style={{ color: 'var(--text-3)', fontSize: 13, padding: 12 }}>No logs yet.</div>;

  return (
    <div className="log-wrap" ref={ref}>
      {logs.split('\n').map((line, i) => {
        const isTool  = line.includes('[Hermes → tool]');
        const isAgent = line.includes('[Hermes Agent]') && !isTool;
        const isErr   = line.includes('❌') || line.includes('FAIL');
        const isOk    = line.includes('✅') || line.includes('🎉');
        const cls = isTool ? 'tool' : isAgent ? 'agent' : isErr ? 'err' : isOk ? 'ok' : '';
        return <div key={i} className={`log-line ${cls}`}>{line}</div>;
      })}
    </div>
  );
}

// ── Main Dashboard ──────────────────────────────────────────
export default function Dashboard() {
  const [jobs, setJobs]                 = useState<Job[]>([]);
  const [stats, setStats]               = useState<JobStats | null>(null);
  const [appSettings, setAppSettings]   = useState<AppSettings | null>(null);
  const [xAccounts, setXAccounts]       = useState<XAccount[]>([]);
  const [selected, setSelected]         = useState<Job | null>(null);
  const [tab, setTab]                   = useState<'overview' | 'logs' | 'video'>('overview');

  const [url, setUrl]           = useState('');
  const [lang, setLang]         = useState('vi');
  const [autoPublish, setAutoPublish] = useState(true);
  const [xAccountId, setXAccountId]   = useState<number | ''>('');
  const [submitting, setSubmitting]   = useState(false);
  const [formError, setFormError]     = useState('');

  // Editing state
  const [editingTweet, setEditingTweet]     = useState(false);
  const [tweetDraft, setTweetDraft]         = useState('');
  const [savingTweet, setSavingTweet]       = useState(false);
  const [coverBusy, setCoverBusy]           = useState<null | 'regen' | 'rewrite' | 'generate'>(null);
  const [lightboxUrl, setLightboxUrl]       = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  const fetchAll = useCallback(async () => {
    try {
      const [j, s, a, cfg] = await Promise.all([
        getJobs(), getStats(), getXAccounts(), getSettings().catch(() => null),
      ]);
      setJobs(j); setStats(s); setXAccounts(a);
      if (cfg) setAppSettings(cfg);
      if (a.length > 0 && xAccountId === '') setXAccountId(a[0].id);
    } catch {}
  }, []);

  useEffect(() => { fetchAll(); const t = setInterval(fetchAll, 5000); return () => clearInterval(t); }, [fetchAll]);

  // WebSocket for live updates on selected job
  useEffect(() => {
    if (selected && !['completed', 'failed', 'cancelled'].includes(selected.status)) {
      const ws = connectWebSocket(selected.id, (d) => {
        if (d.type === 'job_update') {
          setSelected(d.job);
          setJobs(prev => prev.map(j => j.id === d.job.id ? d.job : j));
        }
      });
      wsRef.current = ws;
      return () => ws.close();
    }
  }, [selected?.id, selected?.status]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    setSubmitting(true); setFormError('');
    try {
      const j = await createJob(url.trim(), lang, autoPublish, xAccountId !== '' ? Number(xAccountId) : null);
      setUrl(''); setSelected(j); setTab('overview');
      await fetchAll();
    } catch (e: any) { setFormError(e.message); }
    finally { setSubmitting(false); }
  };

  const handleRetry = async (id: number) => {
    try { const j = await retryJob(id); setSelected(j); await fetchAll(); } catch (e: any) { setFormError(e.message); }
  };

  const handleCancel = async (id: number) => {
    if (!confirm("Are you sure you want to cancel this job?")) return;
    try { 
      await cancelJob(id); 
      await fetchAll();
      // Update selected state locally if it's the one we're viewing
      if (selected && selected.id === id) {
        setSelected({ ...selected, status: 'cancelled' });
      }
    } catch (e: any) { setFormError(e.message); }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this job?')) return;
    try { await deleteJob(id); if (selected?.id === id) setSelected(null); await fetchAll(); } catch {}
  };

  const handlePublishJob = async (id: number) => {
    try {
      await publishJob(id, xAccountId || undefined);
      // Optimistically flip to 'publishing' so WS reconnects and logs stream live
      setSelected(prev => prev && prev.id === id ? { ...prev, status: 'publishing' } : prev);
      setJobs(prev => prev.map(j => j.id === id ? { ...j, status: 'publishing' } : j));
      setTab('logs');
    } catch (e: any) { setFormError(e.message); }
  };

  // Tweet editing
  const handleEditTweet = () => {
    setTweetDraft(selected?.tweet_text || '');
    setEditingTweet(true);
  };

  const handleSaveTweet = async () => {
    if (!selected) return;
    setSavingTweet(true);
    try {
      const updated = await updateJob(selected.id, { tweet_text: tweetDraft });
      setSelected(updated);
      setJobs(prev => prev.map(j => j.id === updated.id ? updated : j));
      setEditingTweet(false);
    } catch (e: any) { alert(e.message); }
    finally { setSavingTweet(false); }
  };

  // Cover actions
  const handleGenerateCover = async () => {
    if (!selected) return;
    setCoverBusy('generate');
    try { await generateCover(selected.id); setTab('logs'); }
    catch (e: any) { alert(e.message); }
    finally { setCoverBusy(null); }
  };

  const handleRegenerateCover = async () => {
    if (!selected) return;
    setCoverBusy('regen');
    try { await regenerateCover(selected.id); setTab('logs'); }
    catch (e: any) { alert(e.message); }
    finally { setCoverBusy(null); }
  };

  const handleRewriteScript = async () => {
    if (!selected) return;
    setCoverBusy('rewrite');
    try { await rewriteScript(selected.id); setTab('logs'); }
    catch (e: any) { alert(e.message); }
    finally { setCoverBusy(null); }
  };

  const handleWriteScript = async () => {
    if (!selected) return;
    setCoverBusy('rewrite');
    try { await writeScript(selected.id); setTab('logs'); }
    catch (e: any) { alert(e.message); }
    finally { setCoverBusy(null); }
  };

  const stage = selected ? (STAGE[selected.status] ?? STAGE.pending) : null;
  const isActive = selected ? !['completed', 'failed', 'pending'].includes(selected.status) : false;
  const selectedAccount = selected?.x_account_id ? xAccounts.find(a => a.id === selected.x_account_id) : null;

  // Parse script_json for display
  let parsedScenes: any[] = [];
  if (selected?.script_json) {
    try { parsedScenes = JSON.parse(selected.script_json); } catch {}
  }

  return (
    <div className="app-shell">

      {/* Top Nav */}
      <nav className="topnav">
        <div className="topnav-brand">
          🤖 Content Bridge
          <span style={{ margin: '0 12px', color: 'var(--border)' }}>|</span>
          <Link href="/" className="topnav-link active" style={{ marginRight: 16 }}>🎬 Full Pipeline</Link>
          <Link href="/extractor" className="topnav-link" style={{ color: 'var(--text-2)' }}>📝 Script Extractor</Link>
        </div>

        <div className="topnav-spacer" />

        {stats && (
          <div style={{ display: 'flex', gap: 6 }}>
            <span className="status-chip"><span className="dot" style={{ background: 'var(--green)' }} />{stats.completed}</span>
            <span className="status-chip"><span className="dot" style={{ background: 'var(--accent)' }} />{stats.processing}</span>
            {stats.failed > 0 && <span className="status-chip"><span className="dot" style={{ background: 'var(--red)' }} />{stats.failed}</span>}
          </div>
        )}

        <Link href="/settings" className="topnav-btn">⚙️ Settings</Link>
      </nav>

      {/* Hackathon Bar */}
      <div className="hackathon-bar">
        <span>🤖 Hermes Agent Hackathon</span>
        <span style={{ color: 'var(--text-3)' }}>·</span>
        <span><span className="hl">Hermes</span> orchestrates via function-calling</span>
        <span style={{ color: 'var(--text-3)' }}>·</span>
        <span><span className="hl">Kimi K2.6</span> translates + writes captions</span>
        <span style={{ color: 'var(--text-3)' }}>·</span>
        <span>model: {appSettings?.hermes_model ?? '…'}</span>
      </div>

      <div className="main-content">

        {/* ── Sidebar ──────────────────────────────────────── */}
        <aside className="sidebar">

          {/* Submit Form */}
          <div className="sidebar-section">
            <form onSubmit={handleSubmit}>
              <div className="url-row">
                <input
                  className="url-field"
                  type="url"
                  placeholder="YouTube / TikTok / Douyin URL"
                  value={url}
                  onChange={e => setUrl(e.target.value)}
                  required
                />
              </div>

              <div className="options-row">
                <select className="select-sm" value={lang} onChange={e => setLang(e.target.value)}>
                  <option value="vi">🇻🇳 Vietnamese</option>
                  <option value="en">🇬🇧 English</option>
                  <option value="zh">🇨🇳 Chinese</option>
                  <option value="ja">🇯🇵 Japanese</option>
                  <option value="ko">🇰🇷 Korean</option>
                </select>

                <label className={`toggle-pill ${autoPublish ? 'active' : ''}`}>
                  <input type="checkbox" checked={autoPublish} onChange={e => setAutoPublish(e.target.checked)} />
                  🐦 Auto-post
                </label>
              </div>

              {autoPublish && xAccounts.length > 0 && (
                <div style={{ marginBottom: 10 }}>
                  <select
                    className="select-sm"
                    style={{ width: '100%' }}
                    value={xAccountId}
                    onChange={e => setXAccountId(e.target.value === '' ? '' : Number(e.target.value))}
                  >
                    {xAccounts.map(a => (
                      <option key={a.id} value={a.id}>{a.name ?? 'Account'} (@{a.username})</option>
                    ))}
                  </select>
                </div>
              )}

              {formError && <div className="error-banner">⚠️ {formError}</div>}

              <button className="btn-primary" type="submit" disabled={submitting || !url.trim()}>
                {submitting ? <><span className="spinner" />Processing…</> : '🚀 Start Hermes'}
              </button>
            </form>
          </div>

          {/* Job List */}
          <div className="job-list-header">
            <h3>Jobs</h3>
            <button className="btn-ghost" onClick={fetchAll}>↻ Refresh</button>
          </div>

          <div className="job-list-wrap">
            {jobs.length === 0 ? (
              <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>
                No jobs yet — paste a URL above
              </div>
            ) : (
              jobs.map(job => (
                <div
                  key={job.id}
                  className={`job-card fade-up ${selected?.id === job.id ? 'active' : ''}`}
                  onClick={() => { setSelected(job); setTab('overview'); setEditingTweet(false); }}
                >
                  <div className="job-card-top">
                    <PlatBadge p={job.platform} />
                    <span className="job-card-title">{job.title || `Job #${job.id}`}</span>
                    <StatusBadge status={job.status} />
                  </div>
                  <PipelineTrack status={job.status} />
                  <ProgBar progress={job.progress} status={job.status} />
                  <div className="job-card-meta">
                    <span>{job.url.slice(0, 40)}…</span>
                    <span>{job.created_at ? new Date(job.created_at).toLocaleTimeString() : ''}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </aside>

        {/* ── Detail Panel ─────────────────────────────────── */}
        <main className="detail-panel">
          {!selected ? (
            <div className="detail-empty">
              <div className="detail-empty-icon">👈</div>
              <div style={{ fontSize: 14, color: 'var(--text-2)' }}>Select a job to view details</div>
            </div>
          ) : (
            <>
              {/* Tab Bar */}
              <div className="detail-tabs">
                <button className={`detail-tab ${tab === 'overview' ? 'active' : ''}`} onClick={() => setTab('overview')}>Overview</button>
                <button className={`detail-tab ${tab === 'video' ? 'active' : ''}`} onClick={() => setTab('video')}>Video</button>
                <button className={`detail-tab ${tab === 'logs' ? 'active' : ''}`} onClick={() => setTab('logs')}>
                  Logs {selected.logs && <span style={{ fontSize: 10, color: 'var(--text-3)', marginLeft: 4 }}>{selected.logs.split('\n').length}</span>}
                </button>
              </div>

              <div className="detail-body fade-up">

                {/* ── Overview Tab ──────────────────────────── */}
                {tab === 'overview' && (
                  <>
                    {/* Status Row */}
                    <div className="info-row">
                      <div className="info-row-icon">
                        <PlatBadge p={selected.platform} />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 4 }}>{selected.title || `Job #${selected.id}`}</div>
                        <div style={{ fontSize: 12, color: 'var(--text-3)', fontFamily: 'var(--mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {selected.url}
                        </div>
                        <div style={{ display: 'flex', gap: 12, marginTop: 6, flexWrap: 'wrap' }}>
                          {selected.duration && (
                            <span style={{ fontSize: 12, color: 'var(--text-3)' }}>
                              ⏱ {Math.round(selected.duration)}s
                            </span>
                          )}
                          {selectedAccount && (
                            <span className="x-account-badge">
                              🐦 @{selectedAccount.username}
                            </span>
                          )}
                        </div>
                      </div>
                      <StatusBadge status={selected.status} />
                    </div>

                    {/* Pipeline Progress */}
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--text-3)', marginBottom: 6 }}>
                        <span>Pipeline progress</span>
                        <span>{selected.progress.toFixed(0)}%</span>
                      </div>
                      <PipelineTrack status={selected.status} />
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
                        {STEPS.map((s, i) => {
                          const cur = stepIdx(selected.status);
                          const isD = i < cur;
                          const isA = i === cur;
                          return (
                            <span key={s} style={{ fontSize: 10, color: isD ? 'var(--green)' : isA ? 'var(--accent)' : 'var(--text-3)', textTransform: 'capitalize' }}>
                              {s.slice(0, 5)}
                            </span>
                          );
                        })}
                      </div>
                    </div>

                    {/* Hermes Agent Activity */}
                    {stage && (
                      <div className="agent-card">
                        <div className="agent-card-title">
                          {isActive && <span className="agent-pulse" />}
                          Hermes Agent
                        </div>
                        <div className="agent-card-action">{stage.label}</div>
                        <div className="agent-card-meta">
                          <span>tool: <span className="tool">{stage.tool}</span></span>
                          <span>service: <span className="svc">{stage.svc}</span></span>
                        </div>
                      </div>
                    )}

                    {/* Error */}
                    {selected.error_message && (
                      <div className="error-box">❌ {selected.error_message}</div>
                    )}

                    {/* Keyframes */}
                    {selected.frames_path && (
                      <div className="summary-box">
                        <div className="box-label" style={{ marginBottom: 6 }}>🎞️ Keyframes</div>
                        <div className="frames-strip">
                          {[1,2,3,4,5].map(n => {
                            const imgUrl = `${API_BASE}/api/videos/${selected.id}/frames/frame_00${n}.jpg`;
                            return (
                              <img
                                key={n}
                                src={imgUrl}
                                alt={`frame ${n}`}
                                onClick={() => setLightboxUrl(imgUrl)}
                                onError={e => { (e.target as HTMLImageElement).style.display = 'none'; }}
                                style={{ cursor: 'pointer' }}
                              />
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* AI Summary */}
                    {selected.summary && (
                      <div className="summary-box">
                        <div className="box-label">🧠 AI Summary</div>
                        <div className="summary-text">{selected.summary}</div>
                      </div>
                    )}

                    {/* Publish Section — all completed jobs */}
                    {selected.status === 'completed' && (
                      <div className="summary-box">
                        {selected.tweet_id ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                            <div className="box-label" style={{ color: 'var(--green)' }}>✅ Posted to X</div>
                            <a href={`https://x.com/i/status/${selected.tweet_id}`} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)', fontSize: 13 }}>
                              View tweet →
                            </a>
                            {selected.output_path && (
                              <a href={`${API_BASE}/api/videos/${selected.id}/output.mp4`} download style={{ color: 'var(--text-3)', fontSize: 12 }}>
                                ⬇️ Download video
                              </a>
                            )}
                          </div>
                        ) : (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                            <div className="box-label">🐦 Post to X</div>

                            {/* Tweet caption editor */}
                            <div>
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                                <span style={{ fontSize: 11, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Caption</span>
                                {!editingTweet && selected.tweet_text && (
                                  <button className="btn-ghost btn-xs" onClick={handleEditTweet}>✏️ Edit</button>
                                )}
                              </div>
                              {editingTweet ? (
                                <div>
                                  <textarea
                                    className="tweet-textarea"
                                    value={tweetDraft}
                                    onChange={e => setTweetDraft(e.target.value)}
                                    rows={4}
                                  />
                                  <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                                    <button className="btn-save btn-sm" onClick={handleSaveTweet} disabled={savingTweet}>
                                      {savingTweet ? '⏳ Saving...' : '💾 Save'}
                                    </button>
                                    <button className="btn-ghost btn-sm" onClick={() => setEditingTweet(false)}>Cancel</button>
                                  </div>
                                </div>
                              ) : (
                                <div className="tweet-text-display">
                                  {selected.tweet_text || <span style={{ color: 'var(--text-3)', fontStyle: 'italic' }}>Auto-generated on post</span>}
                                </div>
                              )}
                            </div>

                            {/* Account selector + Post button */}
                            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                              {xAccounts.length > 0 ? (
                                <select
                                  value={xAccountId ?? ''}
                                  onChange={e => setXAccountId(e.target.value ? Number(e.target.value) : '')}
                                  style={{ padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--surface-2)', color: 'var(--text-1)', fontSize: 13, cursor: 'pointer', flex: 1, minWidth: 0 }}
                                >
                                  <option value="">— Select account —</option>
                                  {xAccounts.map(a => (
                                    <option key={a.id} value={a.id}>🐦 @{a.username}</option>
                                  ))}
                                </select>
                              ) : (
                                <span style={{ fontSize: 12, color: 'var(--text-3)', flex: 1 }}>No accounts — add one in Settings</span>
                              )}
                              <button
                                className="btn btn-primary"
                                style={{ padding: '6px 14px', whiteSpace: 'nowrap' }}
                                onClick={() => handlePublishJob(selected.id)}
                              >
                                🚀 Post to X
                              </button>
                            </div>

                            {selected.output_path && (
                              <a href={`${API_BASE}/api/videos/${selected.id}/output.mp4`} download style={{ color: 'var(--text-3)', fontSize: 12 }}>
                                ⬇️ Download video
                              </a>
                            )}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Actions */}
                    <div className="actions-bar">
                      {selected.status === 'failed' && (
                        <>
                          <button className="btn-ghost" onClick={() => handleRetry(selected.id)}>🔄 Retry</button>
                          <button className="btn-danger" onClick={() => handleDelete(selected.id)}>🗑 Delete</button>
                        </>
                      )}
                      {['pending', 'downloading', 'transcribing', 'translating', 'rendering', 'publishing'].includes(selected.status) && (
                        <button className="btn-danger" onClick={() => handleCancel(selected.id)}>⏹ Cancel</button>
                      )}
                      {selected.tweet_id && (
                        <a href={`https://x.com/i/status/${selected.tweet_id}`} target="_blank" rel="noopener noreferrer" className="btn-ghost">
                          🐦 View on X
                        </a>
                      )}
                      {selected.status === 'completed' && selected.summary && !selected.cover_path && (
                        <button className="btn-accent2" onClick={handleGenerateCover} disabled={coverBusy !== null}>
                          {coverBusy === 'generate' ? '⏳ Generating...' : '🎬 Generate AI Cover'}
                        </button>
                      )}
                      {selected.ai_scenes_path && (
                        <button className="btn-ghost" onClick={handleRegenerateCover} disabled={coverBusy !== null}>
                          {coverBusy === 'regen' ? '⏳ Composing...' : '🔄 Re-compose Cover'}
                        </button>
                      )}
                      {selected.status === 'completed' && selected.summary && (
                        <button className="btn-accent2" onClick={handleRewriteScript} disabled={coverBusy !== null}>
                          {coverBusy === 'rewrite' ? '⏳ Rewriting...' : '📜 Rewrite Cover'}
                        </button>
                      )}
                      {selected.status === 'completed' && selected.transcript && (
                        <button className="btn-ghost" style={{ borderColor: 'var(--accent)', color: 'var(--accent)' }} onClick={handleWriteScript} disabled={coverBusy !== null}>
                          {coverBusy === 'rewrite' ? '⏳ Writing...' : '✍️ Write Script'}
                        </button>
                      )}
                      {selected.status === 'completed' && (
                        <button className="btn-ghost" onClick={() => setTab('video')}>▶️ Watch Video</button>
                      )}
                    </div>

                    {/* AI Scenes preview */}
                    {selected.ai_scenes_path && (
                      <div className="summary-box">
                        <div className="box-label">🎨 AI Scenes (FLUX)</div>
                        <div className="frames-strip" style={{ marginTop: 8 }}>
                          {[1,2,3,4,5].map(n => (
                            <img
                              key={n}
                              src={`${API_BASE}/api/videos/${selected.id}/ai_scenes/scene_0${n}.jpg`}
                              alt={`scene ${n}`}
                              style={{ height: 90 }}
                              onError={e => { (e.target as HTMLImageElement).style.display = 'none'; }}
                            />
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Script JSON display */}
                    {parsedScenes.length > 0 && (
                      <div className="summary-box">
                        <div className="box-label">📜 Cover Script ({parsedScenes.length} scenes)</div>
                        <div className="script-scenes">
                          {parsedScenes.map((scene: any, i: number) => (
                            <div key={i} className="script-scene-item">
                              <div className="script-scene-num">Scene {scene.scene || i + 1}</div>
                              <div className="script-scene-narration">{scene.narration}</div>
                              <div className="script-scene-prompt">{scene.image_prompt}</div>
                              {scene.duration && <span className="script-scene-dur">{scene.duration}s</span>}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}

                {/* ── Video Tab ─────────────────────────────── */}
                {tab === 'video' && (
                  <>
                    {(selected.status === 'completed' || selected.progress >= 90) ? (
                      <div className="video-player-section">
                        {/* Source Video */}
                        <div className="video-player-wrap">
                          <div className="video-player-header">
                            <label>🎬 Output (Subtitled)</label>
                            <a
                              href={`${API_BASE}/api/videos/${selected.id}/output.mp4`}
                              download
                              className="btn-ghost btn-xs"
                            >
                              ⬇ Download
                            </a>
                          </div>
                          <video
                            controls
                            className="video-main"
                            src={`${API_BASE}/api/videos/${selected.id}/output.mp4`}
                            onError={e => {
                              const v = e.target as HTMLVideoElement;
                              if (!v.src.endsWith('compressed.mp4')) v.src = `${API_BASE}/api/videos/${selected.id}/output_compressed.mp4`;
                            }}
                          />
                        </div>

                        {/* AI Cover Video */}
                        {selected.cover_path && (
                          <div className="video-player-wrap">
                            <div className="video-player-header">
                              <label>🎨 AI Cover Video</label>
                              <a
                                href={`${API_BASE}/api/videos/${selected.id}/cover_output.mp4`}
                                download
                                className="btn-ghost btn-xs"
                              >
                                ⬇ Download
                              </a>
                            </div>
                            <video
                              controls
                              className="video-main"
                              src={`${API_BASE}/api/videos/${selected.id}/cover_output.mp4`}
                            />
                          </div>
                        )}
                      </div>
                    ) : (
                      <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>
                        Video will be available once rendering is complete ({selected.progress.toFixed(0)}%)
                      </div>
                    )}
                  </>
                )}

                {/* ── Logs Tab ──────────────────────────────── */}
                {tab === 'logs' && (
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 400 }}>
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 8, fontFamily: 'var(--mono)' }}>
                      Hermes Agent trace — {selected.logs?.split('\n').length ?? 0} lines
                    </div>
                    <LogViewer logs={selected.logs} />
                  </div>
                )}

              </div>
            </>
          )}
        </main>
      </div>

      {/* ── Keyframe Lightbox ────────────────────── */}
      {lightboxUrl && (
        <div
          className="lightbox-overlay"
          onClick={() => setLightboxUrl(null)}
        >
          <div className="lightbox-content" onClick={e => e.stopPropagation()}>
            <button className="lightbox-close" onClick={() => setLightboxUrl(null)}>✕</button>
            <img src={lightboxUrl} alt="Keyframe preview" />
          </div>
        </div>
      )}
    </div>
  );
}
