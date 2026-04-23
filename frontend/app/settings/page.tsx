'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  AppSettings,
  SettingsUpdate,
  getSettings,
  updateSettings,
  testKimiConnection,
  testHermesConnection,
  saveDouyinCookies,
  testDouyinCookies,
  XAccount,
  getXAccounts,
  testAndAddXAccount,
  deleteXAccount,
} from '@/lib/api';

type NavSection = 'ai' | 'publishing' | 'downloads' | 'processing';

// ── Secret Input ────────────────────────────────────────────
function SecretField({
  id,
  label,
  value,
  placeholder,
  onChange,
  configured,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  placeholder: string;
  onChange: (v: string) => void;
  configured?: boolean;
  hint?: string;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="field-group">
      <label className="field-label" htmlFor={id}>
        {label}
        {configured !== undefined && (
          <span
            className="settings-nav-dot"
            style={{ background: configured ? 'var(--green)' : 'var(--red)', marginLeft: 0 }}
            title={configured ? 'Configured' : 'Not configured'}
          />
        )}
      </label>
      <div className="secret-wrap">
        <input
          id={id}
          type={visible ? 'text' : 'password'}
          className="field-input"
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <button
          type="button"
          className="secret-toggle"
          onClick={() => setVisible(!visible)}
          title={visible ? 'Hide' : 'Show'}
        >
          {visible ? '○' : '●'}
        </button>
      </div>
      {hint && <div className="field-hint">{hint}</div>}
    </div>
  );
}

// ── Test Result ─────────────────────────────────────────────
function TestResult({ result }: { result: { status: string; message: string } | null }) {
  if (!result) return null;
  const cls = result.status === 'ok' ? 'ok' : result.status === 'warn' ? 'warn' : 'err';
  const icon = cls === 'ok' ? '✓' : cls === 'warn' ? '⚠' : '✗';
  return (
    <div className={`test-result ${cls}`}>
      {icon} {result.message}
    </div>
  );
}

