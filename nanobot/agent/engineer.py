"""Engineer agent: manages projects with work items dispatched to Claude Code / Codex sessions via tmux."""

import asyncio
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.specialized import SpecializedAgent
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus


SENTINEL = "___NANOBOT_DONE___"
SOCKET_DIR = os.environ.get("NANOBOT_TMUX_SOCKET_DIR", os.path.join(os.environ.get("TMPDIR", "/tmp"), "nanobot-tmux-sockets"))
SOCKET_PATH = os.path.join(SOCKET_DIR, "engineer.sock")
TEMP_DIR = os.path.join(os.environ.get("TMPDIR", "/tmp"), "nanobot-engineer")

MAX_CONCURRENT_SESSIONS = 3
POLL_INTERVAL_S = 15


WORKTREE_DIR = os.path.join(os.environ.get("TMPDIR", "/tmp"), "nanobot-worktrees")


@dataclass
class WorkItem:
    id: str
    title: str
    instructions: str
    scope: dict = field(default_factory=lambda: {"files_writable": [], "files_readable": []})
    agent: str = "claude"  # "claude" or "codex"
    depends_on: list[str] = field(default_factory=list)
    state: str = "pending"  # pending | running | done | failed
    result_summary: str | None = None
    tmux_session: str | None = None
    output_file: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    git_diff: str | None = None
    cost_usd: float | None = None
    worktree_path: str | None = None
    worktree_branch: str | None = None


@dataclass
class Project:
    id: str
    title: str
    target_dir: str
    work_items: list[WorkItem] = field(default_factory=list)
    state: str = "planning"  # planning | approved | running | done | failed
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: str | None = None
    origin_channel: str = "discord"
    origin_chat_id: str = ""
    use_worktrees: bool = False  # Enable git worktrees for parallel work on overlapping files


