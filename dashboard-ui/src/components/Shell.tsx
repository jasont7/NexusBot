import { ComponentChildren } from 'preact';

const NAV_ITEMS = [
  { id: 'home', label: 'Home', icon: '⌂' },
  { id: 'chat', label: 'Chat', icon: '💬' },
  { id: 'agents', label: 'Agents', icon: '🤖' },
  { id: 'twitter', label: 'Twitter', icon: '𝕏' },
  { id: 'email', label: 'Email', icon: '✉' },
  { id: 'research', label: 'Research', icon: '🔍' },
  { id: 'github', label: 'GitHub', icon: '⌥' },
  { id: 'brain', label: 'Brain', icon: '🧠' },
  { id: 'architecture', label: 'Architecture', icon: '◈' },
  { id: 'system', label: 'System', icon: '⚙' },
] as const;

export type TabId = (typeof NAV_ITEMS)[number]['id'];

type Props = {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  connected: boolean;
  children: ComponentChildren;
};

export function Shell({ activeTab, onTabChange, connected, children }: Props) {
  return (
    <div class="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <nav class="w-48 shrink-0 bg-surface border-r border-border flex flex-col">
        <div class="p-4 border-b border-border">
          <h1 class="text-base font-bold text-accent tracking-wide">NexusBot OS</h1>
          <p class="text-[11px] text-text-dim mt-0.5">autonomous control</p>
        </div>
        <div class="flex-1 overflow-y-auto py-2">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              onClick={() => onTabChange(item.id)}
              class={`w-full text-left px-4 py-2 text-sm flex items-center gap-2.5 transition-colors ${
                activeTab === item.id
                  ? 'bg-surface-hover text-accent border-r-2 border-accent'
                  : 'text-text-dim hover:text-text hover:bg-surface-hover'
              }`}
            >
              <span class="text-base w-5 text-center">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </div>
        {/* Status bar */}
        <div class="p-3 border-t border-border text-[11px] text-text-dim space-y-1">
          <div class="flex items-center gap-1.5">
            <span class={`inline-block w-2 h-2 rounded-full ${connected ? 'bg-success' : 'bg-error'}`} />
            {connected ? 'Connected' : 'Disconnected'}
          </div>
        </div>
      </nav>

      {/* Main content */}
      <main class="flex-1 overflow-y-auto bg-bg">
        {children}
      </main>
    </div>
  );
}
