import { useEffect, useRef, useState } from 'preact/hooks';
import { getWsUrl } from '../api';

export type WsMessage = { type: string; [key: string]: unknown };
type Listener = (msg: WsMessage) => void;

const listeners = new Set<Listener>();
let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  try {
    ws = new WebSocket(getWsUrl());
    ws.onopen = () => listeners.forEach((l) => l({ type: '_connected' }));
    ws.onclose = () => {
      listeners.forEach((l) => l({ type: '_disconnected' }));
      reconnectTimer = setTimeout(connect, 5000);
    };
    ws.onerror = () => ws?.close();
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        listeners.forEach((l) => l(msg));
      } catch { /* ignore */ }
    };
  } catch {
    reconnectTimer = setTimeout(connect, 5000);
  }
}

/** Hook that subscribes to WebSocket messages. Returns connection status. */
export function useWebSocket(onMessage?: Listener): boolean {
  const [connected, setConnected] = useState(false);
  const cbRef = useRef(onMessage);
  cbRef.current = onMessage;

  useEffect(() => {
    const handler: Listener = (msg) => {
      if (msg.type === '_connected') setConnected(true);
      else if (msg.type === '_disconnected') setConnected(false);
      else cbRef.current?.(msg);
    };
    listeners.add(handler);
    connect();
    return () => {
      listeners.delete(handler);
      if (listeners.size === 0 && ws) {
        if (reconnectTimer) clearTimeout(reconnectTimer);
        ws.close();
        ws = null;
      }
    };
  }, []);

  return connected;
}
