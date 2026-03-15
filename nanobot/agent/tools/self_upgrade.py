"""Self-upgrade tool: check, pull, test, restart nanobot from upstream."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


class SelfUpgradeTool(Tool):
    """Allows the agent to check for updates, pull upstream changes, run tests, and restart."""

    def __init__(self, repo_dir: str | None = None):
        # Default: the nanobot repo root (three levels up from nanobot/agent/tools/self_upgrade.py)
        self._repo_dir = Path(repo_dir) if repo_dir else Path(__file__).resolve().parents[3]

    @property
    def name(self) -> str:
        return "self_upgrade"

    @property
    def description(self) -> str:
        return (
            "Manage nanobot self-upgrades. Operations: "
            "check (show pending upstream commits), "
            "pull (create backup branch then merge upstream/main), "
            "test (run pytest), "
            "restart (exit process — launchd auto-restarts), "
            "status (current commit + upstream delta)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["check", "pull", "test", "restart", "status"],
                    "description": "The upgrade operation to perform.",
                },
            },
            "required": ["operation"],
        }

    async def execute(self, operation: str, **kwargs: Any) -> str:
        repo = self._repo_dir
        if not (repo / ".git").exists():
            return f"Error: {repo} is not a git repository."

        if operation == "status":
            return await self._status(repo)
        elif operation == "check":
            return await self._check(repo)
        elif operation == "pull":
            return await self._pull(repo)
        elif operation == "test":
            return await self._test(repo)
        elif operation == "restart":
            return self._restart()
        else:
            return f"Unknown operation: {operation}"

    async def _exec(self, cmd: str, cwd: Path, timeout: int = 30) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return -1, "", "Command timed out"
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace").strip(),
            stderr.decode("utf-8", errors="replace").strip(),
        )

    async def _status(self, repo: Path) -> str:
        rc, commit, _ = await self._exec("git rev-parse --short HEAD", repo)
        if rc != 0:
            return "Error: could not get current commit."
        rc, branch, _ = await self._exec("git rev-parse --abbrev-ref HEAD", repo)
        rc, remote_info, _ = await self._exec("git remote -v", repo)

        # Try to get upstream delta
        await self._exec("git fetch origin --quiet", repo, timeout=15)
        rc, ahead_behind, _ = await self._exec(
            "git rev-list --left-right --count HEAD...origin/main 2>/dev/null", repo
        )
        delta = ""
        if rc == 0 and ahead_behind.strip():
            parts = ahead_behind.split()
            if len(parts) == 2:
                ahead, behind = parts
                delta = f"\nAhead: {ahead}, Behind: {behind} (vs origin/main)"

        return f"Commit: {commit}\nBranch: {branch}{delta}\nRemotes:\n{remote_info}"

    async def _check(self, repo: Path) -> str:
        rc, _, err = await self._exec("git fetch origin --quiet", repo, timeout=15)
        if rc != 0:
            return f"Error fetching: {err}"

        rc, log, _ = await self._exec(
            "git log --oneline HEAD..origin/main 2>/dev/null", repo
        )
        if rc != 0 or not log.strip():
            return "Already up to date — no pending upstream commits."
        count = len(log.strip().split("\n"))
        return f"{count} pending upstream commit(s):\n{log}"

    async def _pull(self, repo: Path) -> str:
        # Create backup branch
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_branch = f"backup/pre-upgrade-{timestamp}"
        rc, _, err = await self._exec(f'git branch "{backup_branch}"', repo)
        if rc != 0:
            return f"Error creating backup branch: {err}"

        # Fetch latest
        rc, _, err = await self._exec("git fetch origin --quiet", repo, timeout=15)
        if rc != 0:
            return f"Error fetching: {err}"

        # Merge
        rc, out, err = await self._exec("git merge origin/main --no-edit", repo, timeout=30)
        if rc != 0:
            # Revert on failure
            await self._exec("git merge --abort", repo)
            return f"Merge failed (reverted). Backup branch: {backup_branch}\nError: {err}"

        # Log the upgrade
        history_line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] SELF-UPGRADE: merged origin/main (backup: {backup_branch})\n"
        history_file = repo / "HISTORY.md"
        try:
            with open(history_file, "a") as f:
                f.write(history_line)
        except Exception:
            pass

        logger.info("Self-upgrade: merged origin/main (backup: {})", backup_branch)
        return f"Merged origin/main successfully.\nBackup branch: {backup_branch}\n{out}"

    async def _test(self, repo: Path) -> str:
        rc, out, err = await self._exec("python -m pytest tests/ -x -q 2>&1", repo, timeout=120)
        combined = (out + "\n" + err).strip()
        if rc != 0:
            return f"Tests FAILED (rc={rc}):\n{combined[-2000:]}"
        return f"Tests passed:\n{combined[-1000:]}"

    def _restart(self) -> str:
        logger.info("Self-upgrade: restarting (sys.exit(0), launchd will auto-restart)")
        # Schedule exit after returning the response
        import threading
        threading.Timer(1.0, lambda: sys.exit(0)).start()
        return "Restarting nanobot in 1 second... (launchd KeepAlive will auto-restart the process)"
