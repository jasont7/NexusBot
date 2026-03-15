import { useEffect, useState } from 'preact/hooks';
import { apiFetch, apiPut } from '../api';
import { ForceGraph, type GraphNode, type GraphEdge } from '../components/ForceGraph';

type BrainOverview = {
  bootstrap_files: Record<string, { exists: boolean; size: number }>;
  memory_files: Record<string, { exists: boolean; size: number }>;
  skills: { name: string; source: string; path: string; size: number }[];
  session_count: number;
  cron_job_count: number;
};

type CronJob = { id: string; schedule: string; prompt: string; channel: string; chat_id: string; enabled: boolean };
type ChatSession = { filename: string; key: string; messages: number; size: number; modified: number };
type GraphData = { nodes: GraphNode[]; edges: GraphEdge[] };
type SubTab = 'map' | 'files' | 'skills' | 'sessions' | 'config';

const FILE_DESCRIPTIONS: Record<string, string> = {
  'SOUL.md': 'Core identity and personality',
  'USER.md': 'User context and preferences',
  'AGENTS.md': 'Specialized agent instructions',
  'TOOLS.md': 'Tool usage guidelines',
  'HEARTBEAT.md': 'Periodic heartbeat instructions',
  'MEMORY.md': 'Consolidated memory from conversations',
  'HISTORY.md': 'Action history log (read-only)',
};

function formatBytes(b: number): string {
  if (b < 1024) return `${b}B`;
  if (b < 1048576) return `${(b / 1024).toFixed(1)}KB`;
  return `${(b / 1048576).toFixed(1)}MB`;
}

