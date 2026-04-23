/**
 * API Client — Autonomous Content Bridge
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 
  (typeof window !== 'undefined' 
    ? (window.location.port === '3000' ? `http://${window.location.hostname}:8000` : '') 
    : 'http://localhost:8000');

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
    headers: { 'Content-Type': 'application/json' },
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

export async function deleteJob(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/api/jobs/${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Failed to delete job: ${res.statusText}`);
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
  const res = await fetch(`${API_BASE}/api/settings`);
  if (!res.ok) throw new Error(`Failed to fetch settings: ${res.statusText}`);
  return res.json();
}

export async function updateSettings(data: SettingsUpdate): Promise<{ message: string; updated: string[] }> {
  const res = await fetch(`${API_BASE}/api/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to update settings: ${res.statusText}`);
  return res.json();
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

