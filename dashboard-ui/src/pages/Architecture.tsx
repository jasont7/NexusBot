import { useEffect, useState } from 'preact/hooks';
import { apiFetch } from '../api';

type ArchData = {
  channels: string[];
  tools: string[];
  always_skills: string[];
  on_demand_skills: string[];
  bootstrap_files: string[];
  memory_files: string[];
  session_count: number;
};

const TOOL_DESCRIPTIONS: Record<string, string> = {
  read_file: 'Read file contents (max 128KB)',
  write_file: 'Write/create files',
  edit_file: 'Edit files with diffs',
  list_dir: 'List directory contents',
  exec: 'Execute shell commands',
  web_search: 'Search via Brave API',
  web_fetch: 'Fetch & parse web pages',
  message: 'Send messages to user',
  spawn: 'Spawn background subagents',
  dispatch: 'Dispatch to specialized agents',
  cron: 'Schedule recurring jobs',
  self_upgrade: 'Check for updates, pull, test, restart',
};

export function Architecture() {
  const [data, setData] = useState<ArchData | null>(null);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<ArchData>('/architecture').then(setData).catch(() => {});
  }, []);

  if (!data) return <div class="p-6 text-text-dim">Loading architecture...</div>;

  return (
    <div class="p-6 max-w-6xl mx-auto space-y-4">
      <h2 class="text-xl font-bold text-text mb-2">System Architecture</h2>

      {/* Legend */}
      <div class="flex flex-wrap gap-3 text-[11px]">
        <LegendItem color="bg-accent" label="Core / I/O" />
        <LegendItem color="bg-success" label="Processing" />
        <LegendItem color="bg-purple" label="Agents" />
        <LegendItem color="bg-warning" label="LLM / Memory" />
        <LegendItem color="bg-orange" label="Tools / Storage" />
      </div>

      <div class="bg-surface border border-border rounded-lg p-6 space-y-4 relative">
        {/* Message Sources */}
        <div>
          <label class="text-[10px] text-text-dim uppercase tracking-wide">Message Sources</label>
          <div class="flex flex-wrap gap-1.5 mt-1">
            {data.channels.map((c) => (
              <Pill key={c} color="bg-accent/15 text-accent border-accent/30" label={c}
                onHover={setHover} tooltip={`Channel: ${c}`} />
            ))}
            <Pill color="bg-success/15 text-success border-success/30" label="Heartbeat"
              onHover={setHover} tooltip="Periodic heartbeat (triggers time-aware actions)" />
            <Pill color="bg-success/15 text-success border-success/30" label="Cron"
              onHover={setHover} tooltip="Scheduled jobs (croniter-based)" />
          </div>
        </div>

        {/* Flow arrow */}
        <Arrow />

        {/* MessageBus + AgentLoop */}
        <div class="border border-success/30 rounded-lg p-4 space-y-3">
          <div class="flex items-center gap-3">
            <BoxLabel color="bg-success" label="MessageBus" />
            <span class="text-text-dim text-xs">inbound &rarr; AgentLoop &rarr; outbound</span>
          </div>

          {/* Agent Loop internals */}
          <div class="border border-warning/30 rounded p-3">
            <BoxLabel color="bg-warning" label="AgentLoop" />
            <p class="text-[11px] text-text-dim mt-1">
              ContextBuilder &rarr; LLM Provider &rarr; Tool Loop (max 40 iterations)
            </p>
          </div>

          {/* Tools Grid */}
          <div>
            <label class="text-[10px] text-text-dim uppercase tracking-wide">Tools</label>
            <div class="grid grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-1.5 mt-1">
              {data.tools.map((t) => (
                <Pill key={t} color="bg-orange/15 text-orange border-orange/30" label={t}
                  onHover={setHover} tooltip={TOOL_DESCRIPTIONS[t] || t} />
              ))}
            </div>
          </div>

          {/* Skills */}
          <div>
            <label class="text-[10px] text-text-dim uppercase tracking-wide">Skills</label>
            <div class="flex flex-wrap gap-1.5 mt-1">
              {data.always_skills.map((s) => (
                <Pill key={s} color="bg-warning/15 text-warning border-warning/30" label={`${s} (always)`}
                  onHover={setHover} tooltip={`Always-on skill: loaded into every context`} />
              ))}
              {data.on_demand_skills.map((s) => (
                <Pill key={s} color="bg-warning/10 text-text-dim border-border" label={s}
                  onHover={setHover} tooltip={`On-demand skill: loaded when relevant`} />
              ))}
            </div>
          </div>
        </div>

        <Arrow />

        {/* Specialized Agents */}
        <div class="border border-purple/30 rounded-lg p-4">
          <BoxLabel color="bg-purple" label="Specialized Agents" />
          <div class="flex flex-wrap gap-2 mt-2">
            <Pill color="bg-purple/15 text-purple border-purple/30" label="Engineer"
              onHover={setHover} tooltip="Dispatches work to Claude Code / Codex via tmux sessions" />
            <Pill color="bg-purple/10 text-text-dim border-border" label="Twitter (Phase 2)"
              onHover={setHover} tooltip="Coming: tweet drafting, feed scanning, style calibration" />
            <Pill color="bg-purple/10 text-text-dim border-border" label="Email PA (Phase 3)"
              onHover={setHover} tooltip="Coming: inbox triage, draft responses, auto-archive" />
            <Pill color="bg-purple/10 text-text-dim border-border" label="Research (Phase 4)"
              onHover={setHover} tooltip="Coming: multi-source search, Obsidian KB, bookmarks crawler" />
            <Pill color="bg-purple/10 text-text-dim border-border" label="GitHub (Phase 5)"
              onHover={setHover} tooltip="Coming: trending repos, analysis, scaffolding" />
          </div>
        </div>

        <Arrow />

        {/* Storage */}
        <div class="border border-orange/30 rounded-lg p-4">
          <BoxLabel color="bg-orange" label="Persistent Storage" />
          <div class="flex flex-wrap gap-1.5 mt-2">
            {data.bootstrap_files.map((f) => (
              <Pill key={f} color="bg-orange/10 text-text-dim border-border" label={f}
                onHover={setHover} tooltip={`Bootstrap file: ${f}`} />
            ))}
            {data.memory_files.map((f) => (
              <Pill key={f} color="bg-warning/10 text-text-dim border-border" label={f}
                onHover={setHover} tooltip={`Memory file: ${f}`} />
            ))}
            <Pill color="bg-accent/10 text-text-dim border-border"
              label={`${data.session_count} sessions`}
              onHover={setHover} tooltip="Conversation sessions stored as JSONL" />
          </div>
        </div>

        {/* Tooltip */}
        {hover && (
          <div class="fixed bottom-12 left-1/2 -translate-x-1/2 bg-bg border border-border rounded-lg px-3 py-2 text-xs text-text shadow-lg z-50 max-w-sm">
            {hover}
          </div>
        )}
      </div>
    </div>
  );
}

function LegendItem({ color, label }: { color: string; label: string }) {
  return (
    <div class="flex items-center gap-1">
      <span class={`w-2.5 h-2.5 rounded-sm ${color}`} />
      <span class="text-text-dim">{label}</span>
    </div>
  );
}

function BoxLabel({ color, label }: { color: string; label: string }) {
  return (
    <span class={`inline-block text-xs font-semibold px-2 py-0.5 rounded ${color} text-bg`}>
      {label}
    </span>
  );
}

function Pill({ color, label, onHover, tooltip }: {
  color: string; label: string; onHover: (t: string | null) => void; tooltip: string;
}) {
  return (
    <span
      class={`text-[11px] px-2 py-0.5 rounded border cursor-default transition-colors ${color}`}
      onMouseEnter={() => onHover(tooltip)}
      onMouseLeave={() => onHover(null)}
    >
      {label}
    </span>
  );
}

function Arrow() {
  return (
    <div class="flex justify-center text-text-dim text-xs">
      ↓
    </div>
  );
}