export function Brain() {
  const [subTab, setSubTab] = useState<SubTab>('map');
  const [overview, setOverview] = useState<BrainOverview | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [cron, setCron] = useState<CronJob[]>([]);
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [graph, setGraph] = useState<GraphData | null>(null);

  // Editor state
  const [editFile, setEditFile] = useState<string | null>(null);
  const [editSkill, setEditSkill] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [saveStatus, setSaveStatus] = useState('');

  // Graph selection (for side panel)
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [selectedContent, setSelectedContent] = useState('');

  useEffect(() => {
    apiFetch<BrainOverview>('/brain').then(setOverview).catch(() => {});
    apiFetch<ChatSession[]>('/brain/sessions').then(setSessions).catch(() => {});
    apiFetch<{ jobs: CronJob[] }>('/brain/cron').then((d) => setCron(d.jobs || [])).catch(() => {});
    apiFetch<Record<string, unknown>>('/brain/config').then(setConfig).catch(() => {});
    apiFetch<GraphData>('/brain/graph').then(setGraph).catch(() => {});
  }, []);

  async function openFile(filename: string) {
    const data = await apiFetch<{ content: string }>(`/brain/files/${filename}`);
    setEditContent(data.content);
    setEditFile(filename);
    setEditSkill(null);
    setSaveStatus('');
  }

  async function openSkill(name: string) {
    const data = await apiFetch<{ content: string }>(`/brain/skills/${name}`);
    setEditContent(data.content);
    setEditSkill(name);
    setEditFile(null);
    setSaveStatus('');
  }

  async function save() {
    setSaveStatus('Saving...');
    try {
      if (editFile) {
        await apiPut(`/brain/files/${editFile}`, { content: editContent });
      } else if (editSkill) {
        await apiPut(`/brain/skills/${editSkill}`, { content: editContent });
      }
      setSaveStatus('Saved');
      setTimeout(() => setSaveStatus(''), 2000);
    } catch (e) {
      setSaveStatus(`Error: ${e}`);
    }
  }

  async function onGraphNodeClick(id: string) {
    setSelectedNode(id);
    try {
      // Check if it's a brain file (has .md) or a skill
      if (id.endsWith('.md')) {
        const data = await apiFetch<{ content: string }>(`/brain/files/${id}`);
        setSelectedContent(data.content);
      } else {
        const data = await apiFetch<{ content: string }>(`/brain/skills/${id}`);
        setSelectedContent(data.content);
      }
    } catch {
      setSelectedContent('(could not load content)');
    }
  }

  function editSelected() {
    if (!selectedNode) return;
    if (selectedNode.endsWith('.md')) {
      setEditContent(selectedContent);
      setEditFile(selectedNode);
      setEditSkill(null);
    } else {
      setEditContent(selectedContent);
      setEditSkill(selectedNode);
      setEditFile(null);
    }
    setSaveStatus('');
  }

  // Editor view
  if (editFile || editSkill) {
    const name = editFile || editSkill;
    return (
      <div class="p-6 max-w-5xl mx-auto">
        <button
          onClick={() => { setEditFile(null); setEditSkill(null); }}
          class="text-xs text-accent hover:underline mb-3"
        >
          &larr; Back to brain
        </button>
        <h2 class="text-lg font-bold text-text mb-2">{name}</h2>
        {FILE_DESCRIPTIONS[name!] && (
          <p class="text-xs text-text-dim mb-3">{FILE_DESCRIPTIONS[name!]}</p>
        )}
        <textarea
          value={editContent}
          onInput={(e) => setEditContent((e.target as HTMLTextAreaElement).value)}
          class="w-full bg-bg border border-border rounded-lg p-3 text-sm text-text font-mono resize-y focus:outline-none focus:border-accent"
          style={{ minHeight: '400px' }}
          readOnly={name === 'HISTORY.md'}
        />
        <div class="flex items-center gap-3 mt-3">
          {name !== 'HISTORY.md' && (
            <button
              onClick={save}
              class="px-4 py-1.5 bg-accent text-bg text-sm font-medium rounded hover:bg-accent/80 transition-colors"
            >
              Save
            </button>
          )}
          {saveStatus && (
            <span class={`text-xs ${saveStatus.startsWith('Error') ? 'text-error' : 'text-success'}`}>
              {saveStatus}
            </span>
          )}
        </div>
      </div>
    );
  }

  const tabs: { id: SubTab; label: string }[] = [
    { id: 'map', label: 'Brain Map' },
    { id: 'files', label: 'Files' },
    { id: 'skills', label: `Skills (${overview?.skills.length || 0})` },
    { id: 'sessions', label: `Sessions (${sessions.length})` },
    { id: 'config', label: 'Config' },
  ];

  return (
    <div class="p-6 max-w-6xl mx-auto space-y-4">
      <h2 class="text-xl font-bold text-text">Brain</h2>

      <div class="flex gap-1 border-b border-border">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setSubTab(t.id)}
            class={`px-3 py-1.5 text-sm ${
              subTab === t.id ? 'text-accent border-b-2 border-accent' : 'text-text-dim hover:text-text'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Brain Map */}
      {subTab === 'map' && (
        <div class="flex gap-4" style={{ minHeight: '440px' }}>
          <div class="flex-shrink-0">
            {graph ? (
              <ForceGraph
                nodes={graph.nodes}
                edges={graph.edges}
                onNodeClick={onGraphNodeClick}
                selectedNode={selectedNode}
                width={560}
                height={420}
              />
            ) : (
              <div class="w-[560px] h-[420px] bg-bg border border-border rounded-lg flex items-center justify-center text-text-dim text-sm">
                Loading graph...
              </div>
            )}
          </div>
          <div class="flex-1 min-w-0">
            {selectedNode ? (
              <div class="bg-surface border border-border rounded-lg p-4 h-full flex flex-col">
                <div class="flex items-center justify-between mb-2">
                  <h3 class="text-sm font-semibold text-text">{selectedNode}</h3>
                  <div class="flex gap-2">
                    <button
                      onClick={editSelected}
                      class="text-[11px] px-2 py-0.5 bg-accent text-bg rounded hover:bg-accent/80"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => { setSelectedNode(null); setSelectedContent(''); }}
                      class="text-[11px] px-2 py-0.5 bg-surface border border-border rounded text-text-dim hover:text-text"
                    >
                      Close
                    </button>
                  </div>
                </div>
                {FILE_DESCRIPTIONS[selectedNode] && (
                  <p class="text-[11px] text-text-dim mb-2">{FILE_DESCRIPTIONS[selectedNode]}</p>
                )}
                <pre class="flex-1 text-[11px] text-text-dim bg-bg p-3 rounded overflow-auto font-mono whitespace-pre-wrap">
                  {selectedContent || '(empty)'}
                </pre>
              </div>
            ) : (
              <div class="bg-surface border border-border rounded-lg p-4 h-full flex items-center justify-center">
                <p class="text-text-dim text-sm text-center">
                  Click a node to inspect.<br />
                  <span class="text-xs">Drag nodes to rearrange.</span>
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Files */}
      {subTab === 'files' && (
        <div class="space-y-4">
          <Section title="System Prompt Files">
            <div class="grid grid-cols-2 md:grid-cols-3 gap-2">
              {overview && Object.entries(overview.bootstrap_files).map(([name, info]) => (
                <FileCard key={name} name={name} size={info.size} exists={info.exists} onClick={() => openFile(name)} />
              ))}
            </div>
          </Section>
          <Section title="Memory">
            <div class="grid grid-cols-2 gap-2">
              {overview && Object.entries(overview.memory_files).map(([name, info]) => (
                <FileCard key={name} name={name} size={info.size} exists={info.exists} onClick={() => openFile(name)} />
              ))}
            </div>
          </Section>
        </div>
      )}

      {/* Skills */}
      {subTab === 'skills' && (
        <div class="grid grid-cols-2 md:grid-cols-3 gap-2">
          {overview?.skills.map((s) => (
            <div
              key={s.name}
              onClick={() => openSkill(s.name)}
              class="bg-surface border border-border rounded px-3 py-2 cursor-pointer hover:border-border-hover transition-colors"
            >
              <div class="flex items-center gap-2">
                <span class="text-sm font-medium text-text">{s.name}</span>
                <span class={`text-[10px] px-1.5 py-0.5 rounded ${
                  s.source === 'builtin' ? 'bg-accent/15 text-accent' : 'bg-orange/15 text-orange'
                }`}>
                  {s.source}
                </span>
              </div>
              <p class="text-[11px] text-text-dim mt-0.5">{formatBytes(s.size)}</p>
            </div>
          ))}
        </div>
      )}

      {/* Sessions */}
      {subTab === 'sessions' && (
        <Section title={`Chat Sessions (${sessions.length})`}>
          {sessions.length === 0 ? (
            <p class="text-text-dim text-xs">No sessions yet.</p>
          ) : (
            <div class="space-y-1 max-h-72 overflow-y-auto">
              {sessions.slice(0, 30).map((s) => (
                <div key={s.filename} class="flex justify-between text-xs py-1 border-b border-border last:border-0">
                  <span class="text-text font-mono">{s.key}</span>
                  <span class="text-text-dim">{s.messages} msgs &middot; {formatBytes(s.size)}</span>
                </div>
              ))}
            </div>
          )}
        </Section>
      )}

      {/* Config */}
      {subTab === 'config' && (
        <Section title="Configuration">
          {config ? (
            <pre class="text-[11px] text-text-dim bg-bg p-3 rounded overflow-x-auto max-h-96 overflow-y-auto">
              {JSON.stringify(config, null, 2)}
            </pre>
          ) : (
            <p class="text-text-dim text-xs">Loading...</p>
          )}
        </Section>
      )}
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

function FileCard({ name, size, exists, onClick }: { name: string; size: number; exists: boolean; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      class="bg-bg border border-border rounded px-3 py-2 cursor-pointer hover:border-border-hover transition-colors"
    >
      <span class="text-sm font-medium text-text">{name}</span>
      <p class="text-[11px] text-text-dim mt-0.5">
        {exists ? formatBytes(size) : 'not created'}
        {FILE_DESCRIPTIONS[name] && <span> &middot; {FILE_DESCRIPTIONS[name]}</span>}
      </p>
    </div>
  );
}
