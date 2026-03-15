import { useEffect, useState, useCallback } from 'preact/hooks';
import { apiFetch, apiPost } from '../api';
import { useWebSocket } from '../hooks/useWebSocket';

type WorkItem = {
  id: string;
  title: string;
  instructions: string;
  scope: { files_writable: string[]; files_readable: string[] };
  agent: string;
  depends_on: string[];
  state: string;
  result_summary: string | null;
  error: string | null;
  git_diff: string | null;
  cost_usd: number | null;
  started_at: string | null;
  completed_at: string | null;
};

type Project = {
  id: string;
  title: string;
  target_dir: string;
  work_items: WorkItem[];
  state: string;
  created_at: string;
  completed_at: string | null;
  use_worktrees: boolean;
};

const STATE_ICONS: Record<string, string> = {
  planning: '📋', approved: '✅', running: '🔄', done: '✅', failed: '❌', pending: '⏳',
};

const BADGE_COLORS: Record<string, string> = {
  planning: 'bg-warning/15 text-warning',
  approved: 'bg-success/15 text-success',
  running: 'bg-accent/15 text-accent',
  done: 'bg-success/15 text-success',
  failed: 'bg-error/15 text-error',
  pending: 'bg-border text-text-dim',
};

function timeDiff(from: string, to?: string | null): string {
  const ms = (to ? new Date(to).getTime() : Date.now()) - new Date(from).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${m}m`;
}

export function Agents() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [output, setOutput] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  const loadProjects = useCallback(() => {
    apiFetch<Project[]>('/projects')
      .then((p) => {
        setProjects(p.sort((a, b) => b.created_at.localeCompare(a.created_at)));
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadProjects();
    const interval = setInterval(loadProjects, 30000);
    return () => clearInterval(interval);
  }, [loadProjects]);

  useWebSocket((msg) => {
    if (msg.type === 'project_updated') loadProjects();
  });

  async function approve(id: string) {
    await apiPost(`/projects/${id}/approve`, {});
    loadProjects();
  }

  async function cancel(id: string) {
    await apiPost(`/projects/${id}/cancel`, {});
    loadProjects();
  }

  async function viewOutput(projectId: string, itemId: string) {
    const key = `${projectId}/${itemId}`;
    if (output[key]) {
      setOutput((prev) => { const n = { ...prev }; delete n[key]; return n; });
      return;
    }
    const data = await apiFetch<{ output: string }>(`/projects/${projectId}/items/${itemId}/output`);
    setOutput((prev) => ({ ...prev, [key]: data.output }));
  }

  if (loading) return <div class="p-6 text-text-dim">Loading projects...</div>;

  return (
    <div class="p-6 max-w-5xl mx-auto space-y-4">
      <h2 class="text-xl font-bold text-text">Engineer Projects</h2>

      {projects.length === 0 && (
        <p class="text-text-dim text-sm">No projects yet. Use the dispatch tool to create one.</p>
      )}

      {projects.map((p) => {
        const done = p.work_items.filter((w) => w.state === 'done').length;
        const total = p.work_items.length;
        const cost = p.work_items.reduce((s, w) => s + (w.cost_usd || 0), 0);
        const isExpanded = expanded === p.id;

        return (
          <div key={p.id} class="bg-surface border border-border rounded-lg overflow-hidden hover:border-border-hover transition-colors">
            {/* Header */}
            <div
              class="p-4 cursor-pointer flex items-center justify-between"
              onClick={() => setExpanded(isExpanded ? null : p.id)}
            >
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-1">
                  <span class="font-semibold text-text truncate">{p.title}</span>
                  <span class={`text-[10px] px-1.5 py-0.5 rounded uppercase font-semibold ${BADGE_COLORS[p.state] || ''}`}>
                    {p.state}
                  </span>
                </div>
                <div class="text-xs text-text-dim flex gap-3">
                  <span>{p.id}</span>
                  <span>{timeDiff(p.created_at, p.completed_at)}</span>
                  {cost > 0 && <span>${cost.toFixed(2)}</span>}
                  <span>{done}/{total} done</span>
                </div>
                {/* Progress bar */}
                <div class="mt-2 h-1.5 bg-border rounded-full overflow-hidden">
                  <div
                    class={`h-full rounded-full transition-all ${
                      p.state === 'failed' ? 'bg-error' : 'bg-success'
                    }`}
                    style={{ width: `${total > 0 ? (done / total) * 100 : 0}%` }}
                  />
                </div>
              </div>
              <div class="ml-4 flex gap-2">
                {p.state === 'planning' && (
                  <button
                    onClick={(e) => { e.stopPropagation(); approve(p.id); }}
                    class="px-3 py-1 bg-success/20 text-success text-xs font-medium rounded hover:bg-success/30 transition-colors"
                  >
                    Approve & Run
                  </button>
                )}
                {p.state === 'running' && (
                  <button
                    onClick={(e) => { e.stopPropagation(); cancel(p.id); }}
                    class="px-3 py-1 bg-error/20 text-error text-xs font-medium rounded hover:bg-error/30 transition-colors"
                  >
                    Cancel
                  </button>
                )}
              </div>
            </div>

            {/* Expanded work items */}
            {isExpanded && (
              <div class="border-t border-border">
                {p.work_items.map((w) => {
                  const outKey = `${p.id}/${w.id}`;
                  return (
                    <div key={w.id} class="p-3 border-b border-border last:border-0">
                      <div class="flex items-center gap-2 mb-1">
                        <span>{STATE_ICONS[w.state] || '❓'}</span>
                        <span class="font-medium text-sm text-text">{w.id}: {w.title}</span>
                        <span class="text-[10px] text-text-dim">[{w.agent}]</span>
                        <span class={`text-[10px] px-1.5 py-0.5 rounded ${BADGE_COLORS[w.state] || ''}`}>
                          {w.state}
                        </span>
                      </div>
                      {w.depends_on.length > 0 && (
                        <p class="text-[11px] text-text-dim">depends on: {w.depends_on.join(', ')}</p>
                      )}
                      {w.scope.files_writable.length > 0 && (
                        <p class="text-[11px] text-text-dim">writes: {w.scope.files_writable.join(', ')}</p>
                      )}
                      {w.result_summary && (
                        <p class="text-xs text-success mt-1">{w.result_summary.slice(0, 300)}</p>
                      )}
                      {w.error && (
                        <p class="text-xs text-error mt-1">{w.error}</p>
                      )}
                      {w.git_diff && (
                        <pre class="text-[11px] text-text-dim mt-1 bg-bg p-2 rounded overflow-x-auto">{w.git_diff}</pre>
                      )}
                      {w.cost_usd != null && w.cost_usd > 0 && (
                        <p class="text-[11px] text-text-dim">cost: ${w.cost_usd.toFixed(2)}</p>
                      )}
                      {(w.state === 'done' || w.state === 'failed') && (
                        <button
                          onClick={() => viewOutput(p.id, w.id)}
                          class="text-[11px] text-accent hover:underline mt-1"
                        >
                          {output[outKey] ? 'Hide output' : 'View full output'}
                        </button>
                      )}
                      {output[outKey] && (
                        <pre class="text-[11px] text-text-dim mt-2 bg-bg p-3 rounded overflow-x-auto max-h-60 overflow-y-auto">
                          {output[outKey]}
                        </pre>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
