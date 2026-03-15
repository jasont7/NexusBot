# NexusBot OS: Autonomous AI Operating System

Built on top of the **nanobot** framework (Python asyncio gateway with MessageBus, AgentLoop, channels, tools, skills, Engineer agent).

**Fork:** https://github.com/jasont7/NexusBot

---

## Architecture Overview

```
PERSISTENT STORAGE              NEXUSBOT GATEWAY (asyncio)
~/.nanobot/workspace/           ┌──────────────────────────────────────────┐
┌──────────────┐                │  Message Sources (channels + cron + hb)  │
│ config.json  │                │              ↕ MessageBus ↕              │
│ memory/      │◄──────────────►│  AgentLoop (Context→LLM→Tools→Response)  │
│ sessions/    │                │  ┌─────────────────────────────────────┐  │
│ skills/      │                │  │ TOOLS                               │  │
│ twitter/     │                │  │  file, exec, web, message, spawn,   │  │
│ email_pa/    │                │  │  dispatch, cron, MCP, twitter,      │  │
│ research/    │                │  │  email_triage, github_scan,          │  │
    │  │  self_upgrade                        │  │
│ engineer/    │                │  └─────────────────────────────────────┘  │
│ cron/        │                │  SPECIALIZED AGENTS (via AgentRegistry)   │
└──────────────┘                │    Engineer → tmux sessions              │
                                │    TwitterAgent → X API + tweepy         │
OBSIDIAN VAULT                  │    EmailPAAgent → triage + drafts        │
~/Documents/JThomoVault/        │    ResearchTool → multi-source search     │
┌──────────────┐                │    GitHubScanTool → trending + analysis   │
│ *.md notes   │◄──────────────►│                                          │
│ indexed      │  MCP/tool      │  Dashboard API (aiohttp :18791)          │
└──────────────┘                └──────────┬───────────────────────────────┘
                                           │ REST + WebSocket + SSE
                                ┌──────────┴───────────────────────────────┐
                                │  DASHBOARD SPA (Preact + Vite + TW3)     │
                                │  Tabs: Home | Chat | Agents | Twitter |   │
                                │  Email | Research | GitHub | Brain |      │
                                │  Architecture | System                    │
                                └──────────────────────────────────────────┘
```

---

## Build Status

| Phase | Name | Status | Key Files |
|-------|------|--------|-----------|
| 0 | Foundation | **DONE** | specialized.py, registry.py, self_upgrade.py, schema.py |
| 1 | Dashboard SPA | **DONE** | dashboard-ui/src/ (Preact+Vite+TW3) |
| 2 | Twitter/X Agent | **DONE** | twitter.py, tools/twitter.py |
| 3 | Email PA | **DONE** | email_pa.py, tools/email_triage.py |
| 4 | Research Agent | **DONE** | tools/research.py |
| 5 | GitHub Agent | **DONE** | tools/github_scan.py |
| 6 | Playwright MCP | **DONE** | playwright_mcp/server.py |
| 7 | Brain Map + Activity Monitor | **DONE** | ForceGraph.tsx, Brain.tsx, System.tsx |

---

## Phase 0: Foundation (DONE)

### 0a. Self-Upgrade Tool
- **File:** `nanobot/agent/tools/self_upgrade.py` — `SelfUpgradeTool(Tool)`
- Operations: `check`, `pull`, `test`, `restart`, `status`
- Creates backup branch before merge, reverts on test failure
- `restart` uses `sys.exit(0)` — launchd auto-restarts via `com.nanobot.gateway.plist`
- Registered in `AgentLoop._register_default_tools()`
- **Skill:** `~/.nanobot/workspace/skills/self-upgrade/SKILL.md`

### 0b. Agent Registry + SpecializedAgent Base
- **File:** `nanobot/agent/specialized.py` — `SpecializedAgent(ABC)`
  - Abstract base with: state persistence (JSON), workspace dir, dashboard notification, bus access
  - Abstract methods: `execute(operation, **kwargs)`, `status_summary()`
- **File:** `nanobot/agent/registry.py` — `AgentRegistry`
  - `register()`, `get()`, `list()`, `all()`, `status()`
