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

# Bootstrap files that form the system prompt (order matters)
BRAIN_FILES = ["SOUL.md", "USER.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md"]


class DashboardServer:
    """Serves the dashboard API and static frontend."""

    def __init__(self, engineer: "Engineer", agent_loop: "AgentLoop | None" = None, host: str = "0.0.0.0", port: int = 18791):
        self.engineer = engineer
        self.agent_loop = agent_loop
        self.host = host
        self.port = port
        self._app = web.Application()
        self._ws_clients: list[web.WebSocketResponse] = []
        self._chat_lock = asyncio.Lock()  # Serialize chat requests (agent is single-threaded)
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
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS"
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
