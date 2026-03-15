import { useEffect, useState } from 'preact/hooks';
import { apiFetch, apiPost } from '../api';

type SearchResult = {
  filename: string;
  query: string;
  timestamp: string;
  sources: string[];
  result_count: number;
};

type Note = {
  name: string;
  size: number;
  modified: number;
};

type Tab = 'search' | 'notes' | 'capture';

function formatBytes(b: number): string {
  if (b < 1024) return `${b}B`;
  return `${(b / 1024).toFixed(1)}KB`;
}

export function Research() {
  const [tab, setTab] = useState<Tab>('search');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);

  // Capture form
  const [capTitle, setCapTitle] = useState('');
  const [capContent, setCapContent] = useState('');
  const [capTags, setCapTags] = useState('');
  const [capUrl, setCapUrl] = useState('');
  const [capStatus, setCapStatus] = useState('');

  useEffect(() => {
    apiFetch<SearchResult[]>('/research/results').then(setResults).catch(() => {});
    apiFetch<Note[]>('/research/notes').then(setNotes).catch(() => {});
  }, []);

  async function capture() {
    if (!capTitle || !capContent) {
      setCapStatus('Title and content required.');
      return;
    }
    setCapStatus('Saving...');
    try {
      const tags = capTags ? capTags.split(',').map((t) => t.trim()).filter(Boolean) : [];
      await apiPost('/research/capture', {
        title: capTitle, content: capContent, tags, url: capUrl,
      });
      setCapStatus('Saved to vault.');
      setCapTitle(''); setCapContent(''); setCapTags(''); setCapUrl('');
      apiFetch<Note[]>('/research/notes').then(setNotes).catch(() => {});
      setTimeout(() => setCapStatus(''), 3000);
    } catch (e) {
      setCapStatus(`Error: ${e}`);
    }
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'search', label: 'Search History' },
    { id: 'notes', label: `Knowledge Base (${notes.length})` },
    { id: 'capture', label: 'Capture' },
  ];

  return (
    <div class="p-6 max-w-5xl mx-auto space-y-4">
      <h2 class="text-xl font-bold text-text">Research</h2>

      <div class="flex gap-1 border-b border-border">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            class={`px-3 py-1.5 text-sm ${
              tab === t.id ? 'text-accent border-b-2 border-accent' : 'text-text-dim hover:text-text'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Search History */}
      {tab === 'search' && (
        <div class="space-y-2">
          {results.length === 0 ? (
            <p class="text-text-dim text-sm py-4">
              No search history. Use research(operation="search", query="...") to run searches.
            </p>
          ) : (
            results.map((r) => (
              <div key={r.filename} class="bg-surface border border-border rounded-lg px-3 py-2">
                <div class="flex items-center justify-between">
                  <span class="text-sm font-medium text-text">"{r.query}"</span>
                  <span class="text-[11px] text-text-dim">
                    {r.result_count} results &middot; {new Date(r.timestamp).toLocaleString()}
                  </span>
                </div>
                <div class="flex gap-1.5 mt-1">
                  {r.sources.map((s) => (
                    <span key={s} class="text-[10px] px-1.5 py-0.5 rounded bg-accent/15 text-accent">{s}</span>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Knowledge Base */}
      {tab === 'notes' && (
        <div class="space-y-1">
          {notes.length === 0 ? (
            <p class="text-text-dim text-sm py-4">
              No notes in vault. Use research(operation="index") or the Capture tab to save notes.
            </p>
          ) : (
            notes.map((n) => (
              <div key={n.name} class="flex items-center justify-between bg-surface border border-border rounded px-3 py-2">
                <span class="text-sm text-text font-mono">{n.name}</span>
                <div class="text-[11px] text-text-dim flex gap-3">
                  <span>{formatBytes(n.size)}</span>
                  <span>{new Date(n.modified * 1000).toLocaleDateString()}</span>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Capture */}
      {tab === 'capture' && (
        <div class="bg-surface border border-border rounded-lg p-4 space-y-3">
          <p class="text-xs text-text-dim">Save content to the Obsidian knowledge base.</p>
          <input
            type="text"
            value={capTitle}
            onInput={(e) => setCapTitle((e.target as HTMLInputElement).value)}
            placeholder="Title"
            class="w-full bg-bg border border-border rounded px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
          />
          <textarea
            value={capContent}
            onInput={(e) => setCapContent((e.target as HTMLTextAreaElement).value)}
            placeholder="Content (markdown)"
            rows={8}
            class="w-full bg-bg border border-border rounded px-3 py-1.5 text-sm text-text font-mono resize-y focus:outline-none focus:border-accent"
          />
          <div class="grid grid-cols-2 gap-3">
            <input
              type="text"
              value={capTags}
              onInput={(e) => setCapTags((e.target as HTMLInputElement).value)}
              placeholder="Tags (comma-separated)"
              class="bg-bg border border-border rounded px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
            />
            <input
              type="text"
              value={capUrl}
              onInput={(e) => setCapUrl((e.target as HTMLInputElement).value)}
              placeholder="Source URL (optional)"
              class="bg-bg border border-border rounded px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
            />
          </div>
          <div class="flex items-center gap-3">
            <button
              onClick={capture}
              class="px-4 py-1.5 bg-accent text-bg text-sm font-medium rounded hover:bg-accent/80 transition-colors"
            >
              Save to Vault
            </button>
            {capStatus && (
              <span class={`text-xs ${capStatus.startsWith('Error') ? 'text-error' : 'text-success'}`}>
                {capStatus}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