- **Refactored:** `nanobot/agent/engineer.py` — `Engineer(SpecializedAgent)`
  - Inherits from SpecializedAgent, keeps all existing behavior
  - `workspace_dir` = `~/.nanobot/workspace/engineer/`
  - Added `execute()` and `status_summary()` implementations
- **Modified:** `nanobot/agent/loop.py`
  - Added `self.agents = AgentRegistry()`
  - Registers Engineer (and later Twitter, EmailPA) into registry
- **Modified:** `nanobot/dashboard/server.py`
  - Accepts `agent_registry` param
  - New routes: `GET /api/agents`, `GET /api/agents/{name}/state`, `POST /api/agents/{name}/action`
  - New routes: `GET /api/system/health`, `GET /api/system/git`, `POST /api/system/upgrade`
- **Modified:** `nanobot/cli/commands.py` — passes `agent_registry` to dashboard, sets `_dashboard` on all agents

### 0c. Config Schema Extensions
- **File:** `nanobot/config/schema.py` — added:
  - `SystemConfig`: `upstream_repo`, `auto_upgrade`, `repo_dir`
  - `TwitterConfig`: `api_key`, `api_secret`, `access_token`, `access_secret`, `bearer_token`, `target_niche`, `scan_interval_min`, `style_profiles`
  - `ResearchConfig`: `exa_api_key`, `obsidian_vault_path`, `grok_api_key`, `gemini_api_key`
  - `GitHubAgentConfig`: `scan_topics`, `scan_schedule`
  - Root `Config` now has: `system`, `twitter`, `research`, `github_agent` fields
- **File:** `pyproject.toml` — added `psutil>=5.9.0`, `tweepy>=4.14.0`, optional `[browser]` extra for `playwright`

---

## Phase 1: Dashboard SPA (DONE)

### Project Setup
- **Location:** `dashboard-ui/`
- **Stack:** Vite + Preact + TypeScript + Tailwind CSS v3
- **Build:** `cd dashboard-ui && npm run build` → `dist/` (55KB JS gzipped 16KB, 15KB CSS gzipped 4KB)
- **Deploy:** `npx wrangler pages deploy dist --project-name nanobot-dashboard`
- **Config:** `vite.config.ts`, `tailwind.config.ts`, `postcss.config.js`, `tsconfig.json`, `wrangler.toml`

### Source Structure
```
dashboard-ui/src/
  main.tsx                    # Entry point
  App.tsx                     # Router + tab state
  api.ts                      # REST + SSE + WS client
  index.css                   # Tailwind base + custom styles
  components/
    Shell.tsx                 # OS shell: sidebar nav + header + status
    StatusBar.tsx             # Bottom bar (unused currently)
  hooks/
    useWebSocket.ts           # Singleton WS with auto-reconnect
  pages/
    Home.tsx                  # Stats overview (uptime, memory, agents, skills, git)
    Chat.tsx                  # SSE streaming chat (ported from index.html)
    Agents.tsx                # Engineer projects (ported: approve/cancel/expand/output)
    Twitter.tsx               # Queue, feed, stories, performance, style guide
    Email.tsx                 # Triage inbox, drafts, actions with undo, rules
    Research.tsx              # Placeholder (Phase 4)
    GitHub.tsx                # Trending, search, analyze, insights
    Brain.tsx                 # Bootstrap files, memory, skills editor, sessions, cron, config
    Architecture.tsx          # Interactive system diagram with tooltips
    System.tsx                # Health, API connection, git, upgrade, tmux sessions
```

### API Client (`api.ts`)
- `resolveApiBase()` — priority: `?api=` param > localStorage > localhost > default
- `apiFetch<T>(path)`, `apiPost<T>(path, body)`, `apiPut<T>(path, body)`
- `chatStream(message, handlers)` — SSE streaming with `onTool`, `onProgress`, `onMessage`, `onError`, `onDone`
- `getWsUrl()` — converts http→ws URL

### WebSocket Hook (`useWebSocket.ts`)
- Singleton connection shared across components
- Auto-reconnect every 5 seconds
- Returns `connected` boolean
- Accepts callback for messages (e.g., `project_updated`, `twitter_draft`, `email_triage`)

---

## Phase 2: Twitter/X Agent (DONE)

