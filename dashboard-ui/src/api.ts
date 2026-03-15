/** Shared API client for REST + WebSocket + SSE. */

const DEFAULT_API = 'https://nanobot-api.pinpointlabs.io';
const LS_KEY = 'nanobot_api_url';

/** Resolve the API base URL. Priority: ?api= param > localStorage > localhost > default. */
export function resolveApiBase(): string {
  const params = new URLSearchParams(window.location.search);
  const fromParam = params.get('api');
  if (fromParam) {
    localStorage.setItem(LS_KEY, fromParam);
    return fromParam;
  }
  const stored = localStorage.getItem(LS_KEY);
  if (stored) return stored;
  if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') {
    return location.origin;
  }
  return DEFAULT_API;
}

export function setApiBase(url: string) {
  localStorage.setItem(LS_KEY, url);
}

export function getApiUrl(): string {
  return resolveApiBase() + '/api';
}

/** Generic JSON fetch. */
export async function apiFetch<T = unknown>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(getApiUrl() + path, {
    headers: { 'Content-Type': 'application/json', ...(opts?.headers as Record<string, string>) },
    ...opts,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`API ${res.status}: ${text.slice(0, 200)}`);
  }
  return res.json();
}

/** POST JSON. */
export function apiPost<T = unknown>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, { method: 'POST', body: JSON.stringify(body) });
}

/** PUT JSON. */
export function apiPut<T = unknown>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, { method: 'PUT', body: JSON.stringify(body) });
}

/** SSE stream for chat. Returns an abort controller. */
export function chatStream(
  message: string,
  handlers: {
    onTool?: (content: string) => void;
    onProgress?: (content: string) => void;
    onMessage?: (content: string) => void;
    onError?: (content: string) => void;
    onDone?: () => void;
  },
): AbortController {
  const ctrl = new AbortController();
  const url = getApiUrl() + '/chat';

  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
    signal: ctrl.signal,
  }).then(async (res) => {
    if (!res.ok || !res.body) {
      handlers.onError?.(`HTTP ${res.status}`);
      handlers.onDone?.();
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      let eventType = '';
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            const content = data.content || '';
            if (eventType === 'tool') handlers.onTool?.(content);
            else if (eventType === 'progress') handlers.onProgress?.(content);
            else if (eventType === 'message') handlers.onMessage?.(content);
            else if (eventType === 'error') handlers.onError?.(content);
            else if (eventType === 'done') handlers.onDone?.();
          } catch { /* skip malformed */ }
          eventType = '';
        }
      }
    }
    handlers.onDone?.();
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      handlers.onError?.(err.message);
      handlers.onDone?.();
    }
  });

  return ctrl;
}

/** Build WebSocket URL from API base. */
export function getWsUrl(): string {
  const base = resolveApiBase();
  const ws = base.replace(/^http/, 'ws');
  return ws + '/api/ws';
}
