import { useEffect, useState } from 'preact/hooks';
import { apiFetch, apiPost } from '../api';
import { useWebSocket } from '../hooks/useWebSocket';

type TriageItem = {
  email_id: string;
  sender: string;
  subject: string;
  importance: number;
  category: string;
  summary?: string;
};

type Draft = {
  id: string;
  email_id: string;
  to: string;
  subject: string;
  body: string;
  state: string;
  created_at: string;
};

type Action = {
  id: string;
  type: string;
  target: string;
  details: Record<string, unknown>;
  timestamp: string;
  undone: boolean;
};

type Rule = {
  id: string;
  condition: string;
  action: string;
  reason: string;
  enabled: boolean;
  times_applied: number;
};

type Tab = 'triage' | 'drafts' | 'actions' | 'rules';

const IMP_COLORS: Record<number, string> = {
  1: 'text-error font-bold',
  2: 'text-warning font-semibold',
  3: 'text-text',
  4: 'text-text-dim',
  5: 'text-text-dim opacity-60',
};

const CAT_BADGE: Record<string, string> = {
  'action-required': 'bg-error/15 text-error',
  fyi: 'bg-accent/15 text-accent',
  newsletter: 'bg-purple/15 text-purple',
  spam: 'bg-border text-text-dim',
};

