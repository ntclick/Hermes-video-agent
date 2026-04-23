'use client';

import { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import {
  Job, AppSettings,
  API_BASE, createJob, getJobs, getSettings,
  connectWebSocket, deleteJob
} from '@/lib/api';

// ── Helpers ───────────────────────────────────────────
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

  if (!logs) return <div style={{ color: 'var(--text-3)', fontSize: 13, padding: 12 }}>Waiting for logs...</div>;

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

// ── Main Extractor Page ──────────────────────────────────────
export default function Extractor() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null);
  const [selected, setSelected] = useState<Job | null>(null);
  const [url, setUrl] = useState('');
  const [lang, setLang] = useState('vi');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState('');
  const wsRef = useRef<WebSocket | null>(null);
  const [tab, setTab] = useState<'overview' | 'logs'>('overview');

  const fetchAll = async () => {
    try {
      const [j, cfg] = await Promise.all([
        getJobs(50),
        getSettings()
      ]);
      const scriptJobs = j.filter(job => job.target_language.startsWith('script'));
      setJobs(scriptJobs);
      if (cfg) setAppSettings(cfg);
    } catch {}
  };

  useEffect(() => { fetchAll(); const t = setInterval(fetchAll, 5000); return () => clearInterval(t); }, []);

  useEffect(() => {
    if (selected && !['completed', 'failed'].includes(selected.status)) {
      const ws = connectWebSocket(selected.id, (d) => {
        if (d.type === 'job_update') {
          setSelected(d.job);
          setJobs(prev => prev.map(j => j.id === d.job.id ? d.job : j));
        }
      });
      wsRef.current = ws;
      return () => ws.close();
    }
  }, [selected?.id]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    setSubmitting(true); setFormError('');
    try {
      const j = await createJob(url.trim(), `script_${lang}`, false, null);
      setUrl(''); setSelected(j); setTab('logs');
      await fetchAll();
    } catch (e: any) { setFormError(e.message); }
    finally { setSubmitting(false); }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this script extraction job?')) return;
    try { await deleteJob(id); if (selected?.id === id) setSelected(null); await fetchAll(); } catch {}
  };

  return (
    <div className="app-shell">
      {/* ── Top Nav ────────────────────────────────────────── */}
      <nav className="topnav">
        <div className="topnav-brand" style={{ display: 'flex', alignItems: 'center', fontWeight: 700 }}>
          🤖 Content Bridge
          <span style={{ margin: '0 12px', color: 'var(--border)' }}>|</span>
          <Link href="/" className="topnav-link" style={{ marginRight: 16, color: 'var(--text-2)', textDecoration: 'none' }}>🎬 Full Pipeline</Link>
          <Link href="/extractor" className="topnav-link active" style={{ color: 'var(--accent)', textDecoration: 'none' }}>📝 Script Extractor</Link>
        </div>
        <div className="topnav-spacer" />
        <Link href="/settings" className="topnav-btn">⚙️ Settings</Link>
      </nav>

      <div className="hackathon-bar">
        <span>📝 <strong>Script Extractor Mode</strong></span>
        <span style={{ color: 'var(--text-3)' }}>·</span>
        <span>Download → Transcribe → Kimi K2.6 Script Rewrite</span>
        <span style={{ color: 'var(--text-3)' }}>·</span>
        <span>Bypasses rendering and publishing</span>
      </div>

      <div className="main-content">
        {/* ── Sidebar ──────────────────────────────────────── */}
        <aside className="sidebar">
          <div className="sidebar-section">
            <h2 className="sidebar-section-title">New Script Job</h2>
            <form onSubmit={handleSubmit}>
              <div className="url-row">
                <input
                  className="url-field"
                  type="url"
                  placeholder="Paste YouTube / TikTok / Douyin URL"
                  value={url}
                  onChange={e => setUrl(e.target.value)}
                  disabled={submitting}
                  required
                />
              </div>
              <div className="options-row" style={{ marginTop: 12, marginBottom: 12 }}>
                <select className="select-sm" value={lang} onChange={e => setLang(e.target.value)}>
                  <option value="vi">🇻🇳 Vietnamese</option>
                  <option value="en">🇬🇧 English</option>
                  <option value="zh">🇨🇳 Chinese</option>
                  <option value="ja">🇯🇵 Japanese</option>
                  <option value="ko">🇰🇷 Korean</option>
                </select>
              </div>
              {formError && <div className="error-banner">⚠️ {formError}</div>}
              <button type="submit" className="btn-primary" disabled={submitting || !url.trim()}>
                {submitting ? <><span className="spinner" />Extracting...</> : '✨ Extract Script'}
              </button>
            </form>
          </div>

          <div className="job-list-header">
            <h3>Extracted Scripts</h3>
            <button className="btn-ghost" onClick={fetchAll}>↻ Refresh</button>
          </div>
          
          <div className="job-list-wrap">
            {jobs.length === 0 && (
              <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>
                No script extractions yet
              </div>
            )}
            
            {jobs.map(j => (
              <div
                key={j.id}
                className={`job-card fade-up ${selected?.id === j.id ? 'active' : ''}`}
                onClick={() => { setSelected(j); setTab('overview'); }}
              >
                <div className="job-card-top">
                  <PlatBadge p={j.platform} />
                  <span className="job-card-title">{j.title || `Extraction #${j.id}`}</span>
                  <StatusBadge status={j.status} />
                </div>
                
                <ProgBar progress={j.progress} status={j.status} />
                <div className="job-card-meta">
                  <span>{j.url.slice(0, 40)}…</span>
                  <button className="btn-ghost" style={{ padding: '0 4px', height: '20px' }} onClick={(e) => { e.stopPropagation(); handleDelete(j.id); }}>×</button>
                </div>
              </div>
            ))}
          </div>
        </aside>

        {/* ── Main View ────────────────────────────────────── */}
        <main className="detail-panel">
          {!selected ? (
            <div className="detail-empty">
              <div className="detail-empty-icon">📝</div>
              <div style={{ fontSize: 16, color: 'var(--text-1)', marginBottom: 8, fontWeight: 500 }}>Script Extractor</div>
              <div style={{ fontSize: 14, color: 'var(--text-2)', maxWidth: 300, textAlign: 'center' }}>Submit a video URL on the left to extract the transcript and generate a creative rewritten script.</div>
            </div>
          ) : (
            <>
              <div className="detail-tabs">
                <button className={`detail-tab ${tab === 'overview' ? 'active' : ''}`} onClick={() => setTab('overview')}>Overview</button>
                <button className={`detail-tab ${tab === 'logs' ? 'active' : ''}`} onClick={() => setTab('logs')}>Live Logs</button>
              </div>

              <div className="detail-body fade-up">
                {tab === 'logs' ? (
                  <LogViewer logs={selected.logs} />
                ) : (
                  <>
                    <div className="info-row">
                      <div className="info-row-icon">
                        <PlatBadge p={selected.platform} />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 4 }}>{selected.title || `Job #${selected.id}`}</div>
                        <div style={{ fontSize: 12, color: 'var(--text-3)', fontFamily: 'var(--mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {selected.url}
                        </div>
                      </div>
                      <StatusBadge status={selected.status} />
                    </div>

                    {selected.status !== 'completed' && selected.status !== 'failed' && (
                       <div className="agent-card" style={{ marginTop: 20 }}>
                         <div className="agent-card-title"><span className="agent-pulse" /> Extraction in progress</div>
                         <div className="agent-card-action">Hermes is currently processing the video...</div>
                         <div style={{ marginTop: 12 }}>
                           <ProgBar progress={selected.progress} status={selected.status} />
                         </div>
                       </div>
                    )}

                    {selected.status === 'completed' && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                        {selected.script_json && (
                          <div className="agent-card" style={{ background: 'var(--surface-1)' }}>
                            <div className="agent-card-title" style={{ color: 'var(--accent)', display: 'flex', justifyContent: 'space-between' }}>
                              <span>✨ Rewritten AI Script</span>
                              <span style={{ fontSize: 12, color: 'var(--text-3)' }}>{selected.target_language.replace('script_', '').toUpperCase()}</span>
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 16 }}>
                              {JSON.parse(selected.script_json).map((scene: any, i: number) => (
                                <div key={i} style={{ padding: 16, background: 'var(--bg-base)', borderRadius: 8, border: '1px solid var(--border)', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}>
                                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                                    <div style={{ fontSize: 12, color: 'var(--text-3)', fontWeight: 600, letterSpacing: 1 }}>SCENE {scene.scene_number || i + 1}</div>
                                    <div style={{ fontSize: 11, color: 'var(--text-3)', background: 'var(--surface-1)', padding: '2px 8px', borderRadius: 12 }}>⏱ {scene.duration || 5}s</div>
                                  </div>
                                  <div style={{ fontSize: 15, color: 'var(--text-1)', marginBottom: 16, lineHeight: 1.6 }}>
                                    {scene.narration}
                                  </div>
                                  <div style={{ fontSize: 13, color: 'var(--text-2)', background: 'var(--bg-surface)', padding: '10px 12px', borderRadius: 6, borderLeft: '3px solid var(--accent)' }}>
                                    <strong style={{ opacity: 0.8 }}>🎨 Prompt:</strong> {scene.image_prompt}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {selected.transcript && (
                          <div className="agent-card" style={{ background: 'var(--bg-base)' }}>
                            <div className="agent-card-title">📜 Raw Spoken Transcript</div>
                            <div style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.6, whiteSpace: 'pre-wrap', marginTop: 12 }}>
                              {selected.transcript}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