class Engineer(SpecializedAgent):
    """Manages projects and their work items, dispatching to Claude Code / Codex via tmux."""

    def __init__(self, workspace: Path, bus: MessageBus):
        super().__init__(name="engineer", workspace=workspace, bus=bus)
        self.projects_dir = self._workspace_dir / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        os.makedirs(TEMP_DIR, exist_ok=True)
        os.makedirs(SOCKET_DIR, exist_ok=True)
        self._polling_task: asyncio.Task | None = None
        self._projects: dict[str, Project] = {}
        self._file_locks: dict[str, str] = {}  # file_path -> work_item_id
        self._load_projects()

    async def _notify_dashboard(self, project_id: str) -> None:
        """Notify the dashboard of a project state change."""
        await self.notify_dashboard("project_updated", {"project_id": project_id})

    # ── SpecializedAgent interface ────────────────────────────────

    async def execute(self, operation: str, **kwargs: Any) -> str:
        """Execute an engineer operation (delegated from dispatch tool)."""
        if operation == "status":
            pid = kwargs.get("project_id")
            if pid:
                return self.get_status(pid)
            projects = self.list_projects()
            if not projects:
                return "No projects."
            return "\n\n".join(self.get_status(p.id) for p in projects[-3:])
        elif operation == "list":
            projects = self.list_projects()
            if not projects:
                return "No projects."
            lines = []
            for p in projects:
                done = sum(1 for wi in p.work_items if wi.state == "done")
                lines.append(f"- `{p.id}` **{p.title}** [{p.state}] ({done}/{len(p.work_items)} done)")
            return "\n".join(lines)
        return f"Unknown operation: {operation}"

    def status_summary(self) -> str:
        """Return a short status summary."""
        projects = self.list_projects()
        running = sum(1 for p in projects if p.state == "running")
        total = len(projects)
        return f"{total} projects ({running} running)"

    # ── Persistence ──────────────────────────────────────────────

    def _load_projects(self) -> None:
        """Load all project state from disk."""
        for f in self.projects_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                items = [WorkItem(**wi) for wi in data.pop("work_items", [])]
                proj = Project(**data, work_items=items)
                self._projects[proj.id] = proj
            except Exception as e:
                logger.warning("Failed to load project {}: {}", f.name, e)

    def _save_project(self, project: Project) -> None:
        """Persist project state to disk."""
        path = self.projects_dir / f"{project.id}.json"
        path.write_text(json.dumps(asdict(project), indent=2, default=str))

    # ── Project lifecycle ────────────────────────────────────────

    def create_project(self, title: str, target_dir: str, work_items_data: list[dict],
                       origin_channel: str = "discord", origin_chat_id: str = "",
                       use_worktrees: bool = False) -> Project:
        """Create a new project from decomposed work items."""
        project_id = str(uuid.uuid4())[:8]
        items = []
        for i, wi in enumerate(work_items_data):
            items.append(WorkItem(
                id=wi.get("id", f"w{i+1}"),
                title=wi.get("title", f"Work item {i+1}"),
                instructions=wi.get("instructions", ""),
                scope=wi.get("scope", {"files_writable": [], "files_readable": []}),
                agent=wi.get("agent", "claude"),
                depends_on=wi.get("depends_on", []),
            ))

        project = Project(
            id=project_id,
            title=title,
            target_dir=target_dir,
            work_items=items,
            origin_channel=origin_channel,
            origin_chat_id=origin_chat_id,
            use_worktrees=use_worktrees,
        )
        self._projects[project_id] = project
        self._save_project(project)
        logger.info("Created project [{}]: {} with {} work items", project_id, title, len(items))
        return project

    def approve_project(self, project_id: str) -> str:
        """Mark a project as approved for execution."""
        proj = self._projects.get(project_id)
        if not proj:
            return f"Error: Project {project_id} not found"
        if proj.state != "planning":
            return f"Error: Project is in state '{proj.state}', expected 'planning'"
        proj.state = "approved"
        self._save_project(proj)
        return f"Project {project_id} approved. Call run to dispatch work items."

    def get_project(self, project_id: str) -> Project | None:
        return self._projects.get(project_id)

    def list_projects(self) -> list[Project]:
        return list(self._projects.values())

    def get_status(self, project_id: str) -> str:
        """Get a formatted status summary for a project."""
        proj = self._projects.get(project_id)
        if not proj:
            return f"Error: Project {project_id} not found"

        lines = [f"**{proj.title}** (`{proj.id}`) — {proj.state}"]
        for wi in proj.work_items:
            status_icon = {"pending": "⏳", "running": "🔄", "done": "✅", "failed": "❌"}.get(wi.state, "❓")
            dep_str = f" (depends on: {', '.join(wi.depends_on)})" if wi.depends_on else ""
            agent_str = f" [{wi.agent}]"
            line = f"  {status_icon} **{wi.id}**: {wi.title}{agent_str}{dep_str}"
            if wi.result_summary:
                line += f"\n    → {wi.result_summary}"
            if wi.error:
                line += f"\n    ⚠ {wi.error}"
            lines.append(line)

        done = sum(1 for wi in proj.work_items if wi.state == "done")
        total = len(proj.work_items)
        lines.append(f"\nProgress: {done}/{total} items complete")
        return "\n".join(lines)

    # ── Conflict prevention ──────────────────────────────────────

    def _check_file_conflicts(self, item: WorkItem) -> list[str]:
        """Check if any writable files conflict with currently locked files."""
        conflicts = []
        for f in item.scope.get("files_writable", []):
            if f in self._file_locks and self._file_locks[f] != item.id:
                conflicts.append(f"File '{f}' is locked by work item '{self._file_locks[f]}'")
        return conflicts

    def _lock_files(self, item: WorkItem) -> None:
        """Lock writable files for a work item."""
        for f in item.scope.get("files_writable", []):
            self._file_locks[f] = item.id

    def _unlock_files(self, item: WorkItem) -> None:
        """Release file locks for a work item."""
        for f in item.scope.get("files_writable", []):
            if self._file_locks.get(f) == item.id:
                del self._file_locks[f]

    def _save_locks(self) -> None:
        """Persist file locks to disk."""
        locks_file = self.workspace / "engineer" / "locks.json"
        locks_file.write_text(json.dumps(self._file_locks, indent=2))

    # ── Dispatch ─────────────────────────────────────────────────

    def _get_ready_items(self, project: Project) -> list[WorkItem]:
        """Get work items that are ready to dispatch (all dependencies met, no file conflicts)."""
        done_ids = {wi.id for wi in project.work_items if wi.state == "done"}
        running_count = sum(1 for wi in project.work_items if wi.state == "running")

        ready = []
        for wi in project.work_items:
            if wi.state != "pending":
                continue
            if not all(dep in done_ids for dep in wi.depends_on):
                continue
            # Skip file conflict check when worktrees are enabled — each item gets its own copy
            if not project.use_worktrees and self._check_file_conflicts(wi):
                continue
            if running_count + len(ready) >= MAX_CONCURRENT_SESSIONS:
                break
            ready.append(wi)
        return ready

    async def dispatch_ready(self, project_id: str) -> str:
        """Dispatch all ready work items for a project."""
        proj = self._projects.get(project_id)
        if not proj:
            return f"Error: Project {project_id} not found"
        if proj.state not in ("approved", "running"):
            return f"Error: Project must be approved before running (current state: {proj.state})"

        proj.state = "running"
        ready = self._get_ready_items(proj)
        if not ready:
            # Check if all done
            if all(wi.state in ("done", "failed") for wi in proj.work_items):
                return self._complete_project(proj)
            pending_blocked = [wi for wi in proj.work_items if wi.state == "pending"]
            if pending_blocked:
                return f"No items ready to dispatch. {len(pending_blocked)} items waiting on dependencies."
            return "No items to dispatch."

        dispatched = []
        for item in ready:
            try:
                await self._dispatch_item(proj, item)
                dispatched.append(item.id)
            except Exception as e:
                item.state = "failed"
                item.error = str(e)
                logger.error("Failed to dispatch {}: {}", item.id, e)

        self._save_project(proj)
        self._save_locks()
        await self._notify_dashboard(proj.id)

        # Start polling if not already running
        if self._polling_task is None or self._polling_task.done():
            self._polling_task = asyncio.create_task(self._poll_loop())

        return f"Dispatched {len(dispatched)} work item(s): {', '.join(dispatched)}"

    async def _dispatch_item(self, project: Project, item: WorkItem) -> None:
        """Launch a Claude Code or Codex session in tmux for a work item."""
        session_name = f"nanobot-{project.id}-{item.id}"
        instructions_file = os.path.join(TEMP_DIR, f"{project.id}-{item.id}-instructions.md")
        output_file = os.path.join(TEMP_DIR, f"{project.id}-{item.id}-output.json")

        # Determine working directory (worktree or main repo)
        work_dir = project.target_dir
        if project.use_worktrees:
            work_dir = await self._create_worktree(project, item)

        # Build self-contained instructions
        full_instructions = self._build_instructions(project, item, work_dir)
        Path(instructions_file).write_text(full_instructions)

        # Create tmux session
        await self._exec(f'tmux -S "{SOCKET_PATH}" new-session -d -s "{session_name}"')

        # Build the command based on agent type
        if item.agent == "codex":
            cmd = (
                f'cd "{work_dir}" && '
                f'codex exec --full-auto '
                f'"$(cat {instructions_file})" '
                f'> "{output_file}" 2>&1; '
                f'echo "{SENTINEL}"'
            )
        else:  # claude (default)
            cmd = (
                f'cd "{work_dir}" && '
                f'claude -p --print '
                f'--permission-mode bypassPermissions '
                f'--output-format json '
                f'--max-budget-usd 3.00 '
                f'"$(cat {instructions_file})" '
                f'> "{output_file}" 2>&1; '
                f'echo "{SENTINEL}"'
            )

        # Send command to tmux session
        await self._exec(f'tmux -S "{SOCKET_PATH}" send-keys -t "{session_name}" "{self._escape_tmux(cmd)}" Enter')

        # Update state
        item.state = "running"
        item.tmux_session = session_name
        item.output_file = output_file
        item.started_at = datetime.now().isoformat()
        self._lock_files(item)

        logger.info("Dispatched work item {} [{}] to tmux session {} (worktree: {})",
                     item.id, item.agent, session_name, bool(item.worktree_path))

    # ── Git worktrees ────────────────────────────────────────────

    async def _create_worktree(self, project: Project, item: WorkItem) -> str:
        """Create a git worktree for a work item. Returns the worktree path."""
        os.makedirs(WORKTREE_DIR, exist_ok=True)
        branch_name = f"nanobot/{project.id}/{item.id}"
        worktree_path = os.path.join(WORKTREE_DIR, f"{project.id}-{item.id}")

        # Clean up existing worktree if present (from a failed previous run)
        if os.path.exists(worktree_path):
            try:
                await self._exec(f'cd "{project.target_dir}" && git worktree remove --force "{worktree_path}"', timeout=15)
            except Exception:
                pass

        # Create worktree with a new branch from current HEAD
        await self._exec(
            f'cd "{project.target_dir}" && git worktree add -b "{branch_name}" "{worktree_path}" HEAD',
            timeout=30,
        )

        item.worktree_path = worktree_path
        item.worktree_branch = branch_name
        logger.info("Created worktree for {}: {} on branch {}", item.id, worktree_path, branch_name)
        return worktree_path

    async def _merge_worktree(self, project: Project, item: WorkItem) -> str | None:
        """Merge a worktree branch back into the main branch. Returns merge output or None on failure."""
        if not item.worktree_branch or not item.worktree_path:
            return None

        try:
            # Get the current branch name of the main repo
            main_branch = await self._exec(
                f'cd "{project.target_dir}" && git rev-parse --abbrev-ref HEAD', timeout=10
            )

            # Check if there are any commits on the worktree branch beyond the base
            diff_check = await self._exec(
                f'cd "{project.target_dir}" && git log --oneline "{main_branch}..{item.worktree_branch}" 2>/dev/null',
                timeout=10,
            )
            if not diff_check.strip():
                logger.info("Worktree branch {} has no new commits, skipping merge", item.worktree_branch)
                return "No changes to merge"

            # Merge the worktree branch
            merge_output = await self._exec(
                f'cd "{project.target_dir}" && git merge --no-ff -m '
                f'"nanobot: merge {item.id} ({item.title})" "{item.worktree_branch}"',
                timeout=30,
            )
            logger.info("Merged worktree branch {} into {}", item.worktree_branch, main_branch)
            return merge_output

        except RuntimeError as e:
            error_msg = str(e)
            if "CONFLICT" in error_msg or "conflict" in error_msg:
                # Abort the failed merge
                try:
                    await self._exec(f'cd "{project.target_dir}" && git merge --abort', timeout=10)
                except Exception:
                    pass
                logger.warning("Merge conflict for {}: {}", item.id, error_msg)
                return f"MERGE CONFLICT: {error_msg}"
            raise

    async def _cleanup_worktree(self, project: Project, item: WorkItem) -> None:
        """Remove a git worktree and optionally its branch."""
        if not item.worktree_path:
            return

        try:
            await self._exec(
                f'cd "{project.target_dir}" && git worktree remove --force "{item.worktree_path}"',
                timeout=15,
            )
        except Exception as e:
            logger.warning("Failed to remove worktree {}: {}", item.worktree_path, e)

        # Delete the branch if it was merged
        if item.worktree_branch:
            try:
                await self._exec(
                    f'cd "{project.target_dir}" && git branch -d "{item.worktree_branch}" 2>/dev/null',
                    timeout=10,
                )
            except Exception:
                pass  # Branch may not exist or not be fully merged

    def _build_instructions(self, project: Project, item: WorkItem, work_dir: str | None = None) -> str:
        """Build fully self-contained instructions for a Claude Code / Codex session."""
        effective_dir = work_dir or project.target_dir
        writable = "\n".join(f"  - {f}" for f in item.scope.get("files_writable", [])) or "  (any files as needed)"
        readable = "\n".join(f"  - {f}" for f in item.scope.get("files_readable", [])) or "  (any files as needed)"

        other_items = [wi for wi in project.work_items if wi.id != item.id]
        other_scopes = ""
        if other_items:
            lines = []
            for wi in other_items:
                files = wi.scope.get("files_writable", [])
                if files:
                    lines.append(f"  - {wi.id} ({wi.title}): {', '.join(files)}")
            if lines:
                other_scopes = (
                    "\n\n## DO NOT MODIFY these files (owned by other work items):\n" +
                    "\n".join(lines)
                )

        # Include results from completed dependencies
        dep_context = ""
        if item.depends_on:
            dep_results = []
            for dep_id in item.depends_on:
                dep_item = next((wi for wi in project.work_items if wi.id == dep_id), None)
                if dep_item and dep_item.result_summary:
                    dep_results.append(f"### {dep_id}: {dep_item.title}\n{dep_item.result_summary}")
            if dep_results:
                dep_context = "\n\n## Context from completed dependencies:\n" + "\n\n".join(dep_results)

        worktree_note = ""
        if item.worktree_path:
            worktree_note = f"\n\nNote: You are working in a git worktree on branch `{item.worktree_branch}`. Commit your changes normally — they will be merged back to the main branch automatically."

        return f"""# Task: {item.title}

Project: {project.title}
Working directory: {effective_dir}{worktree_note}

## Instructions

{item.instructions}

## File scope

You may WRITE to:
{writable}

You may READ from:
{readable}
{other_scopes}
{dep_context}

## Guidelines

- Stay focused on this specific task only
- Read relevant files before making changes
- Make minimal, targeted changes
- Run any available tests related to your changes
- Do NOT modify files outside your writable scope
"""

    @staticmethod
    def _escape_tmux(cmd: str) -> str:
        """Escape a command for tmux send-keys."""
        return cmd.replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")

    async def _exec(self, command: str, timeout: int = 10) -> str:
        """Execute a shell command and return output."""
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"Command timed out: {command[:80]}")

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            # Don't fail on "duplicate session" errors
            if "duplicate session" not in err:
                raise RuntimeError(f"Command failed (rc={proc.returncode}): {err}")
        return stdout.decode("utf-8", errors="replace").strip()

    # ── Polling ──────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        """Poll running work items for completion."""
        logger.info("Engineer polling loop started")
        while True:
            try:
                any_running = False
                for proj in self._projects.values():
                    if proj.state != "running":
                        continue
                    for item in proj.work_items:
                        if item.state != "running" or not item.tmux_session:
                            continue
                        any_running = True
                        if await self._check_completion(item):
                            await self._harvest_result(proj, item)
                            # Dispatch next ready items
                            ready = self._get_ready_items(proj)
                            for next_item in ready:
                                try:
                                    await self._dispatch_item(proj, next_item)
                                except Exception as e:
                                    next_item.state = "failed"
                                    next_item.error = str(e)
                            self._save_project(proj)
                            self._save_locks()

                            # Notify dashboard when new items dispatched
                            await self._notify_dashboard(proj.id)

                            # Check if project is complete
                            if all(wi.state in ("done", "failed") for wi in proj.work_items):
                                self._complete_project(proj)
                                self._save_project(proj)
                                await self._notify_dashboard(proj.id)
                                await self._announce_completion(proj)

                if not any_running:
                    logger.info("Engineer polling loop: no running items, stopping")
                    break

                await asyncio.sleep(POLL_INTERVAL_S)
            except asyncio.CancelledError:
                logger.info("Engineer polling loop cancelled")
                break
            except Exception:
                logger.exception("Error in engineer polling loop")
                await asyncio.sleep(POLL_INTERVAL_S)

    async def _check_completion(self, item: WorkItem) -> bool:
        """Check if a tmux session has completed by looking for sentinel marker."""
        try:
            output = await self._exec(
                f'tmux -S "{SOCKET_PATH}" capture-pane -p -t "{item.tmux_session}" -S -10'
            )
            return SENTINEL in output
        except Exception:
            return False

    async def _harvest_result(self, project: Project, item: WorkItem) -> None:
        """Read output from a completed work item and update state."""
        item.completed_at = datetime.now().isoformat()

        # Read output file
        output_content = ""
        if item.output_file and Path(item.output_file).exists():
            try:
                raw = Path(item.output_file).read_text()
                output_content = raw[:20000]  # Limit to 20KB

                # Try to parse Claude Code JSON output for cost info
                if item.agent == "claude":
                    try:
                        data = json.loads(raw)
                        if isinstance(data, dict):
                            item.cost_usd = data.get("cost_usd")
                            output_content = data.get("result", raw[:5000])
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                logger.warning("Failed to read output for {}: {}", item.id, e)

        # Capture git diff (from worktree or main dir)
        diff_dir = item.worktree_path or project.target_dir
        try:
            diff = await self._exec(f'cd "{diff_dir}" && git diff --stat HEAD', timeout=15)
            if diff.strip():
                item.git_diff = diff[:5000]
        except Exception:
            pass

        # Merge worktree branch back if applicable
        if item.worktree_path:
            merge_result = await self._merge_worktree(project, item)
            if merge_result and "MERGE CONFLICT" in merge_result:
                item.error = merge_result
                item.state = "failed"
                # Don't clean up worktree on conflict — user may want to resolve manually
                logger.warning("Work item {} completed but merge failed: {}", item.id, merge_result)
            else:
                await self._cleanup_worktree(project, item)

        # Generate summary
        summary_parts = []
        if output_content:
            # Take first 200 chars as summary
            preview = output_content[:200].replace("\n", " ")
            summary_parts.append(preview)
        if item.git_diff:
            summary_parts.append(f"Changes: {item.git_diff.split(chr(10))[-1].strip()}")

        item.result_summary = " | ".join(summary_parts) if summary_parts else "Completed (no output captured)"
        item.state = "done"
        self._unlock_files(item)

        # Clean up tmux session
        try:
            await self._exec(f'tmux -S "{SOCKET_PATH}" kill-session -t "{item.tmux_session}"')
        except Exception:
            pass

        logger.info("Harvested result for work item {}: {}", item.id, item.state)

        # Notify dashboard + Discord
        await self._notify_dashboard(project.id)
        await self._announce_progress(project, item)

    def _complete_project(self, project: Project) -> str:
        """Mark a project as complete."""
        failed = [wi for wi in project.work_items if wi.state == "failed"]
        project.state = "failed" if failed and len(failed) == len(project.work_items) else "done"
        project.completed_at = datetime.now().isoformat()

        done = sum(1 for wi in project.work_items if wi.state == "done")
        total = len(project.work_items)
        self._save_project(project)

        status = f"Project '{project.title}' completed: {done}/{total} items succeeded."
        if failed:
            status += f" {len(failed)} item(s) failed: {', '.join(wi.id for wi in failed)}"
        logger.info(status)
        return status

    # ── Announcements ────────────────────────────────────────────

    async def _announce_progress(self, project: Project, item: WorkItem) -> None:
        """Announce work item completion to the origin channel."""
        done = sum(1 for wi in project.work_items if wi.state == "done")
        total = len(project.work_items)

        content = (
            f"**[{project.title}]** Work item {done}/{total} complete: "
            f"**{item.title}** ({item.id})\n"
        )
        if item.result_summary:
            content += f"→ {item.result_summary[:300]}\n"
        if item.git_diff:
            content += f"```\n{item.git_diff[:500]}\n```"

        await self.bus.publish_outbound(OutboundMessage(
            channel=project.origin_channel,
            chat_id=project.origin_chat_id,
            content=content,
        ))

    async def _announce_completion(self, project: Project) -> None:
        """Announce project completion."""
        done = sum(1 for wi in project.work_items if wi.state == "done")
        failed = sum(1 for wi in project.work_items if wi.state == "failed")
        total = len(project.work_items)

        content = f"**Project complete: {project.title}**\n"
        content += f"✅ {done} succeeded"
        if failed:
            content += f" | ❌ {failed} failed"
        content += f" | {total} total\n\n"

        for wi in project.work_items:
            icon = "✅" if wi.state == "done" else "❌"
            content += f"{icon} **{wi.id}**: {wi.title}\n"
            if wi.result_summary:
                content += f"  → {wi.result_summary[:200]}\n"

        total_cost = sum(wi.cost_usd or 0 for wi in project.work_items)
        if total_cost > 0:
            content += f"\nTotal cost: ${total_cost:.2f}"

        # Announce to origin channel
        await self.bus.publish_outbound(OutboundMessage(
            channel=project.origin_channel,
            chat_id=project.origin_chat_id,
            content=content,
        ))

        # Also write to HISTORY.md
        await self._write_history(project)

    async def _write_history(self, project: Project) -> None:
        """Write project summary to nanobot's HISTORY.md."""
        history_file = self.workspace / "memory" / "HISTORY.md"
        history_file.parent.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M]")
        items_summary = ", ".join(
            f"{wi.id}:{wi.title}({'ok' if wi.state == 'done' else 'fail'})"
            for wi in project.work_items
        )
        entry = (
            f"{timestamp} ENGINEER: Project '{project.title}' ({project.id}) completed. "
            f"Items: {items_summary}. Target: {project.target_dir}\n"
        )

        with open(history_file, "a") as f:
            f.write(entry)

    # ── Cancel ───────────────────────────────────────────────────

    async def cancel_project(self, project_id: str) -> str:
        """Cancel all running work items for a project."""
        proj = self._projects.get(project_id)
        if not proj:
            return f"Error: Project {project_id} not found"

        cancelled = 0
        for item in proj.work_items:
            if item.state == "running" and item.tmux_session:
                try:
                    await self._exec(f'tmux -S "{SOCKET_PATH}" kill-session -t "{item.tmux_session}"')
                except Exception:
                    pass
                if item.worktree_path:
                    await self._cleanup_worktree(proj, item)
                item.state = "failed"
                item.error = "Cancelled by user"
                self._unlock_files(item)
                cancelled += 1

        proj.state = "failed"
        self._save_project(proj)
        self._save_locks()
        return f"Cancelled {cancelled} running item(s) in project '{proj.title}'"

    # ── Resume after restart ─────────────────────────────────────

    async def resume_polling(self) -> int:
        """Resume polling for any projects that were running before restart."""
        running = 0
        for proj in self._projects.values():
            if proj.state != "running":
                continue
            for item in proj.work_items:
                if item.state == "running" and item.tmux_session:
                    # Check if tmux session still exists
                    try:
                        await self._exec(
                            f'tmux -S "{SOCKET_PATH}" has-session -t "{item.tmux_session}"'
                        )
                        running += 1
                    except Exception:
                        item.state = "failed"
                        item.error = "tmux session lost after restart"
                        self._unlock_files(item)
            self._save_project(proj)

        if running > 0 and (self._polling_task is None or self._polling_task.done()):
            self._polling_task = asyncio.create_task(self._poll_loop())
            logger.info("Resumed polling for {} running work items", running)

        return running
