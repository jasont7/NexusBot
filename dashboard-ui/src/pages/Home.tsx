import { useEffect, useState } from 'preact/hooks';
import { apiFetch } from '../api';

type AgentStatus = { name: string; workspace: string; summary: string };
type Health = { uptime_seconds: number; memory_mb: number; agents: AgentStatus[]; ws_clients: number };
type Brain = { session_count: number; cron_job_count: number; skills: { name: string; source: string }[] };

function fmtUptime(s: number): string {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${m}m`;
}

export function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [brain, setBrain] = useState<Brain | null>(null);
  const [git, setGit] = useState('');

  useEffect(() => {
    apiFetch<Health>('/system/health').then(setHealth).catch(() => {});
    apiFetch<Brain>('/brain').then(setBrain).catch(() => {});
    apiFetch<{ status: string }>('/system/git').then((d) => setGit(d.status)).catch(() => {});
  }, []);

  return (
    <div class="p-6 max-w-5xl mx-auto space-y-6">
      <h2 class="text-xl font-bold text-text">Dashboard</h2>

      {/* Stats grid */}
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Uptime" value={health ? fmtUptime(health.uptime_seconds) : '...'} />
        <StatCard label="Memory" value={health ? `${health.memory_mb} MB` : '...'} />
        <StatCard label="Agents" value={health ? String(health.agents.length) : '...'} />
        <StatCard label="WS Clients" value={health ? String(health.ws_clients) : '...'} />
      </div>

      {/* Agents */}
      {health && health.agents.length > 0 && (
        <Section title="Registered Agents">
          {health.agents.map((a) => (
            <div key={a.name} class="flex items-center justify-between py-2 border-b border-border last:border-0">
              <div>
                <span class="font-medium text-accent">{a.name}</span>
                <span class="text-text-dim text-xs ml-2">{a.workspace}</span>
              </div>
              <span class="text-sm text-text-dim">{a.summary}</span>
            </div>
          ))}
        </Section>
      )}

      {/* Quick info */}
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Section title="Skills">
          {brain ? (
            <div class="flex flex-wrap gap-2">
              {brain.skills.map((s) => (
                <span key={s.name} class={`text-xs px-2 py-0.5 rounded ${
                  s.source === 'builtin' ? 'bg-accent/15 text-accent' : 'bg-orange/15 text-orange'
                }`}>
                  {s.name}
                </span>
              ))}
            </div>
          ) : <p class="text-text-dim text-sm">Loading...</p>}
        </Section>

        <Section title="System Info">
          <div class="text-xs text-text-dim space-y-1">
            <p>Sessions: {brain?.session_count ?? '...'}</p>
            <p>Cron Jobs: {brain?.cron_job_count ?? '...'}</p>
            {git && <pre class="mt-2 text-[11px] whitespace-pre-wrap">{git}</pre>}
          </div>
        </Section>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div class="bg-surface border border-border rounded-lg p-4">
      <p class="text-text-dim text-xs uppercase tracking-wide">{label}</p>
      <p class="text-2xl font-bold text-text mt-1">{value}</p>
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
