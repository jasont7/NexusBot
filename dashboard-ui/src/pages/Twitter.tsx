import { useEffect, useState } from 'preact/hooks';
import { apiFetch, apiPost, apiPut } from '../api';
import { useWebSocket } from '../hooks/useWebSocket';

type Draft = {
  id: string;
  text: string;
  reply_to: string | null;
  source: string;
  state: string;
  created_at: string;
  posted_at: string | null;
  tweet_id: string | null;
  metadata: Record<string, unknown>;
};

type FeedItem = {
  id: string;
  text: string;
  author: string;
  author_name: string;
  created_at: string | null;
  metrics: { like_count?: number; retweet_count?: number; reply_count?: number };
};

type Metrics = {
  tweets_posted: number;
  total_impressions: number;
  total_likes: number;
  total_retweets: number;
  history: { tweet_id: string; text: string; posted_at: string }[];
};

type Tab = 'queue' | 'feed' | 'stories' | 'performance' | 'style';

const BADGE: Record<string, string> = {
  pending: 'bg-warning/15 text-warning',
  approved: 'bg-success/15 text-success',
  posted: 'bg-accent/15 text-accent',
  rejected: 'bg-error/15 text-error',
};

export function Twitter() {
  const [tab, setTab] = useState<Tab>('queue');
  const [queue, setQueue] = useState<Draft[]>([]);
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [stories, setStories] = useState<unknown[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [style, setStyle] = useState('');
  const [editingStyle, setEditingStyle] = useState(false);
  const [editDraft, setEditDraft] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  const [saveStatus, setSaveStatus] = useState('');

  function loadQueue() {
    apiFetch<Draft[]>('/twitter/queue').then(setQueue).catch(() => {});
  }
  function loadFeed() {
    apiFetch<{ items: FeedItem[] }>('/twitter/feed').then((d) => setFeed(d.items || [])).catch(() => {});
  }
  function loadStories() {
    apiFetch<unknown[]>('/twitter/stories').then(setStories).catch(() => {});
  }
  function loadMetrics() {
    apiFetch<Metrics>('/twitter/performance').then(setMetrics).catch(() => {});
  }
  function loadStyle() {
    apiFetch<{ content: string }>('/twitter/style').then((d) => setStyle(d.content)).catch(() => {});
  }

  useEffect(() => {
    loadQueue();
    loadFeed();
    loadMetrics();
    loadStyle();
    loadStories();
  }, []);

  useWebSocket((msg) => {
    if (msg.type === 'twitter_draft' || msg.type === 'twitter_posted') loadQueue();
  });

  async function approve(id: string) {
    await apiPost(`/twitter/queue/${id}/approve`, {});
    loadQueue();
  }

  async function reject(id: string) {
    const base = localStorage.getItem('nanobot_api_url') || 'https://nanobot-api.pinpointlabs.io';
    try {
      await fetch(`${base}/api/twitter/queue/${id}`, { method: 'DELETE' });
    } catch { /* */ }
    loadQueue();
  }

  async function post(id: string) {
    await apiPost(`/twitter/queue/${id}/post`, {});
    loadQueue();
  }

  async function saveEdit(id: string) {
    await apiPost(`/twitter/queue/${id}/edit`, { text: editText });
    setEditDraft(null);
    loadQueue();
  }

  async function saveStyle() {
    setSaveStatus('Saving...');
    try {
      await apiPut('/twitter/style', { content: style });
      setSaveStatus('Saved');
      setTimeout(() => setSaveStatus(''), 2000);
    } catch (e) {
      setSaveStatus(`Error: ${e}`);
    }
    setEditingStyle(false);
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'queue', label: 'Queue' },
    { id: 'feed', label: 'Feed' },
    { id: 'stories', label: 'Stories' },
    { id: 'performance', label: 'Performance' },
    { id: 'style', label: 'Style Guide' },
  ];

  const pendingCount = queue.filter((d) => d.state === 'pending').length;

  return (
    <div class="p-6 max-w-5xl mx-auto space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-xl font-bold text-text">Twitter / X</h2>
        <div class="text-xs text-text-dim">
          {pendingCount > 0 && <span class="text-warning">{pendingCount} pending</span>}
          {metrics && <span class="ml-3">{metrics.tweets_posted} posted</span>}
        </div>
      </div>

      {/* Sub-tabs */}
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
            {t.id === 'queue' && pendingCount > 0 && (
              <span class="ml-1 text-[10px] bg-warning/20 text-warning px-1 rounded">{pendingCount}</span>
            )}
          </button>
        ))}
      </div>

      {/* Queue */}
      {tab === 'queue' && (
        <div class="space-y-2">
          {queue.length === 0 ? (
            <p class="text-text-dim text-sm py-4">No drafts in queue. Use the twitter tool to generate tweets.</p>
          ) : (
            queue.map((d) => (
              <div key={d.id} class="bg-surface border border-border rounded-lg p-3">
                <div class="flex items-start justify-between gap-3">
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1">
                      <span class={`text-[10px] px-1.5 py-0.5 rounded uppercase font-semibold ${BADGE[d.state] || 'bg-border text-text-dim'}`}>
                        {d.state}
                      </span>
                      <span class="text-[11px] text-text-dim">{d.id}</span>
                      <span class="text-[11px] text-text-dim">{d.source}</span>
                      {d.reply_to && <span class="text-[11px] text-text-dim">reply to: {d.reply_to}</span>}
                    </div>
                    {editDraft === d.id ? (
                      <div class="space-y-2">
                        <textarea
                          value={editText}
                          onInput={(e) => setEditText((e.target as HTMLTextAreaElement).value)}
                          class="w-full bg-bg border border-border rounded px-2 py-1 text-sm text-text resize-y focus:outline-none focus:border-accent"
                          rows={3}
                        />
                        <div class="flex gap-2">
                          <span class={`text-[11px] ${editText.length > 280 ? 'text-error' : 'text-text-dim'}`}>
                            {editText.length}/280
                          </span>
                          <button onClick={() => saveEdit(d.id)} class="text-[11px] text-accent hover:underline">Save</button>
                          <button onClick={() => setEditDraft(null)} class="text-[11px] text-text-dim hover:underline">Cancel</button>
                        </div>
                      </div>
                    ) : (
                      <p class="text-sm text-text whitespace-pre-wrap">{d.text}</p>
                    )}
                    <p class="text-[11px] text-text-dim mt-1">
                      {new Date(d.created_at).toLocaleString()}
                      {d.posted_at && <span> &middot; posted {new Date(d.posted_at).toLocaleString()}</span>}
                      {d.tweet_id && (
                        <a href={`https://x.com/i/status/${d.tweet_id}`} target="_blank" class="text-accent ml-2 hover:underline">
                          View on X
                        </a>
                      )}
                    </p>
                  </div>
                  {d.state === 'pending' && editDraft !== d.id && (
                    <div class="flex gap-1.5 shrink-0">
                      <Btn color="success" onClick={() => approve(d.id)}>Approve</Btn>
                      <Btn color="accent" onClick={() => { setEditDraft(d.id); setEditText(d.text); }}>Edit</Btn>
                      <Btn color="error" onClick={() => reject(d.id)}>Reject</Btn>
                    </div>
                  )}
                  {d.state === 'approved' && (
                    <Btn color="accent" onClick={() => post(d.id)}>Post</Btn>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Feed */}
      {tab === 'feed' && (
        <div class="space-y-2">
          {feed.length === 0 ? (
            <p class="text-text-dim text-sm py-4">No feed data. Run twitter(operation="scan_feed") to populate.</p>
          ) : (
            feed.slice(0, 30).map((t) => (
              <div key={t.id} class="bg-surface border border-border rounded-lg p-3">
                <div class="flex items-center gap-2 mb-1">
                  <span class="text-sm font-medium text-accent">@{t.author}</span>
                  {t.author_name && <span class="text-xs text-text-dim">{t.author_name}</span>}
                  {t.created_at && (
                    <span class="text-[11px] text-text-dim">{new Date(t.created_at).toLocaleDateString()}</span>
                  )}
                </div>
                <p class="text-sm text-text">{t.text}</p>
                <div class="flex gap-3 mt-1 text-[11px] text-text-dim">
                  {t.metrics.like_count != null && <span>♥ {t.metrics.like_count}</span>}
                  {t.metrics.retweet_count != null && <span>🔄 {t.metrics.retweet_count}</span>}
                  {t.metrics.reply_count != null && <span>💬 {t.metrics.reply_count}</span>}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Stories */}
      {tab === 'stories' && (
        <div class="space-y-2">
          {stories.length === 0 ? (
            <p class="text-text-dim text-sm py-4">No stories yet. Use twitter(operation="build_stories") after scanning.</p>
          ) : (
            <pre class="text-xs text-text-dim bg-surface border border-border rounded-lg p-4 overflow-x-auto max-h-96 overflow-y-auto">
              {JSON.stringify(stories, null, 2)}
            </pre>
          )}
        </div>
      )}

      {/* Performance */}
      {tab === 'performance' && (
        <div class="bg-surface border border-border rounded-lg p-4">
          {metrics ? (
            <div class="space-y-4">
              <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Stat label="Tweets Posted" value={metrics.tweets_posted} />
                <Stat label="Impressions" value={metrics.total_impressions} />
                <Stat label="Likes" value={metrics.total_likes} />
                <Stat label="Retweets" value={metrics.total_retweets} />
              </div>
              {metrics.history.length > 0 && (
                <div>
                  <h4 class="text-xs font-semibold text-text mb-2">Recent Posts</h4>
                  <div class="space-y-1">
                    {metrics.history.slice(-10).reverse().map((h) => (
                      <div key={h.tweet_id} class="flex justify-between text-xs border-b border-border py-1 last:border-0">
                        <span class="text-text truncate flex-1">{h.text}</span>
                        <span class="text-text-dim ml-2 shrink-0">{new Date(h.posted_at).toLocaleDateString()}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p class="text-text-dim text-sm">Loading metrics...</p>
          )}
        </div>
      )}

      {/* Style Guide */}
      {tab === 'style' && (
        <div class="bg-surface border border-border rounded-lg p-4">
          {editingStyle ? (
            <div>
              <textarea
                value={style}
                onInput={(e) => setStyle((e.target as HTMLTextAreaElement).value)}
                class="w-full bg-bg border border-border rounded-lg p-3 text-sm text-text font-mono resize-y focus:outline-none focus:border-accent"
                style={{ minHeight: '300px' }}
              />
              <div class="flex items-center gap-3 mt-3">
                <button onClick={saveStyle} class="px-4 py-1.5 bg-accent text-bg text-sm rounded hover:bg-accent/80">Save</button>
                <button onClick={() => setEditingStyle(false)} class="text-sm text-text-dim hover:text-text">Cancel</button>
                {saveStatus && <span class="text-xs text-success">{saveStatus}</span>}
              </div>
            </div>
          ) : (
            <div>
              {style ? (
                <pre class="text-sm text-text whitespace-pre-wrap">{style}</pre>
              ) : (
                <p class="text-text-dim text-sm">No style guide yet. Use twitter(operation="build_style") to generate one from target profiles.</p>
              )}
              <button
                onClick={() => setEditingStyle(true)}
                class="mt-3 text-sm text-accent hover:underline"
              >
                Edit Style Guide
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Btn({ color, onClick, children }: { color: string; onClick: () => void; children: preact.ComponentChildren }) {
  const colorClass = color === 'success' ? 'bg-success/20 text-success hover:bg-success/30'
    : color === 'error' ? 'bg-error/20 text-error hover:bg-error/30'
    : 'bg-accent/20 text-accent hover:bg-accent/30';
  return (
    <button onClick={onClick} class={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${colorClass}`}>
      {children}
    </button>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <p class="text-text-dim text-[11px] uppercase tracking-wide">{label}</p>
      <p class="text-lg font-bold text-text">{value}</p>
    </div>
  );
}
