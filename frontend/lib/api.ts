/**
 * API Client — Autonomous Content Bridge
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 
  (typeof window !== 'undefined' 
    ? (window.location.port === '3000' ? `http://${window.location.hostname}:8000` : '') 
    : 'http://localhost:8000');

// ── BYOK (Bring Your Own Key) — localStorage helpers ────────
const STORAGE_KEY = 'hermes_user_keys';

export interface UserKeys {
  kimi_api_key?: string;
  hermes_api_key?: string;
  fal_api_key?: string;
  hermes_provider?: string;
  hermes_model?: string;
  douyin_cookies?: string;
  x_cookies_json?: string;
}

export function getClientKeys(): UserKeys {
  if (typeof window === 'undefined') return {};
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
  } catch { return {}; }
}

export function setClientKeys(keys: UserKeys) {
  if (typeof window === 'undefined') return;
  const current = getClientKeys();
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...current, ...keys }));
}

export function clearClientKeys() {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(STORAGE_KEY);
}

function _byokHeaders(): Record<string, string> {
  const keys = getClientKeys();
  const h: Record<string, string> = {};
  if (keys.kimi_api_key) h['X-Kimi-Key'] = keys.kimi_api_key;
  if (keys.hermes_api_key) h['X-Hermes-Key'] = keys.hermes_api_key;
  if (keys.fal_api_key) h['X-Fal-Key'] = keys.fal_api_key;
  if (keys.hermes_provider) h['X-Hermes-Provider'] = keys.hermes_provider;
  if (keys.hermes_model) h['X-Hermes-Model'] = keys.hermes_model;
  if (keys.douyin_cookies) h['X-Douyin-Cookies'] = keys.douyin_cookies;
  if (keys.x_cookies_json) h['X-X-Cookies'] = keys.x_cookies_json;
  return h;
}

export interface Job {
  id: number;
  url: string;
  platform: string | null;
  status: string;
  progress: number;
  title: string | null;
  duration: number | null;
  thumbnail_url: string | null;
  target_language: string;
  tweet_id: string | null;
  tweet_text: string | null;
  summary: string | null;
  transcript: string | null;
  frames_path: string | null;
  x_account_id: number | null;
  cover_path: string | null;
  ai_scenes_path: string | null;
  script_json: string | null;
  logs: string | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
}

export interface JobStats {
  total: number;
  pending: number;
  processing: number;
  completed: number;
  failed: number;
}

export async function createJob(url: string, targetLanguage = 'vi', autoPublish = true, xAccountId: number | null = null): Promise<Job> {
  const res = await fetch(`${API_BASE}/api/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ..._byokHeaders() },
    body: JSON.stringify({ url, target_language: targetLanguage, auto_publish: autoPublish, x_account_id: xAccountId }),
  });
  if (!res.ok) throw new Error(`Failed to create job: ${res.statusText}`);
  return res.json();
}

export async function generateCover(jobId: number): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}/generate-cover`, { method: 'POST' });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Failed to generate cover: ${res.statusText}`);
  }
  return res.json();
}

export async function writeScript(jobId: number): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}/custom-script`, { method: 'POST' });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Failed to write script: ${res.statusText}`);
  }
  return res.json();
}


export async function getJobs(limit = 20): Promise<Job[]> {
  const res = await fetch(`${API_BASE}/api/jobs?limit=${limit}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed to fetch jobs: ${res.statusText}`);
  return res.json();
}

export async function getJob(id: number): Promise<Job> {
  const res = await fetch(`${API_BASE}/api/jobs/${id}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed to fetch job: ${res.statusText}`);
  return res.json();
}

export async function retryJob(id: number): Promise<Job> {
  const res = await fetch(`${API_BASE}/api/jobs/${id}/retry`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed to retry job: ${res.statusText}`);
  return res.json();
}

export async function cancelJob(id: number): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/jobs/${id}/cancel`, { method: 'POST' });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Failed to cancel job: ${res.statusText}`);
  }
  return res.json();
}

export async function deleteJob(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/api/jobs/${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Failed to delete job: ${res.statusText}`);
}

export async function publishJob(id: number): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/jobs/${id}/publish`, { method: 'POST' });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Failed to publish: ${res.statusText}`);
  }
  return res.json();
}

export async function getStats(): Promise<JobStats> {
  const res = await fetch(`${API_BASE}/api/jobs/stats/summary`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed to fetch stats: ${res.statusText}`);
  return res.json();
}

export function connectWebSocket(jobId: number, onMessage: (data: any) => void): any {
  let wsUrl = API_BASE.replace('http', 'ws');
  if (typeof window !== 'undefined' && !wsUrl) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    wsUrl = `${protocol}//${window.location.host}`;
  }
  
  let ws: WebSocket | null = null;
  let reconnectTimer: any;
  let pingInterval: any;
  let isIntentionallyClosed = false;

  function connect() {
    ws = new WebSocket(`${wsUrl}/ws/jobs/${jobId}`);

    ws.onmessage = (event) => {
      if (event.data === 'pong') return;
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch {}
    };

    ws.onopen = () => {
      pingInterval = setInterval(() => {
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, 30000);
    };

    ws.onclose = () => {
      clearInterval(pingInterval);
      if (!isIntentionallyClosed) {
        reconnectTimer = setTimeout(connect, 3000);
      }
    };
  }

  connect();

  return {
    close: () => {
      isIntentionallyClosed = true;
      clearTimeout(reconnectTimer);
      clearInterval(pingInterval);
      if (ws) ws.close();
    }
  };
}

// ── Settings API ────────────────────────────────────────────

export type HermesProvider = 'openrouter' | 'kimi' | 'custom';

export interface AppSettings {
  kimi_api_key: string;
  kimi_configured: boolean;
  hermes_api_key: string;
  hermes_configured: boolean;
  fal_api_key: string;
  fal_configured: boolean;
  hermes_model: string;
  hermes_provider: HermesProvider;
  hermes_ready: boolean;
  x_configured: boolean;
  whisper_model: string;
  douyin_cookies: string;
  douyin_configured: boolean;
}

export interface SettingsUpdate {
  kimi_api_key?: string;
  hermes_api_key?: string;
  fal_api_key?: string;
  hermes_model?: string;
  hermes_provider?: HermesProvider;
  x_cookies_json?: string;
  whisper_model?: string;
  douyin_cookies?: string;
}

export async function getSettings(): Promise<AppSettings> {
  // Read from localStorage first, merge with server defaults
  const keys = getClientKeys();
  const res = await fetch(`${API_BASE}/api/settings`);
  if (!res.ok) throw new Error(`Failed to fetch settings: ${res.statusText}`);
  const server: AppSettings = await res.json();
  // Override with local keys
  return {
    ...server,
    kimi_api_key: keys.kimi_api_key || server.kimi_api_key,
    kimi_configured: !!(keys.kimi_api_key || server.kimi_configured),
    hermes_api_key: keys.hermes_api_key || server.hermes_api_key,
    hermes_configured: !!(keys.hermes_api_key || server.hermes_configured),
    fal_api_key: keys.fal_api_key || server.fal_api_key,
    fal_configured: !!(keys.fal_api_key || server.fal_configured),
    hermes_model: keys.hermes_model || server.hermes_model,
    hermes_provider: (keys.hermes_provider as any) || server.hermes_provider,
    douyin_cookies: keys.douyin_cookies || server.douyin_cookies,
    douyin_configured: !!(keys.douyin_cookies || server.douyin_configured),
  };
}

export async function updateSettings(data: SettingsUpdate): Promise<{ message: string; updated: string[] }> {
  // Save keys to localStorage (BYOK), also update server for non-secret settings
  const localKeys: UserKeys = {};
  const serverData: SettingsUpdate = {};
  
  if (data.kimi_api_key !== undefined) localKeys.kimi_api_key = data.kimi_api_key;
  if (data.hermes_api_key !== undefined) localKeys.hermes_api_key = data.hermes_api_key;
  if (data.fal_api_key !== undefined) localKeys.fal_api_key = data.fal_api_key;
  if (data.hermes_model !== undefined) localKeys.hermes_model = data.hermes_model;
  if (data.hermes_provider !== undefined) localKeys.hermes_provider = data.hermes_provider;
  if (data.douyin_cookies !== undefined) localKeys.douyin_cookies = data.douyin_cookies;
  if (data.x_cookies_json !== undefined) localKeys.x_cookies_json = data.x_cookies_json;
  
  // Non-secret settings go to server
  if (data.whisper_model) serverData.whisper_model = data.whisper_model;
  
  setClientKeys(localKeys);
  
  // Update server with non-secret settings if any
  if (Object.keys(serverData).length > 0) {
    const res = await fetch(`${API_BASE}/api/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(serverData),
    });
    if (!res.ok) throw new Error(`Failed to update settings: ${res.statusText}`);
    return res.json();
  }
  
  return { message: 'Settings saved to browser', updated: Object.keys(localKeys) };
}

export async function testKimiConnection(apiKey?: string): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE}/api/settings/test-kimi`, { 
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey }),
  });
  return res.json();
}

export async function saveDouyinCookies(cookies: string): Promise<{ status: string; message: string; count: number; has_sessionid: boolean }> {
  const res = await fetch(`${API_BASE}/api/settings/save-douyin`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cookies }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Save failed: ${res.statusText}`);
  return data;
}

export async function testDouyinCookies(cookies?: string): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE}/api/settings/test-douyin`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cookies: cookies || '' }),
  });
  return res.json();
}

export async function testHermesConnection(apiKey?: string, model?: string, provider?: HermesProvider): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE}/api/settings/test-hermes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey, model: model, provider: provider }),
  });
  return res.json();
}

export interface XAccount {
  id: number;
  name: string | null;
  username: string | null;
  created_at: string | null;
}

export async function getXAccounts(): Promise<XAccount[]> {
  const res = await fetch(`${API_BASE}/api/settings/x-accounts`);
  if (!res.ok) throw new Error(`Failed to fetch X accounts: ${res.statusText}`);
  return res.json();
}

export async function testAndAddXAccount(cookiesJson: string): Promise<XAccount> {
  const res = await fetch(`${API_BASE}/api/settings/x-accounts/test-and-add`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cookies_json: cookiesJson }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to add X account: ${res.statusText}`);
  }
  return res.json();
}

export async function deleteXAccount(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/api/settings/x-accounts/${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Failed to delete X account: ${res.statusText}`);
}

// ── Job Editing & Cover Regeneration ────────────────────────

export async function updateJob(id: number, data: { tweet_text?: string; script_json?: string }): Promise<Job> {
  const res = await fetch(`${API_BASE}/api/jobs/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to update job: ${res.statusText}`);
  }
  return res.json();
}

export async function regenerateCover(jobId: number): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}/regenerate-cover`, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to regenerate cover: ${res.statusText}`);
  }
  return res.json();
}

export async function rewriteScript(jobId: number): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}/rewrite-script`, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to rewrite script: ${res.statusText}`);
  }
  return res.json();
}