### Core Agent
- **File:** `nanobot/agent/twitter.py` — `TwitterAgent(SpecializedAgent)`
- Workspace: `~/.nanobot/workspace/twitter/`
- Queue: `queue/` dir with JSON files per draft
- Scans: `scans/` dir with timestamped scan results
- Style guide: `STYLE.md`
- Metrics: `metrics.json`
- Stories: `stories.json`
- Uses **tweepy v2 Client** with `wait_on_rate_limit=True`

### Twitter Tool
- **File:** `nanobot/agent/tools/twitter.py` — `TwitterTool(Tool)`
- 16 operations: `scan_feed`, `scan_newsletters`, `build_stories`, `generate_tweet`, `generate_reply`, `post`, `analyze_performance`, `build_style`, `queue_review`, `approve`, `reject`, `edit`, `mentions`, `bookmarks`, `get_style`, `set_style`

### Content Pipeline
1. `scan_feed` → fetch timeline (30 min cron)
2. `build_stories` → aggregate signals (2 hour cron)
3. `generate_tweet` → create draft from stories
4. `build_style` → refresh style from target profiles (weekly)
5. `analyze_performance` → track engagement (daily)

### Dashboard API Routes (9)
- `GET /api/twitter/feed` — latest scan results
- `GET /api/twitter/stories` — story summaries
- `GET /api/twitter/queue` — draft tweets
- `POST /api/twitter/queue/{id}/approve` — approve draft
- `POST /api/twitter/queue/{id}/edit` — edit draft
- `DELETE /api/twitter/queue/{id}` — reject draft
- `POST /api/twitter/queue/{id}/post` — publish to X
- `GET /api/twitter/performance` — metrics
- `GET/PUT /api/twitter/style` — style guide

### Dashboard Page (`Twitter.tsx`)
- 5 sub-tabs: Queue, Feed, Stories, Performance, Style Guide
- Queue: approve/edit/reject/post drafts, char count, tweet links
- Feed: timeline with engagement metrics
- Style: view/edit STYLE.md

### Skill
- `~/.nanobot/workspace/skills/twitter/SKILL.md`

---

## Phase 3: Email Personal Assistant (DONE)

### Core Agent
- **File:** `nanobot/agent/email_pa.py` — `EmailPAAgent(SpecializedAgent)`
- Workspace: `~/.nanobot/workspace/email_pa/`
- Action log: `actions.json` (last 500 actions, all undoable)
- Triage rules: `rules.json` (from:, subject:contains:, domain: conditions)
- Triage results: `triage.json` (classified emails)
- Snoozed items: `snoozed.json`
- Draft responses: `drafts/` dir

### Email Triage Tool
- **File:** `nanobot/agent/tools/email_triage.py` — `EmailTriageTool(Tool)`
- 15 operations: `triage`, `respond`, `send_draft`, `list_drafts`, `archive`, `snooze`, `check_snoozes`, `undo`, `actions`, `rules`, `add_rule`, `delete_rule`, `toggle_rule`, `match_rules`, `get_triage`

### Integration
- Leverages existing `EmailChannel` (IMAP/SMTP)
- `send_draft` publishes `OutboundMessage` → bus → EmailChannel.send()
- Rules auto-apply during triage
- All actions logged with timestamps for undo

### Dashboard API Routes (8)
- `GET /api/email/triage` — triage results
- `GET /api/email/drafts` — pending drafts
- `POST /api/email/drafts/{id}/send` — send draft
- `DELETE /api/email/drafts/{id}` — discard draft
- `GET /api/email/actions` — action log
- `POST /api/email/actions/{id}/undo` — undo action
- `GET /api/email/rules` — triage rules
- `GET /api/email/snoozed` — snoozed items

### Dashboard Page (`Email.tsx`)
- 4 sub-tabs: Inbox (triage), Drafts, Actions, Rules
- Inbox sorted by importance, color-coded by category
- Drafts with send/discard buttons
- Actions with per-item undo
- Rules with enable/disable status

### Skill
- `~/.nanobot/workspace/skills/email-pa/SKILL.md`

---

## Phase 4: Research Agent (DONE)

### Research Tool
- **File:** `nanobot/agent/tools/research.py` — `ResearchTool(Tool)`
- 7 operations: `search`, `deep_dive`, `query_kb`, `index`, `list_notes`, `read_note`, `crawl_bookmarks`
- Workspace: `~/.nanobot/workspace/research/` (results stored in `results/` dir)

