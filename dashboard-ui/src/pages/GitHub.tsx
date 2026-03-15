import { useEffect, useState } from 'preact/hooks';
import { apiFetch, apiPost } from '../api';

type Tab = 'trending' | 'search' | 'insights' | 'scans';

type Scan = {
  filename: string;
  type: string;
  timestamp: string;
  count: number;
  items: Record<string, string>[];
};

export function GitHub() {
  const [tab, setTab] = useState<Tab>('trending');

  // Trending
  const [trendingResult, setTrendingResult] = useState('');
  const [trendingLang, setTrendingLang] = useState('');
  const [trendingSince, setTrendingSince] = useState('daily');
  const [trendingLoading, setTrendingLoading] = useState(false);

  // Search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResult, setSearchResult] = useState('');
  const [searchLoading, setSearchLoading] = useState(false);

  // Analyze
  const [analyzeRepo, setAnalyzeRepo] = useState('');
  const [analyzeResult, setAnalyzeResult] = useState('');
  const [analyzeLoading, setAnalyzeLoading] = useState(false);

  // Insights
  const [insights, setInsights] = useState('');

  // Scans
  const [scans, setScans] = useState<Scan[]>([]);
  const [expandedScan, setExpandedScan] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<{ result: string }>('/github/insights').then((d) => setInsights(d.result)).catch(() => {});
    apiFetch<{ scans: Scan[] }>('/github/scans').then((d) => setScans(d.scans)).catch(() => {});
  }, []);

  async function fetchTrending() {
    setTrendingLoading(true);
    try {
      const params = new URLSearchParams({ since: trendingSince });
      if (trendingLang) params.set('language', trendingLang);
      const d = await apiFetch<{ result: string }>(`/github/trending?${params}`);
      setTrendingResult(d.result);
      // Refresh scans list
      apiFetch<{ scans: Scan[] }>('/github/scans').then((d) => setScans(d.scans)).catch(() => {});
    } catch (e) {
      setTrendingResult(`Error: ${e}`);
    }
    setTrendingLoading(false);
  }

  async function doSearch() {
    if (!searchQuery) return;
    setSearchLoading(true);
    try {
      const d = await apiPost<{ result: string }>('/github/search', { query: searchQuery });
      setSearchResult(d.result);
    } catch (e) {
      setSearchResult(`Error: ${e}`);
    }
    setSearchLoading(false);
  }

  async function doAnalyze() {
    if (!analyzeRepo) return;
    setAnalyzeLoading(true);
    try {
      const d = await apiPost<{ result: string }>('/github/analyze', { repo: analyzeRepo });
      setAnalyzeResult(d.result);
    } catch (e) {
      setAnalyzeResult(`Error: ${e}`);
    }
    setAnalyzeLoading(false);
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'trending', label: 'Trending' },
    { id: 'search', label: 'Search & Analyze' },
    { id: 'insights', label: 'Insights' },
    { id: 'scans', label: `Scan History (${scans.length})` },
  ];

  return (
    <div class="p-6 max-w-5xl mx-auto space-y-4">
      <h2 class="text-xl font-bold text-text">GitHub / Product Hunt</h2>

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

      {/* Trending */}
      {tab === 'trending' && (
        <div class="space-y-3">
          <div class="flex gap-2 items-end">
            <div>
              <label class="text-xs text-text-dim block mb-1">Language</label>
              <input
                type="text"
                value={trendingLang}
                onInput={(e) => setTrendingLang((e.target as HTMLInputElement).value)}
                placeholder="all"
                class="bg-bg border border-border rounded px-2 py-1.5 text-sm text-text w-32 focus:outline-none focus:border-accent"
              />
            </div>
            <div>
              <label class="text-xs text-text-dim block mb-1">Period</label>
              <select
                value={trendingSince}
                onChange={(e) => setTrendingSince((e.target as HTMLSelectElement).value)}
                class="bg-bg border border-border rounded px-2 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
              >
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </select>
            </div>
            <button
              onClick={fetchTrending}
              disabled={trendingLoading}
              class="px-4 py-1.5 bg-accent text-bg text-sm font-medium rounded hover:bg-accent/80 transition-colors disabled:opacity-50"
            >
              {trendingLoading ? 'Scanning...' : 'Scan Trending'}
            </button>
          </div>
          {trendingResult && (
            <pre class="bg-surface border border-border rounded-lg p-4 text-sm text-text whitespace-pre-wrap font-mono overflow-x-auto">
              {trendingResult}
            </pre>
          )}
        </div>
      )}

      {/* Search & Analyze */}
      {tab === 'search' && (
        <div class="space-y-4">
          {/* Search */}
          <div class="bg-surface border border-border rounded-lg p-4 space-y-3">
            <h3 class="text-sm font-semibold text-text">Search Repos</h3>
            <div class="flex gap-2">
              <input
                type="text"
                value={searchQuery}
                onInput={(e) => setSearchQuery((e.target as HTMLInputElement).value)}
                onKeyDown={(e) => e.key === 'Enter' && doSearch()}
                placeholder="e.g. LLM agents framework"
                class="flex-1 bg-bg border border-border rounded px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
              />
              <button
                onClick={doSearch}
                disabled={searchLoading || !searchQuery}
                class="px-4 py-1.5 bg-accent text-bg text-sm font-medium rounded hover:bg-accent/80 transition-colors disabled:opacity-50"
              >
                {searchLoading ? 'Searching...' : 'Search'}
              </button>
            </div>
            {searchResult && (
              <pre class="bg-bg border border-border rounded p-3 text-sm text-text whitespace-pre-wrap font-mono overflow-x-auto">
                {searchResult}
              </pre>
            )}
          </div>

          {/* Analyze */}
          <div class="bg-surface border border-border rounded-lg p-4 space-y-3">
            <h3 class="text-sm font-semibold text-text">Analyze Repo</h3>
            <div class="flex gap-2">
              <input
                type="text"
                value={analyzeRepo}
                onInput={(e) => setAnalyzeRepo((e.target as HTMLInputElement).value)}
                onKeyDown={(e) => e.key === 'Enter' && doAnalyze()}
                placeholder="owner/repo"
                class="flex-1 bg-bg border border-border rounded px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
              />
              <button
                onClick={doAnalyze}
                disabled={analyzeLoading || !analyzeRepo}
                class="px-4 py-1.5 bg-accent text-bg text-sm font-medium rounded hover:bg-accent/80 transition-colors disabled:opacity-50"
              >
                {analyzeLoading ? 'Analyzing...' : 'Analyze'}
              </button>
            </div>
            {analyzeResult && (
              <pre class="bg-bg border border-border rounded p-3 text-sm text-text whitespace-pre-wrap font-mono overflow-x-auto">
                {analyzeResult}
              </pre>
            )}
          </div>
        </div>
      )}

      {/* Insights */}
      {tab === 'insights' && (
        <div class="space-y-2">
          {!insights || insights.includes('No insights') ? (
            <p class="text-text-dim text-sm py-4">
              No insights saved yet. Use github_scan(operation="save_insight", ...) to save patterns.
            </p>
          ) : (
            <pre class="bg-surface border border-border rounded-lg p-4 text-sm text-text whitespace-pre-wrap font-mono">
              {insights}
            </pre>
          )}
        </div>
      )}

      {/* Scan History */}
      {tab === 'scans' && (
        <div class="space-y-2">
          {scans.length === 0 ? (
            <p class="text-text-dim text-sm py-4">
              No scans yet. Use the Trending tab to scan GitHub.
            </p>
          ) : (
            scans.map((s) => (
              <div key={s.filename} class="bg-surface border border-border rounded-lg">
                <button
                  onClick={() => setExpandedScan(expandedScan === s.filename ? null : s.filename)}
                  class="w-full px-3 py-2 flex items-center justify-between text-left"
                >
                  <div class="flex items-center gap-2">
                    <span class="text-[10px] px-1.5 py-0.5 rounded bg-accent/15 text-accent">{s.type}</span>
                    <span class="text-sm text-text">{s.count} items</span>
                  </div>
                  <span class="text-[11px] text-text-dim">
                    {new Date(s.timestamp).toLocaleString()}
                  </span>
                </button>
                {expandedScan === s.filename && s.items && (
                  <div class="border-t border-border px-3 py-2 space-y-1">
                    {s.items.map((item, i) => (
                      <div key={i} class="text-sm text-text">
                        <span class="font-medium">{item.name || item.title || 'unnamed'}</span>
                        {item.description && (
                          <span class="text-text-dim ml-2">{item.description.slice(0, 100)}</span>
                        )}
                        {item.stars && (
                          <span class="text-accent ml-2">{item.stars} stars</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