export function Email() {
  const [tab, setTab] = useState<Tab>('triage');
  const [triage, setTriage] = useState<TriageItem[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [actions, setActions] = useState<Action[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [triageTime, setTriageTime] = useState('');

  function loadAll() {
    apiFetch<{ items: TriageItem[]; timestamp?: string }>('/email/triage')
      .then((d) => { setTriage(d.items || []); setTriageTime(d.timestamp || ''); })
      .catch(() => {});
    apiFetch<Draft[]>('/email/drafts').then(setDrafts).catch(() => {});
    apiFetch<Action[]>('/email/actions').then(setActions).catch(() => {});
    apiFetch<Rule[]>('/email/rules').then(setRules).catch(() => {});
  }

  useEffect(loadAll, []);

  useWebSocket((msg) => {
    if (msg.type === 'email_triage') loadAll();
  });

  async function sendDraft(id: string) {
    await apiPost(`/email/drafts/${id}/send`, {});
    loadAll();
  }

  async function discardDraft(id: string) {
    const base = localStorage.getItem('nanobot_api_url') || 'https://nanobot-api.pinpointlabs.io';
    await fetch(`${base}/api/email/drafts/${id}`, { method: 'DELETE' });
    loadAll();
  }

  async function undoAction(id: string) {
    await apiPost(`/email/actions/${id}/undo`, {});
    loadAll();
  }

  const actionReq = triage.filter((t) => t.category === 'action-required').length;
  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: 'triage', label: 'Inbox', count: actionReq },
    { id: 'drafts', label: 'Drafts', count: drafts.length },
    { id: 'actions', label: 'Actions' },
    { id: 'rules', label: 'Rules', count: rules.length },
  ];

  return (
    <div class="p-6 max-w-5xl mx-auto space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-xl font-bold text-text">Email PA</h2>
        {triageTime && (
          <span class="text-xs text-text-dim">Last triage: {new Date(triageTime).toLocaleString()}</span>
        )}
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
            {t.count != null && t.count > 0 && (
              <span class="ml-1 text-[10px] bg-warning/20 text-warning px-1 rounded">{t.count}</span>
            )}
          </button>
        ))}
      </div>

      {/* Triage / Inbox */}
      {tab === 'triage' && (
        <div class="space-y-1">
          {triage.length === 0 ? (
            <p class="text-text-dim text-sm py-4">
              No triage results yet. Emails arrive via the email channel. Use email_triage(operation="triage") to classify them.
            </p>
          ) : (
            triage
              .sort((a, b) => a.importance - b.importance)
              .map((t, i) => (
                <div key={i} class="bg-surface border border-border rounded-lg px-3 py-2 flex items-start gap-3">
                  <span class={`text-sm w-5 text-center shrink-0 ${IMP_COLORS[t.importance] || ''}`}>
                    {t.importance}
                  </span>
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-0.5">
                      <span class={`text-[10px] px-1.5 py-0.5 rounded uppercase font-semibold ${CAT_BADGE[t.category] || 'bg-border text-text-dim'}`}>
                        {t.category}
                      </span>
                      <span class="text-sm text-accent truncate">{t.sender}</span>
                    </div>
                    <p class="text-sm text-text truncate">{t.subject}</p>
                    {t.summary && <p class="text-xs text-text-dim mt-0.5">{t.summary}</p>}
                  </div>
                </div>
              ))
          )}
        </div>
      )}

      {/* Drafts */}
      {tab === 'drafts' && (
        <div class="space-y-2">
          {drafts.length === 0 ? (
            <p class="text-text-dim text-sm py-4">No draft responses. Use email_triage(operation="respond") to draft replies.</p>
          ) : (
            drafts.map((d) => (
              <div key={d.id} class="bg-surface border border-border rounded-lg p-3">
                <div class="flex items-start justify-between gap-3">
                  <div class="flex-1 min-w-0">
                    <p class="text-sm text-text">
                      <span class="text-text-dim">To:</span> {d.to}
                    </p>
                    <p class="text-sm text-text">
                      <span class="text-text-dim">Subject:</span> {d.subject}
                    </p>
                    <p class="text-xs text-text-dim mt-1 whitespace-pre-wrap">{d.body.slice(0, 300)}{d.body.length > 300 ? '...' : ''}</p>
                    <p class="text-[11px] text-text-dim mt-1">{new Date(d.created_at).toLocaleString()}</p>
                  </div>
                  <div class="flex gap-1.5 shrink-0">
                    <button onClick={() => sendDraft(d.id)} class="px-2.5 py-1 text-[11px] font-medium rounded bg-success/20 text-success hover:bg-success/30">Send</button>
                    <button onClick={() => discardDraft(d.id)} class="px-2.5 py-1 text-[11px] font-medium rounded bg-error/20 text-error hover:bg-error/30">Discard</button>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Actions */}
      {tab === 'actions' && (
        <div class="space-y-1">
          {actions.length === 0 ? (
            <p class="text-text-dim text-sm py-4">No actions logged yet.</p>
          ) : (
            actions.map((a) => (
              <div key={a.id} class={`flex items-center justify-between text-sm py-1.5 px-3 rounded ${a.undone ? 'opacity-40 line-through' : 'bg-surface border border-border'}`}>
                <div class="flex items-center gap-2 flex-1 min-w-0">
                  <span class="text-[10px] text-text-dim font-mono">{a.id}</span>
                  <span class="text-accent">{a.type}</span>
                  <span class="text-text-dim truncate">{a.target}</span>
                  <span class="text-[11px] text-text-dim">{new Date(a.timestamp).toLocaleString()}</span>
                </div>
                {!a.undone && (
                  <button onClick={() => undoAction(a.id)} class="text-[11px] text-warning hover:underline shrink-0 ml-2">Undo</button>
                )}
              </div>
            ))
          )}
        </div>
      )}

      {/* Rules */}
      {tab === 'rules' && (
        <div class="space-y-1">
          {rules.length === 0 ? (
            <p class="text-text-dim text-sm py-4">No triage rules. Rules are learned from your triage patterns via email_triage(operation="add_rule").</p>
          ) : (
            rules.map((r) => (
              <div key={r.id} class={`bg-surface border border-border rounded-lg px-3 py-2 ${!r.enabled ? 'opacity-50' : ''}`}>
                <div class="flex items-center gap-2">
                  <span class={`w-2 h-2 rounded-full ${r.enabled ? 'bg-success' : 'bg-error'}`} />
                  <span class="text-sm font-mono text-accent">{r.condition}</span>
                  <span class="text-text-dim text-sm">&rarr;</span>
                  <span class="text-sm text-text">{r.action}</span>
                  <span class="text-[11px] text-text-dim ml-auto">applied {r.times_applied}x</span>
                </div>
                {r.reason && <p class="text-xs text-text-dim mt-0.5 ml-4">{r.reason}</p>}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