### Multi-Source Search
- Fan out queries in parallel via `asyncio.create_task`
- Sources: **Brave** (web search), **Exa** (semantic search), **Grok** (X.AI API), **Gemini** (Google API)
- Each source configured via API keys in `ResearchConfig`
- Grok/Gemini use OpenAI-compatible `/chat/completions` endpoint
- Results saved as timestamped JSON in `research/results/`

### Obsidian Knowledge Base (`~/Documents/JThomoVault`)
- `query_kb` — full-text search across all `.md` files in vault, ranked by term frequency
- `index` — saves as `.md` with YAML frontmatter (title, date, tags, source, indexed_at) in `NexusBot/` subfolder
- `list_notes` — lists recent notes in NexusBot subfolder
- `read_note` — reads note content (up to 10KB)
- Capture API: `POST /api/research/capture` — dashboard endpoint for bookmarklet/extension

### Dashboard API Routes (3)
- `GET /api/research/results` — recent search results
- `GET /api/research/notes` — notes in knowledge base
- `POST /api/research/capture` — capture content into vault

### Dashboard Page (`Research.tsx`)
- 3 sub-tabs: Search History, Knowledge Base, Capture
- Search History: query, sources used, result counts
- Knowledge Base: list of notes with size and date
- Capture: form to manually save content (title, content, tags, URL)

### Skill
- `~/.nanobot/workspace/skills/research/SKILL.md`

### Wiring
- `AgentLoop` accepts `research_config` param, creates `ResearchTool` in `_register_default_tools()`
- CLI passes `config.research` to AgentLoop
- Uses existing `brave_api_key` and `web_proxy` from AgentLoop

---

## Phase 5: GitHub/ProductHunt Agent (DONE)

### 5a. GitHub Scan Tool
- **File:** `nanobot/agent/tools/github_scan.py` — `GitHubScanTool(Tool)`
- **Operations:** `trending` (scrape GitHub trending HTML), `analyze_repo` (GitHub API: stars, forks, languages, README), `scan_producthunt` (scrape PH trending), `search_repos` (GitHub search API), `get_insights`, `save_insight`, `create_repo` (scaffold plan)
- Workspace: `~/.nanobot/workspace/github_agent/`
- Insights persisted to `insights.json`, scans saved with timestamps

### 5b. Dashboard API Routes
- `GET /api/github/trending?language=&since=&max_results=` — scan trending repos
- `GET /api/github/insights` — get saved pattern insights
- `GET /api/github/scans` — list past scan results
- `POST /api/github/search` — search repos by query
- `POST /api/github/analyze` — deep analyze a repo

### 5c. Dashboard Page
- **File:** `dashboard-ui/src/pages/GitHub.tsx`
- 4 tabs: **Trending** (language/period filter + scan button), **Search & Analyze** (repo search + deep analysis), **Insights** (saved patterns), **Scan History** (past scans with expandable items)

### 5d. Wiring
- `AgentLoop` accepts `github_agent_config` param, creates `GitHubScanTool` in `_register_default_tools()`
- CLI passes `config.github_agent` to AgentLoop
- Skill: `~/.nanobot/workspace/skills/github-agent/SKILL.md`
- Config schema: `GitHubAgentConfig` with `scan_topics` and `scan_schedule`

---

## Phase 6: Playwright MCP Server (DONE)

### 6a. MCP Server
- **Package:** `nanobot/playwright_mcp/` — standalone stdio-based MCP server using `FastMCP`
- **Files:** `__init__.py`, `__main__.py`, `server.py`
- **11 tools:** `navigate`, `click`, `type_text`, `screenshot`, `extract_content`, `scroll`, `wait_for_selector`, `get_cookies`, `set_cookies`, `evaluate_js`, `page_info`
- Persistent browser context via `launch_persistent_context()` at `~/.nanobot/workspace/browser/user-data/`
- Configurable: `PLAYWRIGHT_USER_DATA` env var for data dir, `PLAYWRIGHT_HEADLESS=0` for visible browser

