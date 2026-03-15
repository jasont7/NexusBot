"""Dashboard HTTP + WebSocket server."""

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web
from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.engineer import Engineer
    from nanobot.agent.registry import AgentRegistry

# Bootstrap files that form the system prompt (order matters)
BRAIN_FILES = ["SOUL.md", "USER.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md"]


class DashboardServer:
    """Serves the dashboard API and static frontend."""

    def __init__(self, engineer: "Engineer", agent_loop: "AgentLoop | None" = None,
                 host: str = "0.0.0.0", port: int = 18791,
                 agent_registry: "AgentRegistry | None" = None):
        self.engineer = engineer
        self.agent_loop = agent_loop
        self.agent_registry = agent_registry
        self.host = host
        self.port = port
        self._app = web.Application()
        self._ws_clients: list[web.WebSocketResponse] = []
        self._chat_lock = asyncio.Lock()  # Serialize chat requests (agent is single-threaded)
        if self.agent_loop:
            self.agent_loop._activity_broadcast = self._broadcast_activity
        self._setup_routes()

    def _setup_routes(self) -> None:
        self._app.router.add_get("/api/projects", self._handle_list_projects)
        self._app.router.add_get("/api/projects/{project_id}", self._handle_get_project)
        self._app.router.add_post("/api/projects/{project_id}/approve", self._handle_approve)
        self._app.router.add_post("/api/projects/{project_id}/cancel", self._handle_cancel)
        self._app.router.add_get("/api/projects/{project_id}/items/{item_id}/output", self._handle_get_output)
        self._app.router.add_get("/api/sessions", self._handle_list_sessions)
        self._app.router.add_get("/api/memory", self._handle_get_memory)
        self._app.router.add_get("/api/ws", self._handle_websocket)

        # Brain endpoints
        self._app.router.add_get("/api/brain", self._handle_get_brain)
        self._app.router.add_get("/api/brain/files/{filename}", self._handle_get_brain_file)
        self._app.router.add_put("/api/brain/files/{filename}", self._handle_put_brain_file)
        self._app.router.add_get("/api/brain/skills", self._handle_list_skills)
        self._app.router.add_get("/api/brain/skills/{name}", self._handle_get_skill)
        self._app.router.add_put("/api/brain/skills/{name}", self._handle_put_skill)
        self._app.router.add_get("/api/brain/config", self._handle_get_config)
        self._app.router.add_get("/api/brain/sessions", self._handle_list_chat_sessions)
        self._app.router.add_get("/api/brain/cron", self._handle_get_cron)

        # Chat endpoint
        self._app.router.add_post("/api/chat", self._handle_chat)
        self._app.router.add_get("/api/chat/history", self._handle_chat_history)

        # Agents registry
        self._app.router.add_get("/api/agents", self._handle_list_agents)
        self._app.router.add_get("/api/agents/{name}/state", self._handle_agent_state)
        self._app.router.add_post("/api/agents/{name}/action", self._handle_agent_action)

        # System endpoints
        self._app.router.add_get("/api/system/health", self._handle_system_health)
        self._app.router.add_get("/api/system/git", self._handle_system_git)
        self._app.router.add_post("/api/system/upgrade", self._handle_system_upgrade)
        self._app.router.add_get("/api/system/activity", self._handle_activity_history)

        # Brain graph
        self._app.router.add_get("/api/brain/graph", self._handle_brain_graph)

        # Research endpoints
        self._app.router.add_get("/api/research/results", self._handle_research_results)
        self._app.router.add_get("/api/research/notes", self._handle_research_notes)
        self._app.router.add_post("/api/research/capture", self._handle_research_capture)

        # Email PA endpoints
        self._app.router.add_get("/api/email/triage", self._handle_email_triage)
        self._app.router.add_get("/api/email/drafts", self._handle_email_drafts)
        self._app.router.add_post("/api/email/drafts/{draft_id}/send", self._handle_email_send_draft)
        self._app.router.add_delete("/api/email/drafts/{draft_id}", self._handle_email_discard_draft)
        self._app.router.add_get("/api/email/actions", self._handle_email_actions)
        self._app.router.add_post("/api/email/actions/{action_id}/undo", self._handle_email_undo)
        self._app.router.add_get("/api/email/rules", self._handle_email_rules)
        self._app.router.add_get("/api/email/snoozed", self._handle_email_snoozed)

        # Twitter endpoints
        self._app.router.add_get("/api/twitter/feed", self._handle_twitter_feed)
        self._app.router.add_get("/api/twitter/stories", self._handle_twitter_stories)
        self._app.router.add_get("/api/twitter/queue", self._handle_twitter_queue)
        self._app.router.add_post("/api/twitter/queue/{draft_id}/approve", self._handle_twitter_approve)
        self._app.router.add_post("/api/twitter/queue/{draft_id}/edit", self._handle_twitter_edit)
        self._app.router.add_delete("/api/twitter/queue/{draft_id}", self._handle_twitter_reject)
        self._app.router.add_post("/api/twitter/queue/{draft_id}/post", self._handle_twitter_post)
        self._app.router.add_get("/api/twitter/performance", self._handle_twitter_performance)
        self._app.router.add_get("/api/twitter/style", self._handle_twitter_style)
        self._app.router.add_put("/api/twitter/style", self._handle_twitter_put_style)

        # GitHub agent endpoints
        self._app.router.add_get("/api/github/trending", self._handle_github_trending)
        self._app.router.add_get("/api/github/insights", self._handle_github_insights)
        self._app.router.add_get("/api/github/scans", self._handle_github_scans)
        self._app.router.add_post("/api/github/search", self._handle_github_search)
        self._app.router.add_post("/api/github/analyze", self._handle_github_analyze)

        # Architecture diagram
        self._app.router.add_get("/api/architecture", self._handle_architecture)

        # Serve static frontend files
        static_dir = Path(__file__).parent / "static"
        if static_dir.exists():
            self._app.router.add_static("/", static_dir, show_index=True)
        else:
            self._app.router.add_get("/", self._handle_index_fallback)

        # CORS middleware
        self._app.middlewares.append(self._cors_middleware)

    @web.middleware
    async def _cors_middleware(self, request: web.Request, handler) -> web.StreamResponse:
        if request.method == "OPTIONS":
            resp = web.Response()
        else:
            resp = await handler(request)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    # ── API Handlers ─────────────────────────────────────────────

    async def _handle_list_projects(self, request: web.Request) -> web.Response:
        from dataclasses import asdict
        projects = self.engineer.list_projects()
        data = [asdict(p) for p in projects]
        return web.json_response(data)

    async def _handle_get_project(self, request: web.Request) -> web.Response:
        from dataclasses import asdict
        project_id = request.match_info["project_id"]
        proj = self.engineer.get_project(project_id)
        if not proj:
            return web.json_response({"error": "Project not found"}, status=404)
        return web.json_response(asdict(proj))

    async def _handle_approve(self, request: web.Request) -> web.Response:
        project_id = request.match_info["project_id"]
        result = self.engineer.approve_project(project_id)
        if result.startswith("Error"):
            return web.json_response({"error": result}, status=400)

        # Also dispatch
        dispatch_result = await self.engineer.dispatch_ready(project_id)
        await self._broadcast({"type": "project_updated", "project_id": project_id})
        return web.json_response({"result": result, "dispatch": dispatch_result})

    async def _handle_cancel(self, request: web.Request) -> web.Response:
        project_id = request.match_info["project_id"]
        result = await self.engineer.cancel_project(project_id)
        await self._broadcast({"type": "project_updated", "project_id": project_id})
        return web.json_response({"result": result})

    async def _handle_get_output(self, request: web.Request) -> web.Response:
        project_id = request.match_info["project_id"]
        item_id = request.match_info["item_id"]
        proj = self.engineer.get_project(project_id)
        if not proj:
            return web.json_response({"error": "Project not found"}, status=404)

        item = next((wi for wi in proj.work_items if wi.id == item_id), None)
        if not item:
            return web.json_response({"error": "Work item not found"}, status=404)

        output = ""
        if item.output_file and Path(item.output_file).exists():
            output = Path(item.output_file).read_text()[:50000]

        return web.json_response({
            "id": item.id,
            "title": item.title,
            "state": item.state,
            "output": output,
            "git_diff": item.git_diff,
            "result_summary": item.result_summary,
            "cost_usd": item.cost_usd,
        })

    async def _handle_list_sessions(self, request: web.Request) -> web.Response:
        """List active tmux sessions with pane output."""
        from nanobot.agent.engineer import SOCKET_PATH
        sessions = []
        try:
            proc = await asyncio.create_subprocess_shell(
                f'tmux -S "{SOCKET_PATH}" list-sessions -F "#{{session_name}}" 2>/dev/null',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if stdout:
                for name in stdout.decode().strip().split("\n"):
                    name = name.strip()
                    if not name:
                        continue
                    # Capture pane output
                    pane_proc = await asyncio.create_subprocess_shell(
                        f'tmux -S "{SOCKET_PATH}" capture-pane -p -t "{name}" -S -100',
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    pane_out, _ = await pane_proc.communicate()
                    sessions.append({
                        "name": name,
                        "output": pane_out.decode("utf-8", errors="replace")[-5000:] if pane_out else "",
                    })
        except Exception as e:
            logger.debug("Failed to list tmux sessions: {}", e)

        return web.json_response(sessions)

    async def _handle_get_memory(self, request: web.Request) -> web.Response:
        workspace = self.engineer.workspace
        memory_file = workspace / "memory" / "MEMORY.md"
        history_file = workspace / "memory" / "HISTORY.md"

        memory = memory_file.read_text() if memory_file.exists() else ""
        # Return last 50 lines of history
        history_lines = []
        if history_file.exists():
            all_lines = history_file.read_text().strip().split("\n")
            history_lines = all_lines[-50:]

        return web.json_response({
            "memory": memory,
            "history": history_lines,
        })

    # ── Brain API Handlers ─────────────────────────────────────

    async def _handle_get_brain(self, request: web.Request) -> web.Response:
        """Overview of all brain components."""
        workspace = self.engineer.workspace

        # Bootstrap files
        files = {}
        for name in BRAIN_FILES:
            p = workspace / name
            files[name] = {
                "exists": p.exists(),
                "size": p.stat().st_size if p.exists() else 0,
                "modified": p.stat().st_mtime if p.exists() else None,
            }

        # Memory files
        memory_dir = workspace / "memory"
        memory_files = {}
        for name in ["MEMORY.md", "HISTORY.md"]:
            p = memory_dir / name
            memory_files[name] = {
                "exists": p.exists(),
                "size": p.stat().st_size if p.exists() else 0,
                "modified": p.stat().st_mtime if p.exists() else None,
            }

        # Skills
        skills = self._enumerate_skills()

        # Sessions count
        sessions_dir = workspace / "sessions"
        session_count = len(list(sessions_dir.glob("*.jsonl"))) if sessions_dir.exists() else 0

        # Cron jobs
        cron_file = workspace / "cron" / "jobs.json"
        cron_count = 0
        if cron_file.exists():
            try:
                data = json.loads(cron_file.read_text())
                cron_count = len(data.get("jobs", []))
            except Exception:
                pass

        return web.json_response({
            "bootstrap_files": files,
            "memory_files": memory_files,
            "skills": skills,
            "session_count": session_count,
            "cron_job_count": cron_count,
        })

    async def _handle_get_brain_file(self, request: web.Request) -> web.Response:
        """Read a bootstrap or memory file."""
        filename = request.match_info["filename"]
        workspace = self.engineer.workspace

        # Allow bootstrap files and memory files
        allowed = {name: workspace / name for name in BRAIN_FILES}
        allowed["MEMORY.md"] = workspace / "memory" / "MEMORY.md"
        allowed["HISTORY.md"] = workspace / "memory" / "HISTORY.md"

        if filename not in allowed:
            return web.json_response({"error": f"Unknown file: {filename}"}, status=404)

        path = allowed[filename]
        content = path.read_text() if path.exists() else ""
        return web.json_response({"filename": filename, "content": content})

    async def _handle_put_brain_file(self, request: web.Request) -> web.Response:
        """Write a bootstrap or memory file."""
        filename = request.match_info["filename"]
        workspace = self.engineer.workspace

        allowed = {name: workspace / name for name in BRAIN_FILES}
        allowed["MEMORY.md"] = workspace / "memory" / "MEMORY.md"

        if filename not in allowed:
            return web.json_response({"error": f"Cannot edit: {filename}"}, status=403)

        body = await request.json()
        content = body.get("content", "")
        path = allowed[filename]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return web.json_response({"ok": True, "filename": filename, "size": len(content)})

    def _enumerate_skills(self) -> list[dict]:
        """List all skills (workspace + built-in)."""
        import importlib.resources
        skills = []
        workspace = self.engineer.workspace

        # Workspace skills (user-created, take priority)
        ws_skills_dir = workspace / "skills"
        if ws_skills_dir.exists():
            for d in sorted(ws_skills_dir.iterdir()):
                skill_file = d / "SKILL.md"
                if skill_file.exists():
                    skills.append({
                        "name": d.name,
                        "source": "workspace",
                        "path": str(skill_file),
                        "size": skill_file.stat().st_size,
                    })

        # Built-in skills
        builtin_dir = Path(__file__).parent.parent / "skills"
        if builtin_dir.exists():
            for d in sorted(builtin_dir.iterdir()):
                if d.is_dir() and (d / "SKILL.md").exists():
                    # Skip if overridden by workspace
                    if not any(s["name"] == d.name for s in skills):
                        skills.append({
                            "name": d.name,
                            "source": "builtin",
                            "path": str(d / "SKILL.md"),
                            "size": (d / "SKILL.md").stat().st_size,
                        })
        return skills

    async def _handle_list_skills(self, request: web.Request) -> web.Response:
        return web.json_response(self._enumerate_skills())

    async def _handle_get_skill(self, request: web.Request) -> web.Response:
        name = request.match_info["name"]
        for skill in self._enumerate_skills():
            if skill["name"] == name:
                content = Path(skill["path"]).read_text()
                return web.json_response({**skill, "content": content})
        return web.json_response({"error": "Skill not found"}, status=404)

    async def _handle_put_skill(self, request: web.Request) -> web.Response:
        """Write a workspace skill (creates if needed)."""
        name = request.match_info["name"]
        body = await request.json()
        content = body.get("content", "")
        workspace = self.engineer.workspace
        skill_dir = workspace / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(content)
        return web.json_response({"ok": True, "name": name, "size": len(content)})

    async def _handle_get_config(self, request: web.Request) -> web.Response:
        """Return config (redacting API keys)."""
        config_path = Path("~/.nanobot/config.json").expanduser()
        if not config_path.exists():
            return web.json_response({"error": "Config not found"}, status=404)
        try:
            config = json.loads(config_path.read_text())
            # Redact sensitive values
            self._redact_keys(config)
            return web.json_response(config)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    def _redact_keys(self, obj: dict) -> None:
        """Recursively redact values for keys containing 'key', 'token', 'secret', 'password'."""
        sensitive = {"key", "token", "secret", "password", "api_key", "apiKey",
                     "appSecret", "app_secret", "accessToken", "access_token",
                     "botToken", "bot_token", "appToken", "app_token",
                     "clawToken", "claw_token", "encryptKey", "encrypt_key",
                     "verificationToken", "verification_token", "bridgeToken", "bridge_token"}
        for k, v in obj.items():
            if isinstance(v, dict):
                self._redact_keys(v)
            elif isinstance(v, str) and v and any(s in k.lower() for s in
                    ("key", "token", "secret", "password")):
                obj[k] = v[:4] + "..." + v[-4:] if len(v) > 12 else "***"

    async def _handle_list_chat_sessions(self, request: web.Request) -> web.Response:
        """List chat session files with metadata."""
        sessions_dir = self.engineer.workspace / "sessions"
        if not sessions_dir.exists():
            return web.json_response([])
        sessions = []
        for f in sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            # Read first line for metadata
            meta = {}
            msg_count = 0
            try:
                with open(f) as fh:
                    for line in fh:
                        msg_count += 1
                        if msg_count == 1:
                            data = json.loads(line)
                            if data.get("_type") == "metadata":
                                meta = data
            except Exception:
                pass
            sessions.append({
                "filename": f.name,
                "key": meta.get("key", f.stem),
                "messages": msg_count - (1 if meta else 0),
                "size": f.stat().st_size,
                "modified": f.stat().st_mtime,
                "created_at": meta.get("created_at"),
                "updated_at": meta.get("updated_at"),
            })
        return web.json_response(sessions)

    async def _handle_get_cron(self, request: web.Request) -> web.Response:
        """Return cron jobs."""
        cron_file = self.engineer.workspace / "cron" / "jobs.json"
        if not cron_file.exists():
            return web.json_response({"version": 1, "jobs": []})
        try:
            return web.json_response(json.loads(cron_file.read_text()))
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    # ── Chat API ───────────────────────────────────────────────

    async def _handle_chat(self, request: web.Request) -> web.StreamResponse:
        """Chat with nanobot via Server-Sent Events (streaming)."""
        if not self.agent_loop:
            return web.json_response({"error": "Agent loop not available"}, status=503)

        body = await request.json()
        message = body.get("message", "").strip()
        if not message:
            return web.json_response({"error": "Empty message"}, status=400)

        # Use SSE for streaming progress + final response
        resp = web.StreamResponse()
        resp.headers["Content-Type"] = "text/event-stream"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Connection"] = "keep-alive"
        resp.headers["Access-Control-Allow-Origin"] = "*"
        await resp.prepare(request)

        async def _send_event(event: str, data: dict) -> None:
            payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
            await resp.write(payload.encode())

        # Serialize: only one chat at a time since agent loop is single-threaded
        if self._chat_lock.locked():
            await _send_event("error", {"content": "Another chat request is in progress. Please wait."})
            await _send_event("done", {})
            await resp.write_eof()
            return resp

        async with self._chat_lock:
            try:
                progress_chunks: list[str] = []

                async def on_progress(content: str, *, tool_hint: bool = False) -> None:
                    if tool_hint:
                        await _send_event("tool", {"content": content})
                    else:
                        progress_chunks.append(content)
                        await _send_event("progress", {"content": content})

                result = await self.agent_loop.process_direct(
                    message,
                    session_key="dashboard:chat",
                    channel="dashboard",
                    chat_id="chat",
                    on_progress=on_progress,
                )

                await _send_event("message", {"content": result or "(no response)"})
            except Exception as e:
                logger.error("Chat error: {}", e)
                await _send_event("error", {"content": str(e)})

        await _send_event("done", {})
        await resp.write_eof()
        return resp

    async def _handle_chat_history(self, request: web.Request) -> web.Response:
        """Return recent chat history for the dashboard session."""
        sessions_dir = self.engineer.workspace / "sessions"
        session_file = sessions_dir / "dashboard_chat.jsonl"
        if not session_file.exists():
            return web.json_response([])

        messages = []
        try:
            with open(session_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if entry.get("_type") == "metadata":
                        continue
                    role = entry.get("role")
                    if role in ("user", "assistant"):
                        content = entry.get("content", "")
                        if isinstance(content, list):
                            # Extract text from content blocks
                            text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                            content = "\n".join(text_parts)
                        if content:
                            messages.append({
                                "role": role,
                                "content": content,
                                "timestamp": entry.get("timestamp"),
                            })
        except Exception as e:
            logger.debug("Failed to read chat history: {}", e)

        # Return last 50 messages
        return web.json_response(messages[-50:])

    # ── Agents Registry Handlers ────────────────────────────────

    async def _handle_list_agents(self, request: web.Request) -> web.Response:
        """List all registered agents and their status."""
        if not self.agent_registry:
            return web.json_response([])
        return web.json_response(self.agent_registry.status())

    async def _handle_agent_state(self, request: web.Request) -> web.Response:
        """Get a specific agent's state."""
        name = request.match_info["name"]
        if not self.agent_registry:
            return web.json_response({"error": "No agent registry"}, status=503)
        agent = self.agent_registry.get(name)
        if not agent:
            return web.json_response({"error": f"Agent '{name}' not found"}, status=404)
        return web.json_response(agent.get_state())

    async def _handle_agent_action(self, request: web.Request) -> web.Response:
        """Trigger an operation on a specific agent."""
        name = request.match_info["name"]
        if not self.agent_registry:
            return web.json_response({"error": "No agent registry"}, status=503)
        agent = self.agent_registry.get(name)
        if not agent:
            return web.json_response({"error": f"Agent '{name}' not found"}, status=404)
        body = await request.json()
        operation = body.get("operation", "")
        kwargs = {k: v for k, v in body.items() if k != "operation"}
        try:
            result = await agent.execute(operation, **kwargs)
            return web.json_response({"result": result})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    # ── System Handlers ───────────────────────────────────────────

    async def _handle_system_health(self, request: web.Request) -> web.Response:
        """System health: uptime, memory, active agents."""
        import os
        import time
        import psutil
        try:
            process = psutil.Process(os.getpid())
            mem_mb = process.memory_info().rss / 1024 / 1024
            uptime_s = time.time() - process.create_time()
        except Exception:
            mem_mb = 0
            uptime_s = 0

        agents = self.agent_registry.status() if self.agent_registry else []
        return web.json_response({
            "uptime_seconds": round(uptime_s),
            "memory_mb": round(mem_mb, 1),
            "agents": agents,
            "ws_clients": len(self._ws_clients),
        })

    async def _handle_system_git(self, request: web.Request) -> web.Response:
        """Current commit and upstream delta."""
        from nanobot.agent.tools.self_upgrade import SelfUpgradeTool
        tool = SelfUpgradeTool()
        result = await tool.execute(operation="status")
        return web.json_response({"status": result})

    async def _handle_system_upgrade(self, request: web.Request) -> web.Response:
        """Trigger self-upgrade check + pull + restart."""
        from nanobot.agent.tools.self_upgrade import SelfUpgradeTool
        tool = SelfUpgradeTool()
        check = await tool.execute(operation="check")
        if "up to date" in check.lower():
            return web.json_response({"result": check, "action": "none"})
        pull = await tool.execute(operation="pull")
        if "failed" in pull.lower() or "error" in pull.lower():
            return web.json_response({"result": pull, "action": "pull_failed"})
        test = await tool.execute(operation="test")
        if "FAILED" in test:
            return web.json_response({"result": f"Pull succeeded but tests failed:\n{test}", "action": "test_failed"})
        restart = tool._restart()
        return web.json_response({"result": f"{pull}\n{test}\n{restart}", "action": "restarting"})

    # ── Activity + Brain Graph Handlers ──────────────────────────

    async def _broadcast_activity(self, entry: dict) -> None:
        """Broadcast an activity event to all WebSocket clients."""
        await self._broadcast({"type": "activity", **entry})

    async def _handle_activity_history(self, request: web.Request) -> web.Response:
        """Return the activity ring buffer."""
        if not self.agent_loop:
            return web.json_response([])
        return web.json_response(list(self.agent_loop.activity_log))

    async def _handle_brain_graph(self, request: web.Request) -> web.Response:
        """Return brain files + skills as a knowledge graph with cross-reference edges."""
        import re
        workspace = self.engineer.workspace
        nodes = []
        file_contents: dict[str, str] = {}

        # Brain files
        for fname in BRAIN_FILES + ["MEMORY.md", "HISTORY.md"]:
            fpath = workspace / fname
            if fpath.exists():
                content = fpath.read_text(errors="replace")
                nodes.append({"id": fname, "type": "brain", "size": len(content), "group": "bootstrap"})
                file_contents[fname] = content

        # NEXUSBOT.md (repo root)
        repo_root = Path(__file__).resolve().parents[2]
        nexus_path = repo_root / "NEXUSBOT.md"
        if nexus_path.exists():
            content = nexus_path.read_text(errors="replace")
            nodes.append({"id": "NEXUSBOT.md", "type": "brain", "size": len(content), "group": "project"})
            file_contents["NEXUSBOT.md"] = content

        # Skills
        skills = self._enumerate_skills()
        for s in skills:
            skill_name = s["name"]
            skill_path = workspace / "skills" / skill_name / "SKILL.md"
            content = ""
            if skill_path.exists():
                content = skill_path.read_text(errors="replace")
            nodes.append({"id": skill_name, "type": "skill", "size": len(content) or 100, "group": "skill"})
            file_contents[skill_name] = content

        # Build edges via cross-references
        node_ids = {n["id"] for n in nodes}
        # Also match without .md suffix for brain files
        name_patterns: dict[str, str] = {}
        for nid in node_ids:
            base = nid.replace(".md", "") if nid.endswith(".md") else nid
            # Match whole word (case-insensitive)
            name_patterns[nid] = r'\b' + re.escape(base) + r'\b'

        edges = []
        seen_edges: set[tuple[str, str]] = set()
        for src_id, src_content in file_contents.items():
            if not src_content:
                continue
            for tgt_id, pattern in name_patterns.items():
                if tgt_id == src_id:
                    continue
                edge_key = (src_id, tgt_id)
                if edge_key in seen_edges:
                    continue
                if re.search(pattern, src_content, re.IGNORECASE):
                    edges.append({"source": src_id, "target": tgt_id})
                    seen_edges.add(edge_key)

        return web.json_response({"nodes": nodes, "edges": edges})

    # ── Twitter Handlers ────────────────────────────────────────

    def _get_twitter_agent(self):
        """Get TwitterAgent from registry."""
        if self.agent_registry:
            return self.agent_registry.get("twitter")
        return None

    async def _handle_twitter_feed(self, request: web.Request) -> web.Response:
        agent = self._get_twitter_agent()
        if not agent:
            return web.json_response({"error": "Twitter agent not available"}, status=503)
        from nanobot.agent.twitter import TwitterAgent
        if isinstance(agent, TwitterAgent):
            scan = agent.get_latest_scan("feed")
            return web.json_response(scan or {"items": [], "count": 0})
        return web.json_response({"items": []})

    async def _handle_twitter_stories(self, request: web.Request) -> web.Response:
        agent = self._get_twitter_agent()
        if not agent:
            return web.json_response([], status=503)
        from nanobot.agent.twitter import TwitterAgent
        if isinstance(agent, TwitterAgent):
            return web.json_response(agent.get_stories())
        return web.json_response([])

    async def _handle_twitter_queue(self, request: web.Request) -> web.Response:
        agent = self._get_twitter_agent()
        if not agent:
            return web.json_response([], status=503)
        from nanobot.agent.twitter import TwitterAgent
        if isinstance(agent, TwitterAgent):
            return web.json_response(agent._queue_list())
        return web.json_response([])

    async def _handle_twitter_approve(self, request: web.Request) -> web.Response:
        agent = self._get_twitter_agent()
        if not agent:
            return web.json_response({"error": "Twitter agent not available"}, status=503)
        draft_id = request.match_info["draft_id"]
        from nanobot.agent.twitter import TwitterAgent
        if isinstance(agent, TwitterAgent):
            draft = agent._queue_get(draft_id)
            if not draft:
                return web.json_response({"error": "Draft not found"}, status=404)
            draft["state"] = "approved"
            agent._queue_save(draft)
            return web.json_response({"ok": True, "draft_id": draft_id})
        return web.json_response({"error": "Wrong agent type"}, status=500)

    async def _handle_twitter_edit(self, request: web.Request) -> web.Response:
        agent = self._get_twitter_agent()
        if not agent:
            return web.json_response({"error": "Twitter agent not available"}, status=503)
        draft_id = request.match_info["draft_id"]
        body = await request.json()
        text = body.get("text", "")
        from nanobot.agent.twitter import TwitterAgent
        if isinstance(agent, TwitterAgent):
            draft = agent._queue_get(draft_id)
            if not draft:
                return web.json_response({"error": "Draft not found"}, status=404)
            if text:
                draft["text"] = text
            agent._queue_save(draft)
            return web.json_response({"ok": True, "draft_id": draft_id})
        return web.json_response({"error": "Wrong agent type"}, status=500)

    async def _handle_twitter_reject(self, request: web.Request) -> web.Response:
        agent = self._get_twitter_agent()
        if not agent:
            return web.json_response({"error": "Twitter agent not available"}, status=503)
        draft_id = request.match_info["draft_id"]
        from nanobot.agent.twitter import TwitterAgent
        if isinstance(agent, TwitterAgent):
            draft = agent._queue_get(draft_id)
            if not draft:
                return web.json_response({"error": "Draft not found"}, status=404)
            draft["state"] = "rejected"
            agent._queue_save(draft)
            return web.json_response({"ok": True, "draft_id": draft_id})
        return web.json_response({"error": "Wrong agent type"}, status=500)

    async def _handle_twitter_post(self, request: web.Request) -> web.Response:
        agent = self._get_twitter_agent()
        if not agent:
            return web.json_response({"error": "Twitter agent not available"}, status=503)
        draft_id = request.match_info["draft_id"]
        from nanobot.agent.twitter import TwitterAgent
        if isinstance(agent, TwitterAgent):
            result = await agent.post_tweet(draft_id)
            ok = not result.startswith("Error")
            return web.json_response({"ok": ok, "result": result}, status=200 if ok else 400)
        return web.json_response({"error": "Wrong agent type"}, status=500)

    async def _handle_twitter_performance(self, request: web.Request) -> web.Response:
        agent = self._get_twitter_agent()
        if not agent:
            return web.json_response({}, status=503)
        from nanobot.agent.twitter import TwitterAgent
        if isinstance(agent, TwitterAgent):
            return web.json_response(agent.get_metrics())
        return web.json_response({})

    async def _handle_twitter_style(self, request: web.Request) -> web.Response:
        agent = self._get_twitter_agent()
        if not agent:
            return web.json_response({"content": ""}, status=503)
        from nanobot.agent.twitter import TwitterAgent
        if isinstance(agent, TwitterAgent):
            return web.json_response({"content": agent.get_style()})
        return web.json_response({"content": ""})

    async def _handle_twitter_put_style(self, request: web.Request) -> web.Response:
        agent = self._get_twitter_agent()
        if not agent:
            return web.json_response({"error": "Twitter agent not available"}, status=503)
        body = await request.json()
        content = body.get("content", "")
        from nanobot.agent.twitter import TwitterAgent
        if isinstance(agent, TwitterAgent):
            agent.save_style(content)
            return web.json_response({"ok": True, "size": len(content)})
        return web.json_response({"error": "Wrong agent type"}, status=500)

    # ── Research Handlers ─────────────────────────────────────────

    async def _handle_research_results(self, request: web.Request) -> web.Response:
        """List recent search results."""
        results_dir = self.engineer.workspace / "research" / "results"
        if not results_dir.exists():
            return web.json_response([])
        files = sorted(results_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        results = []
        for f in files[:20]:
            try:
                data = json.loads(f.read_text())
                results.append({
                    "filename": f.name,
                    "query": data.get("query", ""),
                    "timestamp": data.get("timestamp", ""),
                    "sources": data.get("sources", []),
                    "result_count": sum(len(v) for v in data.get("results", {}).values() if isinstance(v, list)),
                })
            except Exception:
                pass
        return web.json_response(results)

    async def _handle_research_notes(self, request: web.Request) -> web.Response:
        """List notes in the knowledge base."""
        from nanobot.config.schema import ResearchConfig
        config = ResearchConfig()
        vault = Path(config.obsidian_vault_path).expanduser() / "NexusBot"
        if not vault.exists():
            return web.json_response([])
        notes = []
        for f in sorted(vault.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
            notes.append({
                "name": f.name,
                "size": f.stat().st_size,
                "modified": f.stat().st_mtime,
            })
        return web.json_response(notes)

    async def _handle_research_capture(self, request: web.Request) -> web.Response:
        """Capture content into the knowledge base (for browser extension / bookmarklet)."""
        body = await request.json()
        title = body.get("title", "")
        content = body.get("content", "")
        tags = body.get("tags", [])
        source_url = body.get("url", "")
        if not title or not content:
            return web.json_response({"error": "title and content required"}, status=400)
        # Use the research tool to index
        if self.agent_loop:
            research_tool = self.agent_loop.tools.get("research")
            if research_tool:
                result = await research_tool.execute(
                    operation="index", title=title, content=content,
                    tags=tags, source_url=source_url,
                )
                return web.json_response({"ok": True, "result": result})
        return web.json_response({"error": "Research tool not available"}, status=503)

    # ── Email PA Handlers ─────────────────────────────────────────

    def _get_email_pa(self):
        if self.agent_registry:
            return self.agent_registry.get("email_pa")
        return None

    async def _handle_email_triage(self, request: web.Request) -> web.Response:
        agent = self._get_email_pa()
        if not agent:
            return web.json_response({"items": [], "count": 0}, status=503)
        from nanobot.agent.email_pa import EmailPAAgent
        if isinstance(agent, EmailPAAgent):
            return web.json_response(agent.get_triage())
        return web.json_response({"items": []})

    async def _handle_email_drafts(self, request: web.Request) -> web.Response:
        agent = self._get_email_pa()
        if not agent:
            return web.json_response([], status=503)
        from nanobot.agent.email_pa import EmailPAAgent
        if isinstance(agent, EmailPAAgent):
            return web.json_response(agent.list_drafts())
        return web.json_response([])

    async def _handle_email_send_draft(self, request: web.Request) -> web.Response:
        agent = self._get_email_pa()
        if not agent:
            return web.json_response({"error": "Email PA not available"}, status=503)
        draft_id = request.match_info["draft_id"]
        from nanobot.agent.email_pa import EmailPAAgent
        if isinstance(agent, EmailPAAgent):
            draft = agent.get_draft(draft_id)
            if not draft:
                return web.json_response({"error": "Draft not found"}, status=404)
            if draft["state"] != "draft":
                return web.json_response({"error": f"Draft in state '{draft['state']}'"}, status=400)
            from nanobot.bus.events import OutboundMessage
            await agent.bus.publish_outbound(OutboundMessage(
                channel="email", chat_id=draft["to"], content=draft["body"],
                metadata={"subject": draft["subject"], "force_send": True},
            ))
            agent.update_draft(draft_id, state="sent")
            agent.log_action("send_response", draft.get("email_id", ""), {
                "draft_id": draft_id, "to": draft["to"],
            })
            return web.json_response({"ok": True, "draft_id": draft_id})
        return web.json_response({"error": "Wrong agent type"}, status=500)

    async def _handle_email_discard_draft(self, request: web.Request) -> web.Response:
        agent = self._get_email_pa()
        if not agent:
            return web.json_response({"error": "Email PA not available"}, status=503)
        draft_id = request.match_info["draft_id"]
        from nanobot.agent.email_pa import EmailPAAgent
        if isinstance(agent, EmailPAAgent):
            draft = agent.get_draft(draft_id)
            if not draft:
                return web.json_response({"error": "Draft not found"}, status=404)
            agent.update_draft(draft_id, state="discarded")
            return web.json_response({"ok": True})
        return web.json_response({"error": "Wrong agent type"}, status=500)

    async def _handle_email_actions(self, request: web.Request) -> web.Response:
        agent = self._get_email_pa()
        if not agent:
            return web.json_response([], status=503)
        from nanobot.agent.email_pa import EmailPAAgent
        if isinstance(agent, EmailPAAgent):
            return web.json_response(agent.get_actions(50))
        return web.json_response([])

    async def _handle_email_undo(self, request: web.Request) -> web.Response:
        agent = self._get_email_pa()
        if not agent:
            return web.json_response({"error": "Email PA not available"}, status=503)
        action_id = request.match_info["action_id"]
        from nanobot.agent.email_pa import EmailPAAgent
        if isinstance(agent, EmailPAAgent):
            result = agent.undo_action(action_id)
            return web.json_response({"result": result})
        return web.json_response({"error": "Wrong agent type"}, status=500)

    async def _handle_email_rules(self, request: web.Request) -> web.Response:
        agent = self._get_email_pa()
        if not agent:
            return web.json_response([], status=503)
        from nanobot.agent.email_pa import EmailPAAgent
        if isinstance(agent, EmailPAAgent):
            return web.json_response(agent.get_rules())
        return web.json_response([])

    async def _handle_email_snoozed(self, request: web.Request) -> web.Response:
        agent = self._get_email_pa()
        if not agent:
            return web.json_response([], status=503)
        from nanobot.agent.email_pa import EmailPAAgent
        if isinstance(agent, EmailPAAgent):
            return web.json_response(agent.get_snoozed())
        return web.json_response([])

    # ── GitHub Agent Handlers ──────────────────────────────────────

    def _get_github_tool(self):
        if self.agent_loop:
            return self.agent_loop.tools.get("github_scan")
        return None

    async def _handle_github_trending(self, request: web.Request) -> web.Response:
        tool = self._get_github_tool()
        if not tool:
            return web.json_response({"error": "GitHub tool not available"}, status=503)
        language = request.query.get("language", "")
        since = request.query.get("since", "daily")
        max_results = int(request.query.get("max_results", "15"))
        result = await tool.execute(operation="trending", language=language, since=since, max_results=max_results)
        return web.json_response({"result": result})

    async def _handle_github_insights(self, request: web.Request) -> web.Response:
        tool = self._get_github_tool()
        if not tool:
            return web.json_response({"error": "GitHub tool not available"}, status=503)
        result = tool._get_insights()
        return web.json_response({"result": result})

    async def _handle_github_scans(self, request: web.Request) -> web.Response:
        tool = self._get_github_tool()
        if not tool:
            return web.json_response({"scans": []}, status=503)
        scan_dir = tool._scan_dir
        scans = []
        if scan_dir.exists():
            for f in sorted(scan_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
                if f.name == "insights.json":
                    continue
                try:
                    data = json.loads(f.read_text())
                    scans.append({"filename": f.name, **data})
                except Exception:
                    pass
        return web.json_response({"scans": scans})

    async def _handle_github_search(self, request: web.Request) -> web.Response:
        tool = self._get_github_tool()
        if not tool:
            return web.json_response({"error": "GitHub tool not available"}, status=503)
        body = await request.json()
        query = body.get("query", "")
        if not query:
            return web.json_response({"error": "query required"}, status=400)
        max_results = body.get("max_results", 10)
        result = await tool.execute(operation="search_repos", query=query, max_results=max_results)
        return web.json_response({"result": result})

    async def _handle_github_analyze(self, request: web.Request) -> web.Response:
        tool = self._get_github_tool()
        if not tool:
            return web.json_response({"error": "GitHub tool not available"}, status=503)
        body = await request.json()
        repo = body.get("repo", "")
        if not repo:
            return web.json_response({"error": "repo required (owner/name)"}, status=400)
        result = await tool.execute(operation="analyze_repo", repo=repo)
        return web.json_response({"result": result})

    async def _handle_architecture(self, request: web.Request) -> web.Response:
        """Return architecture data for the diagram."""
        # Gather live state for accuracy
        workspace = self.engineer.workspace
        skills = self._enumerate_skills()
        always_skills = [s["name"] for s in skills if self._is_always_skill(s)]
        on_demand_skills = [s["name"] for s in skills if not self._is_always_skill(s)]

        sessions_dir = workspace / "sessions"
        session_files = list(sessions_dir.glob("*.jsonl")) if sessions_dir.exists() else []
        channels = set()
        for f in session_files:
            key = f.stem.replace("_", ":")
            if ":" in key:
                channels.add(key.split(":")[0])

        tools = [
            "read_file", "write_file", "edit_file", "list_dir",
            "exec", "web_search", "web_fetch", "message", "spawn", "dispatch",
        ]
        if (workspace / "cron" / "jobs.json").exists():
            tools.append("cron")

        return web.json_response({
            "channels": sorted(channels),
            "tools": tools,
            "always_skills": always_skills,
            "on_demand_skills": on_demand_skills,
            "bootstrap_files": ["SOUL.md", "USER.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md"],
            "memory_files": ["MEMORY.md", "HISTORY.md"],
            "session_count": len(session_files),
        })

    def _is_always_skill(self, skill: dict) -> bool:
        """Check if a skill is always-on by reading its frontmatter."""
        try:
            content = Path(skill["path"]).read_text()
            return "always: true" in content[:500]
        except Exception:
            return False

    async def _handle_index_fallback(self, request: web.Request) -> web.Response:
        """Redirect to the deployed Cloudflare Pages dashboard with the local API URL."""
        # Use https when accessed via Cloudflare Tunnel, http for local access
        scheme = "https" if request.headers.get("CF-Connecting-IP") else "http"
        local_api = f"{scheme}://{request.host}"
        pages_url = f"https://nanobot-dashboard.pages.dev/?api={local_api}"
        raise web.HTTPFound(pages_url)

    # ── WebSocket ────────────────────────────────────────────────

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._ws_clients.append(ws)
        logger.info("Dashboard WebSocket client connected ({} total)", len(self._ws_clients))

        try:
            async for msg in ws:
                pass  # Read loop keeps connection alive
        finally:
            self._ws_clients.remove(ws)
            logger.info("Dashboard WebSocket client disconnected ({} total)", len(self._ws_clients))

        return ws

    async def _broadcast(self, data: dict) -> None:
        """Broadcast a message to all connected WebSocket clients."""
        if not self._ws_clients:
            return
        payload = json.dumps(data)
        for ws in list(self._ws_clients):
            try:
                await ws.send_str(payload)
            except Exception:
                self._ws_clients.remove(ws)

    async def notify_project_update(self, project_id: str) -> None:
        """Called by engineer agent when a project state changes."""
        await self._broadcast({"type": "project_updated", "project_id": project_id})

    # ── Server lifecycle ─────────────────────────────────────────

    async def start(self) -> None:
        """Start the dashboard HTTP server."""
        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info("Dashboard server started on http://{}:{}", self.host, self.port)

    @property
    def app(self) -> web.Application:
        return self._app