// ── Main ────────────────────────────────────────────────────
export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [form, setForm] = useState<SettingsUpdate>({});
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [activeSection, setActiveSection] = useState<NavSection>('ai');
  const [loading, setLoading] = useState(true);

  const [kimiTest, setKimiTest] = useState<{ status: string; message: string } | null>(null);
  const [hermesTest, setHermesTest] = useState<{ status: string; message: string } | null>(null);
  const [testingKimi, setTestingKimi] = useState(false);
  const [testingHermes, setTestingHermes] = useState(false);

  const [xAccounts, setXAccounts] = useState<XAccount[]>([]);
  const [newXCookie, setNewXCookie] = useState('');
  const [testingXAccount, setTestingXAccount] = useState(false);
  const [xTestResult, setXTestResult] = useState<{ status: string; message: string } | null>(null);

  const [douyinBusy, setDouyinBusy] = useState<null | 'save' | 'test'>(null);
  const [douyinResult, setDouyinResult] = useState<{ status: string; message: string } | null>(null);

  useEffect(() => { loadSettings(); }, []);

  async function loadSettings() {
    try {
      const [s, accounts] = await Promise.all([getSettings(), getXAccounts()]);
      setSettings(s);
      setXAccounts(accounts);
      setForm({
        kimi_api_key: s.kimi_api_key,
        hermes_api_key: s.hermes_api_key,
        fal_api_key: s.fal_api_key,
        hermes_model: s.hermes_model,
        hermes_provider: s.hermes_provider,
        whisper_model: s.whisper_model,
        douyin_cookies: s.douyin_cookies,
      });
    } catch (e: any) {
      console.error('Failed to load settings:', e);
    } finally {
      setLoading(false);
    }
  }

  async function handleSave() {
    setSaving(true);
    setSaveMsg('');
    try {
      const result = await updateSettings(form);
      setSaveMsg(`✓ ${result.message}`);
      await loadSettings();
    } catch (e: any) {
      setSaveMsg(`✗ ${e.message}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleAddXAccount() {
    if (!newXCookie.trim()) return;
    setTestingXAccount(true);
    setXTestResult(null);
    try {
      const acc = await testAndAddXAccount(newXCookie.trim());
      setXAccounts([acc, ...xAccounts]);
      setNewXCookie('');
      setXTestResult({ status: 'ok', message: `Connected: ${acc.name} (@${acc.username})` });
    } catch (e: any) {
      setXTestResult({ status: 'error', message: e.message });
    } finally {
      setTestingXAccount(false);
    }
  }

  async function handleDeleteXAccount(id: number) {
    if (!confirm('Delete this X account?')) return;
    try {
      await deleteXAccount(id);
      setXAccounts(xAccounts.filter((a) => a.id !== id));
    } catch (e: any) {
      alert(`Failed: ${e.message}`);
    }
  }

  async function handleSaveDouyin() {
    const raw = (form.douyin_cookies || '').trim();
    if (!raw) { setDouyinResult({ status: 'error', message: 'Paste cookies first.' }); return; }
    setDouyinBusy('save');
    setDouyinResult(null);
    try {
      const r = await saveDouyinCookies(raw);
      setDouyinResult({ status: r.status, message: r.message });
      setForm({ ...form, douyin_cookies: '' });
      await loadSettings();
    } catch (e: any) {
      setDouyinResult({ status: 'error', message: e.message });
    } finally {
      setDouyinBusy(null);
    }
  }

  async function handleTestDouyin() {
    setDouyinBusy('test');
    setDouyinResult(null);
    try {
      const r = await testDouyinCookies(form.douyin_cookies || undefined);
      setDouyinResult(r);
    } catch (e: any) {
      setDouyinResult({ status: 'error', message: e.message });
    } finally {
      setDouyinBusy(null);
    }
  }

  async function handleTestKimi() {
    setTestingKimi(true);
    setKimiTest(null);
    try {
      setKimiTest(await testKimiConnection(form.kimi_api_key));
    } catch (e: any) {
      setKimiTest({ status: 'error', message: e.message });
    } finally {
      setTestingKimi(false);
    }
  }

  async function handleTestHermes() {
    setTestingHermes(true);
    setHermesTest(null);
    try {
      const key = form.hermes_provider === 'kimi' ? form.kimi_api_key : form.hermes_api_key;
      setHermesTest(await testHermesConnection(key, form.hermes_model, form.hermes_provider));
    } catch (e: any) {
      setHermesTest({ status: 'error', message: e.message });
    } finally {
      setTestingHermes(false);
    }
  }

  const navItems: { id: NavSection; label: string; icon: string; dot: boolean }[] = [
    { id: 'ai',          label: 'AI Models',   icon: '🧠', dot: !!(settings?.kimi_configured && settings?.hermes_ready) },
    { id: 'publishing',  label: 'Publishing',  icon: '🐦', dot: xAccounts.length > 0 },
    { id: 'downloads',   label: 'Downloads',   icon: '📱', dot: !!settings?.douyin_configured },
    { id: 'processing',  label: 'Processing',  icon: '🎙️', dot: true },
  ];

  if (loading) {
    return (
      <div className="app-shell">
        <nav className="topnav">
          <Link href="/" className="topnav-logo">◈ Content Bridge</Link>
          <span className="topnav-spacer" />
        </nav>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-3)' }}>
          Loading...
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      {/* ── Top Nav ── */}
      <nav className="topnav">
        <Link href="/" className="topnav-logo">◈ Content Bridge</Link>
        <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 4px' }} />
        <span style={{ fontSize: 13, color: 'var(--text-2)', fontWeight: 500 }}>Settings</span>
        <span className="topnav-spacer" />

        {/* Status chips */}
        <div className="topnav-status">
          <span className="status-chip">
            <span className="dot" style={{ background: settings?.kimi_configured ? 'var(--green)' : 'var(--red)' }} />
            Kimi
          </span>
          <span className="status-chip">
            <span className="dot" style={{ background: settings?.hermes_ready ? 'var(--green)' : 'var(--red)' }} />
            Hermes
          </span>
          <span className="status-chip">
            <span className="dot" style={{ background: settings?.douyin_configured ? 'var(--green)' : 'var(--red)' }} />
            Douyin
          </span>
          <span className="status-chip">
            <span className="dot" style={{ background: xAccounts.length > 0 ? 'var(--green)' : 'var(--red)' }} />
            X
          </span>
        </div>

        <Link href="/" className="topnav-btn">← Dashboard</Link>
      </nav>

      {/* ── Body ── */}
      <div className="main-content">
        <div className="settings-shell">

          {/* ── Left Nav ── */}
          <nav className="settings-nav">
            {navItems.map((item) => (
              <button
                key={item.id}
                className={`settings-nav-item${activeSection === item.id ? ' active' : ''}`}
                onClick={() => setActiveSection(item.id)}
              >
                <span>{item.icon}</span>
                <span>{item.label}</span>
                <span
                  className="settings-nav-dot"
                  style={{ background: item.dot ? 'var(--green)' : 'var(--red)' }}
                />
              </button>
            ))}

            <div style={{ flex: 1 }} />

            {/* Save button pinned at bottom of nav */}
            <div className="save-bar" style={{ flexDirection: 'column', alignItems: 'stretch', padding: '12px 0 0' }}>
              <button className="btn-save" onClick={handleSave} disabled={saving}>
                {saving && <span className="spinner" />}
                {saving ? 'Saving…' : '💾 Save All'}
              </button>
              {saveMsg && (
                <div
                  className={`save-msg ${saveMsg.startsWith('✓') ? 'ok' : 'err'}`}
                  style={{ marginTop: 6, textAlign: 'center' }}
                >
                  {saveMsg}
                </div>
              )}
            </div>
          </nav>

          {/* ── Right Content ── */}
          <div className="settings-content">

            {/* ════════ AI Models ════════ */}
            {activeSection === 'ai' && (
              <div className="fade-up">
                {/* Kimi */}
                <div className="settings-section-title">🧠 Kimi — Moonshot AI</div>
                <div className="settings-section-desc">
                  Translation, subtitle generation, and tweet writing.{' '}
                  <a href="https://platform.moonshot.cn" target="_blank" rel="noopener noreferrer" className="link">
                    Get API Key →
                  </a>
                </div>

                <SecretField
                  id="kimi-key"
                  label="API Key"
                  value={form.kimi_api_key || ''}
                  placeholder="sk-..."
                  onChange={(v) => setForm({ ...form, kimi_api_key: v })}
                  configured={settings?.kimi_configured}
                  hint="Used for: translate subtitles, summarize content, write tweet text"
                />

                <div className="save-bar" style={{ marginBottom: 24 }}>
                  <button className="btn-ghost" onClick={handleTestKimi} disabled={testingKimi}>
                    {testingKimi ? '⏳ Testing…' : '⚡ Test Connection'}
                  </button>
                </div>
                <TestResult result={kimiTest} />

                <div className="divider" />

                {/* Hermes Agent */}
                <div className="settings-section-title">🤖 Hermes Agent — Orchestrator</div>
                <div className="settings-section-desc">
                  LLM powering the agentic pipeline: tool-calling, planning, and tweet generation.
                  Kimi reuses the API key above.
                </div>

                <div className="field-group">
                  <label className="field-label" htmlFor="hermes-provider">Provider</label>
                  <select
                    id="hermes-provider"
                    className="field-select"
                    value={form.hermes_provider || 'openrouter'}
                    onChange={(e) => {
                      const p = e.target.value as 'openrouter' | 'kimi' | 'custom';
                      let model = form.hermes_model || '';
                      if (p === 'kimi') model = 'kimi-k2.6';
                      else if (p === 'openrouter') model = 'nousresearch/hermes-4-405b';
                      setForm({ ...form, hermes_provider: p, hermes_model: model });
                    }}
                  >
                    <option value="kimi">Kimi (Moonshot) — reuse key above</option>
                    <option value="openrouter">OpenRouter — Nous Hermes models</option>
                    <option value="custom">Custom — OpenAI-compatible endpoint</option>
                  </select>
                  <div className="field-hint">
                    {form.hermes_provider === 'kimi' && (
                      <>Agent will use <code style={{ fontFamily: 'var(--mono)' }}>KIMI_API_KEY</code> — {settings?.kimi_configured ? '✓ configured' : '✗ not set above'}</>
                    )}
                    {form.hermes_provider === 'openrouter' && 'Requires a separate OpenRouter API key.'}
                    {form.hermes_provider === 'custom' && 'Any OpenAI-compatible endpoint: vLLM, LiteLLM, Ollama, etc.'}
                  </div>
                </div>

                {form.hermes_provider !== 'kimi' && (
                  <SecretField
                    id="hermes-key"
                    label={form.hermes_provider === 'custom' ? 'API Key (custom endpoint)' : 'API Key (OpenRouter)'}
                    value={form.hermes_api_key || ''}
                    placeholder={form.hermes_provider === 'custom' ? 'sk-...' : 'sk-or-...'}
                    onChange={(v) => setForm({ ...form, hermes_api_key: v })}
                    configured={settings?.hermes_configured}
                  />
                )}

                <div className="field-group">
                  <label className="field-label" htmlFor="hermes-model">Model</label>
                  {form.hermes_provider === 'custom' ? (
                    <input
                      id="hermes-model"
                      type="text"
                      className="field-input"
                      placeholder="e.g. meta-llama/Llama-3.1-70B-Instruct"
                      value={form.hermes_model || ''}
                      onChange={(e) => setForm({ ...form, hermes_model: e.target.value })}
                    />
                  ) : (
                    <select
                      id="hermes-model"
                      className="field-select"
                      value={form.hermes_model || ''}
                      onChange={(e) => setForm({ ...form, hermes_model: e.target.value })}
                    >
                      {form.hermes_provider === 'kimi' ? (
                        <>
                          <option value="kimi-k2.6">kimi-k2.6 — Newest (2026-04, 262k ctx)</option>
                          <option value="kimi-k2.5">kimi-k2.5 — Stable</option>
                          <option value="kimi-k2-turbo-preview">kimi-k2-turbo — Fast</option>
                          <option value="moonshot-v1-128k">moonshot-v1-128k</option>
                        </>
                      ) : (
                        <>
                          <option value="nousresearch/hermes-4-405b">Hermes 4 — 405B (recommended)</option>
                          <option value="nousresearch/hermes-3-llama-3.1-405b">Hermes 3 — 405B</option>
                          <option value="nousresearch/hermes-3-llama-3.1-70b">Hermes 3 — 70B (fast)</option>
                          <option value="nousresearch/hermes-2-pro-llama-3-8b">Hermes 2 Pro — 8B</option>
                        </>
                      )}
                    </select>
                  )}
                </div>

                <div className="save-bar" style={{ marginBottom: 24 }}>
                  <button className="btn-ghost" onClick={handleTestHermes} disabled={testingHermes}>
                    {testingHermes ? '⏳ Testing…' : '⚡ Test Connection'}
                  </button>
                </div>
                <TestResult result={hermesTest} />

                <div className="divider" />

                {/* fal.ai */}
                <div className="settings-section-title">🎨 fal.ai FLUX</div>
                <div className="settings-section-desc">
                  AI cover video generation with FLUX.{' '}
                  <a href="https://fal.ai/dashboard/keys" target="_blank" rel="noopener noreferrer" className="link">
                    Get API Key →
                  </a>
                </div>

                <SecretField
                  id="fal-key"
                  label="API Key"
                  value={form.fal_api_key || ''}
                  placeholder="key:id:secret"
                  onChange={(v) => setForm({ ...form, fal_api_key: v })}
                  configured={settings?.fal_configured}
                  hint="Used for generating AI Cover Video scenes with FLUX"
                />
              </div>
            )}

            {/* ════════ Publishing ════════ */}
            {activeSection === 'publishing' && (
              <div className="fade-up">
                <div className="settings-section-title">🐦 X / Twitter Accounts</div>
                <div className="settings-section-desc">
                  Add accounts via{' '}
                  <a
                    href="https://chromewebstore.google.com/detail/editthiscookie/fngmhnnpilhplaeedifhccceomcggeha"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="link"
                  >
                    EditThisCookie
                  </a>{' '}
                  — export cookies from x.com as JSON then paste below.
                </div>

                <div className="field-group">
                  <label className="field-label">Add Account via Cookies JSON</label>
                  <textarea
                    className="field-textarea"
                    rows={5}
                    placeholder={'[{"name": "auth_token", "value": "..."}, {"name": "ct0", "value": "..."}]'}
                    value={newXCookie}
                    onChange={(e) => setNewXCookie(e.target.value)}
                  />
                </div>

                <div className="save-bar" style={{ marginBottom: 8 }}>
                  <button
                    className="btn-ghost"
                    onClick={handleAddXAccount}
                    disabled={testingXAccount || !newXCookie.trim()}
                  >
                    {testingXAccount ? '⏳ Connecting…' : '⚡ Test & Add Account'}
                  </button>
                </div>
                <TestResult result={xTestResult} />

                {xAccounts.length > 0 && (
                  <>
                    <div className="divider" />
                    <div className="field-label" style={{ marginBottom: 8 }}>
                      Saved Accounts ({xAccounts.length})
                    </div>
                    <div className="account-list">
                      {xAccounts.map((acc) => (
                        <div key={acc.id} className="account-item">
                          <div>
                            <div className="account-item-name">{acc.name || 'Unknown'}</div>
                            <div className="account-item-user">@{acc.username || 'unknown'}</div>
                          </div>
                          <button
                            className="btn-danger"
                            onClick={() => handleDeleteXAccount(acc.id)}
                          >
                            Remove
                          </button>
                        </div>
                      ))}
                    </div>
                  </>
                )}

                {xAccounts.length === 0 && (
                  <div style={{ fontSize: 13, color: 'var(--text-3)', padding: '12px 0' }}>
                    No X accounts added yet.
                  </div>
                )}
              </div>
            )}

            {/* ════════ Downloads ════════ */}
            {activeSection === 'downloads' && (
              <div className="fade-up">
                <div className="settings-section-title">📱 Douyin Cookies</div>
                <div className="settings-section-desc">
                  Douyin blocks downloads without authentication. Export cookies with{' '}
                  <a
                    href="https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="link"
                  >
                    Get cookies.txt LOCALLY
                  </a>{' '}
                  (Netscape) or EditThisCookie (JSON) — both formats supported.{' '}
                  <a href="https://www.douyin.com" target="_blank" rel="noopener noreferrer" className="link">
                    Login first →
                  </a>
                </div>

                {settings?.douyin_configured && (
                  <div
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 6,
                      padding: '6px 12px',
                      background: 'rgba(63,185,80,0.1)',
                      border: '1px solid rgba(63,185,80,0.2)',
                      borderRadius: 'var(--r-sm)',
                      fontSize: 12,
                      color: 'var(--green)',
                      marginBottom: 16,
                    }}
                  >
                    <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--green)', display: 'inline-block' }} />
                    Cookies configured — paste below to replace
                  </div>
                )}

                <div className="field-group">
                  <label className="field-label">Cookies (Netscape or JSON)</label>
                  <textarea
                    className="field-textarea"
                    rows={7}
                    placeholder={
                      settings?.douyin_configured
                        ? 'Paste new cookies here to replace existing ones'
                        : '# Netscape format:\n.douyin.com\tTRUE\t/\tTRUE\t0\tsessionid\t...\n\n# or JSON (EditThisCookie):\n[{"name": "sessionid", "value": "...", "domain": ".douyin.com"}]'
                    }
                    value={form.douyin_cookies || ''}
                    onChange={(e) => setForm({ ...form, douyin_cookies: e.target.value })}
                  />
                </div>

                <div className="save-bar" style={{ marginBottom: 8 }}>
                  <button
                    className="btn-save"
                    onClick={handleSaveDouyin}
                    disabled={douyinBusy !== null || !(form.douyin_cookies || '').trim()}
                  >
                    {douyinBusy === 'save' && <span className="spinner" />}
                    {douyinBusy === 'save' ? 'Saving…' : '💾 Save Cookies'}
                  </button>
                  <button
                    className="btn-ghost"
                    onClick={handleTestDouyin}
                    disabled={douyinBusy !== null}
                    title={(form.douyin_cookies || '').trim() ? 'Test cookies in textarea' : 'Test saved cookies'}
                  >
                    {douyinBusy === 'test' ? '⏳ Testing…' : '⚡ Test Login'}
                  </button>
                </div>
                <TestResult result={douyinResult} />
              </div>
            )}

            {/* ════════ Processing ════════ */}
            {activeSection === 'processing' && (
              <div className="fade-up">
                <div className="settings-section-title">🎙️ Whisper — Speech-to-Text</div>
                <div className="settings-section-desc">
                  Runs locally. Larger models are slower but more accurate. Base is recommended for most use cases.
                </div>

                <div className="field-group">
                  <label className="field-label" htmlFor="whisper-model">Model Size</label>
                  <select
                    id="whisper-model"
                    className="field-select"
                    value={form.whisper_model || 'base'}
                    onChange={(e) => setForm({ ...form, whisper_model: e.target.value })}
                  >
                    <option value="tiny">tiny — Fastest, ~1GB RAM</option>
                    <option value="base">base — Balanced, ~1GB RAM (recommended)</option>
                    <option value="small">small — Better accuracy, ~2GB RAM</option>
                    <option value="medium">medium — High accuracy, ~5GB RAM</option>
                    <option value="large-v3">large-v3 — Best, needs GPU, ~10GB RAM</option>
                  </select>
                  <div className="field-hint">
                    Currently set: <code style={{ fontFamily: 'var(--mono)' }}>{settings?.whisper_model || 'base'}</code>
                  </div>
                </div>

                <div className="divider" />

                <div className="settings-section-title" style={{ fontSize: 13, marginBottom: 8 }}>
                  ◈ About Content Bridge
                </div>
                <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.7 }}>
                  <p style={{ marginBottom: 8 }}>
                    <strong style={{ color: 'var(--text-1)' }}>Pipeline:</strong>{' '}
                    Download → Transcribe (Whisper) → Translate (Kimi) → Render (FFmpeg) → Publish (X/Twitter)
                  </p>
                  <p style={{ marginBottom: 8 }}>
                    <strong style={{ color: 'var(--text-1)' }}>Hermes Agent:</strong>{' '}
                    Orchestrates all steps via tool-calling. Supports Kimi K2.6, OpenRouter Hermes-3, or any OpenAI-compatible endpoint.
                  </p>
                  <p>
                    <strong style={{ color: 'var(--text-1)' }}>Stack:</strong>{' '}
                    FastAPI + SQLite · Next.js 15 · Whisper · yt-dlp · FFmpeg · Playwright
                  </p>
                </div>
              </div>
            )}

          </div>
        </div>
      </div>
    </div>
  );
}