### 6b. Config
Add to `config.json` to enable:
```json
"tools": {
  "mcpServers": {
    "browser": {
      "command": "python",
      "args": ["-m", "nanobot.playwright_mcp.server"]
    }
  }
}
```
Nanobot's existing MCP client (`nanobot/agent/tools/mcp.py`) auto-connects on startup and registers all tools as `mcp_browser_*`.

### 6c. Dependency
`playwright>=1.40.0` under `[project.optional-dependencies] browser` in pyproject.toml. Post-install: `playwright install chromium`

---

## Phase 7: Brain Map + Activity Monitor (DONE)

### 7a. Activity Ring Buffer
- **File:** `nanobot/agent/loop.py` — `activity_log` (deque, maxlen=200)
- `_record_activity(event_type, **data)` called at 4 hook points: tool_call, tool_result, message_in, message_out
- `_activity_broadcast` callback set by DashboardServer to push events via WebSocket
- **Endpoint:** `GET /api/system/activity` — returns ring buffer as JSON

### 7b. Brain Knowledge Graph
- **Endpoint:** `GET /api/brain/graph` — returns `{nodes, edges}` JSON
- Nodes: all brain files (SOUL.md, USER.md, etc.), skills, NEXUSBOT.md
- Edges: cross-references detected via regex word-boundary matching
- **Component:** `dashboard-ui/src/components/ForceGraph.tsx` — custom SVG force-directed graph (~180 lines, zero dependencies)
  - Spring + repulsion physics with Euler integration
  - Drag nodes to rearrange, click to inspect
  - Color-coded: bootstrap (blue), project (purple), memory (cyan), skill (orange)

### 7c. Brain Map Page
- **File:** `dashboard-ui/src/pages/Brain.tsx` — restructured with sub-tabs: **Brain Map** | Files | Skills | Sessions | Config
- Default view: interactive graph (left) + side panel (right) showing file content on click
- Edit button opens full editor (reuses existing edit/save logic)

### 7d. System Activity Monitor
- **File:** `dashboard-ui/src/pages/System.tsx` — new "Live Activity" section at top
- Subscribes to WebSocket for real-time tool calls + message flow
- Filterable: All | Tools | Messages
- Pause/clear controls, auto-scroll, relative timestamps

---

## Wiring Summary

### AgentLoop (`nanobot/agent/loop.py`)
```python
# __init__:
self.agents = AgentRegistry()
self.engineer = Engineer(workspace, bus)           # agents.register
self.twitter_agent = TwitterAgent(workspace, bus, twitter_config)  # agents.register
self.email_pa = EmailPAAgent(workspace, bus)       # agents.register

# _register_default_tools:
DispatchTool(engineer=self.engineer)
TwitterTool(agent=self.twitter_agent)
EmailTriageTool(agent=self.email_pa)
SelfUpgradeTool()
```

### CLI Gateway (`nanobot/cli/commands.py`)
```python
agent = AgentLoop(..., twitter_config=config.twitter)
dashboard = DashboardServer(engineer=agent.engineer, agent_loop=agent,
                            agent_registry=agent.agents)
for a in agent.agents.all().values():
    a._dashboard = dashboard
```

### Dashboard Server (`nanobot/dashboard/server.py`)
- 42 total API routes
- Accepts `agent_registry` for dynamic agent endpoints
- Twitter handlers use `_get_twitter_agent()` helper
- Email handlers use `_get_email_pa()` helper

### Tests
- 141 existing tests all pass
- No new test files added (existing tests validate the unchanged interfaces)

---

## Key Design Decisions

1. **SpecializedAgent base class** — shared patterns (state, workspace, dashboard notification) extracted from Engineer
2. **AgentRegistry** — replaces hardcoded `self.engineer` with dynamic registry
3. **Tools as agent interfaces** — each specialized agent has a corresponding Tool that the LLM calls
4. **Dashboard approval gates** — Twitter drafts require approval before posting (auto-post planned after ~50 calibrated tweets)
5. **Full undo for email** — every email action is logged and reversible
6. **Preact SPA** — 55KB JS bundle (16KB gzipped), dark mode, OS-style sidebar navigation
7. **tweepy v2** — rate limit handling built-in, OAuth tokens from config.json
8. **Config-driven** — all agent configs in schema.py with Pydantic validation + defaults
