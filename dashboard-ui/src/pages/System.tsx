import { useEffect, useRef, useState } from 'preact/hooks';
import { apiFetch, apiPost, resolveApiBase, setApiBase } from '../api';
import { useWebSocket } from '../hooks/useWebSocket';

type Health = { uptime_seconds: number; memory_mb: number; agents: { name: string; summary: string }[]; ws_clients: number };
type ActivityEvent = {
  type: string;
  ts: number;
  tool?: string;
  args?: string;
  result?: string;
  status?: string;
  channel?: string;
  sender?: string;
  preview?: string;
};

type ActivityFilter = 'all' | 'tools' | 'messages';

function fmtUptime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${h}h ${m}m ${sec}s`;
}

function timeAgo(ts: number): string {
  const diff = Math.floor(Date.now() / 1000 - ts);
  if (diff < 5) return 'now';
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

const EVENT_STYLES: Record<string, { icon: string; color: string }> = {
  tool_call: { icon: '>', color: 'text-cyan' },
  tool_result: { icon: '<', color: 'text-text-dim' },
  message_in: { icon: '+', color: 'text-success' },
  message_out: { icon: '-', color: 'text-accent' },
};

export function System() {
  const [health, setHealth] = useState<Health | null>(null);
  const [git, setGit] = useState('');
  const [upgradeResult, setUpgradeResult] = useState('');
  const [upgrading, setUpgrading] = useState(false);
  const [apiUrl, setApiUrl] = useState(resolveApiBase());
  const [tmuxSessions, setTmuxSessions] = useState<{ name: string; output: string }[]>([]);
  const [expandedSession, setExpandedSession] = useState<string | null>(null);

  // Activity
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [actFilter, setActFilter] = useState<ActivityFilter>('all');
  const [actPaused, setActPaused] = useState(false);
  const actEndRef = useRef<HTMLDivElement>(null);

  function reload() {
    apiFetch<Health>('/system/health').then(setHealth).catch(() => {});
    apiFetch<{ status: string }>('/system/git').then((d) => setGit(d.status)).catch(() => {});
    apiFetch<{ name: string; output: string }[]>('/sessions').then(setTmuxSessions).catch(() => {});
    apiFetch<ActivityEvent[]>('/system/activity').then(setActivity).catch(() => {});
  }

  useEffect(reload, []);

  // Subscribe to live activity via WebSocket
  useWebSocket((msg) => {
    if (msg.type === 'activity' || msg.type === 'tool_call' || msg.type === 'tool_result' ||
        msg.type === 'message_in' || msg.type === 'message_out') {
      if (!actPaused) {
        setActivity((prev) => [...prev.slice(-199), msg as unknown as ActivityEvent]);
      }
    }
  });

  // Auto-scroll activity feed
  useEffect(() => {
    if (!actPaused) actEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activity, actPaused]);

  async function upgrade() {
    setUpgrading(true);
    setUpgradeResult('');
    try {
      const res = await apiPost<{ result: string; action: string }>('/system/upgrade', {});
      setUpgradeResult(res.result);
    } catch (e) {
      setUpgradeResult(`Error: ${e}`);
    }
    setUpgrading(false);
  }

  function saveApiUrl() {
    setApiBase(apiUrl);
    window.location.reload();
  }

  const filteredActivity = activity.filter((e) => {
    if (actFilter === 'tools') return e.type === 'tool_call' || e.type === 'tool_result';
    if (actFilter === 'messages') return e.type === 'message_in' || e.type === 'message_out';
    return true;
  });

  return (
    <div class="p-6 max-w-5xl mx-auto space-y-6">
      <h2 class="text-xl font-bold text-text">System</h2>

      {/* Live Activity */}
      <Section title="Live Activity">
        <div class="flex items-center gap-2 mb-2">
          {(['all', 'tools', 'messages'] as ActivityFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setActFilter(f)}
              class={`text-[11px] px-2 py-0.5 rounded ${
                actFilter === f ? 'bg-accent text-bg' : 'bg-bg border border-border text-text-dim hover:text-text'
              }`}
            >
              {f}
            </button>
          ))}
          <div class="flex-1" />
          <button
            onClick={() => setActPaused(!actPaused)}
            class={`text-[11px] px-2 py-0.5 rounded border ${
              actPaused ? 'border-warning text-warning' : 'border-border text-text-dim'
            }`}
          >
            {actPaused ? 'Paused' : 'Pause'}
          </button>
          <button
            onClick={() => setActivity([])}
            class="text-[11px] px-2 py-0.5 rounded border border-border text-text-dim hover:text-text"
          >
            Clear
          </button>
          <span class="text-[10px] text-text-dim">{filteredActivity.length} events</span>
        </div>
        <div class="bg-bg border border-border rounded p-2 max-h-64 overflow-y-auto font-mono text-[11px] space-y-0.5">
          {filteredActivity.length === 0 ? (
            <p class="text-text-dim py-4 text-center">No activity yet. Events will appear here in real time.</p>
          ) : (
            filteredActivity.map((e, i) => {
              const style = EVENT_STYLES[e.type] || { icon: '?', color: 'text-text-dim' };
              let detail = '';
              if (e.type === 'tool_call') detail = `${e.tool}(${e.args || ''})`;
              else if (e.type === 'tool_result') detail = `${e.tool} -> ${e.result || ''}`;
              else if (e.type === 'message_in') detail = `[${e.channel}] ${e.sender || ''}: ${e.preview || ''}`;
              else if (e.type === 'message_out') detail = `[${e.channel}] ${e.preview || ''}`;
              return (
                <div key={`${e.ts}-${i}`} class="flex gap-2 leading-tight">
                  <span class="text-text-dim w-12 shrink-0 text-right">{timeAgo(e.ts)}</span>
                  <span class={`${style.color} w-3 shrink-0`}>{style.icon}</span>
                  <span class="text-text truncate">{detail}</span>
                </div>
              );
            })
          )}
          <div ref={actEndRef} />
        </div>
      </Section>

      {/* API Connection */}
      <Section title="API Connection">
        <div class="flex gap-2">
          <input
            type="text"
            value={apiUrl}
            onInput={(e) => setApiUrl((e.target as HTMLInputElement).value)}
            class="flex-1 bg-bg border border-border rounded px-3 py-1.5 text-sm text-text font-mono focus:outline-none focus:border-accent"
          />
          <button
            onClick={saveApiUrl}
            class="px-3 py-1.5 bg-accent text-bg text-sm rounded hover:bg-accent/80 transition-colors"
          >
            Connect
          </button>
        </div>
      </Section>

      {/* Health */}
      <Section title="Health">
        {health ? (
          <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div>
              <p class="text-text-dim text-xs">Uptime</p>
              <p class="font-medium">{fmtUptime(health.uptime_seconds)}</p>
            </div>
            <div>
              <p class="text-text-dim text-xs">Memory</p>
              <p class="font-medium">{health.memory_mb} MB</p>
            </div>
            <div>
              <p class="text-text-dim text-xs">Agents</p>
              <p class="font-medium">{health.agents.length}</p>
            </div>
            <div>
              <p class="text-text-dim text-xs">WS Clients</p>
              <p class="font-medium">{health.ws_clients}</p>
            </div>
          </div>
        ) : <p class="text-text-dim text-sm">Loading...</p>}
      </Section>

      {/* Git & Upgrade */}
      <Section title="Version & Upgrade">
        {git && (
          <pre class="text-xs text-text-dim bg-bg p-3 rounded mb-3 whitespace-pre-wrap">{git}</pre>
        )}
        <div class="flex items-center gap-3">
          <button
            onClick={upgrade}
            disabled={upgrading}
            class="px-4 py-1.5 bg-warning/20 text-warning text-sm font-medium rounded hover:bg-warning/30 transition-colors disabled:opacity-40"
          >
            {upgrading ? 'Upgrading...' : 'Check & Upgrade'}
          </button>
          <button
            onClick={reload}
            class="px-4 py-1.5 bg-surface border border-border text-text-dim text-sm rounded hover:border-border-hover transition-colors"
          >
            Refresh
          </button>
        </div>
        {upgradeResult && (
          <pre class="text-xs mt-3 bg-bg p-3 rounded whitespace-pre-wrap text-text-dim">{upgradeResult}</pre>
        )}
      </Section>

      {/* Active tmux sessions */}
      <Section title={`tmux Sessions (${tmuxSessions.length})`}>
        {tmuxSessions.length === 0 ? (
          <p class="text-text-dim text-xs">No active tmux sessions.</p>
        ) : (
          <div class="space-y-2">
            {tmuxSessions.map((s) => (
              <div key={s.name} class="border border-border rounded overflow-hidden">
                <div
                  class="px-3 py-1.5 bg-bg cursor-pointer flex justify-between text-sm hover:bg-surface-hover transition-colors"
                  onClick={() => setExpandedSession(expandedSession === s.name ? null : s.name)}
                >
                  <span class="font-mono text-cyan">{s.name}</span>
                  <span class="text-text-dim text-xs">{expandedSession === s.name ? '▼' : '▶'}</span>
                </div>
                {expandedSession === s.name && (
                  <pre class="px-3 py-2 text-[11px] text-text-dim bg-bg overflow-x-auto max-h-48 overflow-y-auto">
                    {s.output || '(no output)'}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: preact.ComponentChildren }) {
  return (
    <div class="bg-surface border border-border rounded-lg p-4">
      <h3 class="text-sm font-semibold text-text mb-3">{title}</h3>
      {children}
    </div>
  );
}
