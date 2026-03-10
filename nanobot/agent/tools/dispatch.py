"""Dispatch tool for the Engineer agent — Claude Code / Codex sessions."""

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.engineer import Engineer


class DispatchTool(Tool):
    """Tool to plan, run, and monitor Engineer agent coding sessions."""

    def __init__(self, engineer: "Engineer"):
        self._engineer = engineer
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the origin context for project announcements."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id

    @property
    def name(self) -> str:
        return "dispatch"

    @property
    def description(self) -> str:
        return (
            "Dispatch engineering tasks to Claude Code or Codex sessions. "
            "Operations: 'plan' (create a project with work items), 'approve' (approve a plan for execution), "
            "'run' (dispatch approved work items), 'status' (check project progress), "
            "'cancel' (stop a running project), 'list' (show all projects)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["plan", "approve", "run", "status", "cancel", "list"],
                    "description": "The operation to perform"
                },
                "title": {
                    "type": "string",
                    "description": "Project title (required for 'plan')"
                },
                "target_dir": {
                    "type": "string",
                    "description": "Target directory for the project (required for 'plan')"
                },
                "work_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "instructions": {"type": "string"},
                            "scope": {
                                "type": "object",
                                "properties": {
                                    "files_writable": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    },
                                    "files_readable": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    }
                                }
                            },
                            "agent": {
                                "type": "string",
                                "enum": ["claude", "codex"],
                                "description": "Which coding agent to use"
                            },
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "IDs of work items this depends on"
                            }
                        },
                        "required": ["id", "title", "instructions"]
                    },
                    "description": "Work items (required for 'plan')"
                },
                "project_id": {
                    "type": "string",
                    "description": "Project ID (required for 'approve', 'run', 'status', 'cancel')"
                },
                "use_worktrees": {
                    "type": "boolean",
                    "description": "Use git worktrees for parallel work items (allows overlapping file scopes). Each item gets its own branch, merged back on completion."
                }
            },
            "required": ["operation"]
        }

    async def execute(self, operation: str, **kwargs: Any) -> str:
        if operation == "plan":
            return self._handle_plan(**kwargs)
        elif operation == "approve":
            return self._handle_approve(**kwargs)
        elif operation == "run":
            return await self._handle_run(**kwargs)
        elif operation == "status":
            return self._handle_status(**kwargs)
        elif operation == "cancel":
            return await self._handle_cancel(**kwargs)
        elif operation == "list":
            return self._handle_list()
        else:
            return f"Error: Unknown operation '{operation}'. Use: plan, approve, run, status, cancel, list"

    def _handle_plan(self, title: str = "", target_dir: str = "",
                     work_items: list[dict] | None = None,
                     use_worktrees: bool = False, **kwargs: Any) -> str:
        if not title:
            return "Error: 'title' is required for plan operation"
        if not target_dir:
            return "Error: 'target_dir' is required for plan operation"
        if not work_items:
            return "Error: 'work_items' is required for plan operation"

        project = self._engineer.create_project(
            title=title,
            target_dir=target_dir,
            work_items_data=work_items,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
            use_worktrees=use_worktrees,
        )

        # Format plan for user review
        worktree_label = " (git worktrees enabled)" if project.use_worktrees else ""
        lines = [
            f"📋 **Project Plan: {project.title}** (id: `{project.id}`)",
            f"Target: `{project.target_dir}`{worktree_label}",
            f"Work items: {len(project.work_items)}",
            "",
        ]
        for wi in project.work_items:
            agent_badge = f"[{wi.agent}]"
            deps = f" → depends on: {', '.join(wi.depends_on)}" if wi.depends_on else ""
            writable = wi.scope.get("files_writable", [])
            scope_str = f" (writes: {', '.join(writable)})" if writable else ""
            lines.append(f"  **{wi.id}**: {wi.title} {agent_badge}{deps}{scope_str}")

        lines.append("")
        lines.append("⚠️ **Awaiting approval.** Reply with approval to execute this plan.")
        return "\n".join(lines)

    def _handle_approve(self, project_id: str = "", **kwargs: Any) -> str:
        if not project_id:
            # Auto-find the most recent planning project
            planning = [p for p in self._engineer.list_projects() if p.state == "planning"]
            if len(planning) == 1:
                project_id = planning[0].id
            elif not planning:
                return "Error: No projects awaiting approval"
            else:
                ids = ", ".join(p.id for p in planning)
                return f"Error: Multiple projects awaiting approval. Specify project_id: {ids}"

        return self._engineer.approve_project(project_id)

    async def _handle_run(self, project_id: str = "", **kwargs: Any) -> str:
        if not project_id:
            # Auto-find the most recent approved project
            approved = [p for p in self._engineer.list_projects()
                        if p.state in ("approved", "running")]
            if len(approved) == 1:
                project_id = approved[0].id
            elif not approved:
                return "Error: No approved projects to run. Use 'approve' first."
            else:
                ids = ", ".join(p.id for p in approved)
                return f"Error: Multiple runnable projects. Specify project_id: {ids}"

        return await self._engineer.dispatch_ready(project_id)

    def _handle_status(self, project_id: str = "", **kwargs: Any) -> str:
        if not project_id:
            # Show status of most recent active project
            active = [p for p in self._engineer.list_projects()
                      if p.state in ("running", "approved", "planning")]
            if active:
                project_id = active[-1].id
            else:
                all_projects = self._engineer.list_projects()
                if all_projects:
                    project_id = all_projects[-1].id
                else:
                    return "No projects found."

        return self._engineer.get_status(project_id)

    async def _handle_cancel(self, project_id: str = "", **kwargs: Any) -> str:
        if not project_id:
            running = [p for p in self._engineer.list_projects() if p.state == "running"]
            if len(running) == 1:
                project_id = running[0].id
            elif not running:
                return "No running projects to cancel."
            else:
                ids = ", ".join(p.id for p in running)
                return f"Error: Multiple running projects. Specify project_id: {ids}"

        return await self._engineer.cancel_project(project_id)

    def _handle_list(self) -> str:
        projects = self._engineer.list_projects()
        if not projects:
            return "No projects found."

        lines = ["**Projects:**"]
        for p in sorted(projects, key=lambda x: x.created_at, reverse=True):
            done = sum(1 for wi in p.work_items if wi.state == "done")
            total = len(p.work_items)
            icon = {"planning": "📋", "approved": "✅", "running": "🔄",
                    "done": "🎉", "failed": "❌"}.get(p.state, "❓")
            lines.append(f"  {icon} `{p.id}` **{p.title}** — {p.state} ({done}/{total})")
        return "\n".join(lines)
