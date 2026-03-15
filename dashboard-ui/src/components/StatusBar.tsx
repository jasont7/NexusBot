type Props = {
  connected: boolean;
  agentCount?: number;
};

export function StatusBar({ connected, agentCount }: Props) {
  return (
    <div class="fixed bottom-0 left-48 right-0 h-6 bg-surface border-t border-border flex items-center px-3 text-[11px] text-text-dim gap-4 z-50">
      <div class="flex items-center gap-1.5">
        <span class={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-success' : 'bg-error'}`} />
        {connected ? 'WS Connected' : 'WS Disconnected'}
      </div>
      {agentCount !== undefined && (
        <div>{agentCount} agent{agentCount !== 1 ? 's' : ''} registered</div>
      )}
    </div>
  );
}
