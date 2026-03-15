"""Base class for specialized agents (Engineer, TwitterAgent, etc.)."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus


class SpecializedAgent(ABC):
    """
    Abstract base class for specialized agents.

    Provides shared patterns: state persistence to JSON, workspace directory,
    dashboard notification, and message bus access.
    """

    def __init__(self, name: str, workspace: Path, bus: MessageBus):
        self._name = name
        self.workspace = workspace
        self.bus = bus
        self._workspace_dir = workspace / name
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        self._state: dict[str, Any] = {}
        self._dashboard: Any | None = None
        self.load_state()

    @property
    def name(self) -> str:
        return self._name

    @property
    def workspace_dir(self) -> Path:
        return self._workspace_dir

    @property
    def state_file(self) -> Path:
        return self._workspace_dir / "state.json"

    def get_state(self) -> dict[str, Any]:
        """Return the agent's current state."""
        return {"name": self._name, "workspace": str(self._workspace_dir), **self._state}

    def save_state(self) -> None:
        """Persist agent state to disk."""
        self.state_file.write_text(json.dumps(self._state, indent=2, default=str))

    def load_state(self) -> None:
        """Load agent state from disk."""
        if self.state_file.exists():
            try:
                self._state = json.loads(self.state_file.read_text())
            except Exception as e:
                logger.warning("Failed to load state for {}: {}", self._name, e)

    async def notify_dashboard(self, event_type: str, data: dict | None = None) -> None:
        """Notify the dashboard of a state change."""
        if self._dashboard and hasattr(self._dashboard, "_broadcast"):
            try:
                await self._dashboard._broadcast({
                    "type": event_type,
                    "agent": self._name,
                    **(data or {}),
                })
            except Exception:
                pass

    @abstractmethod
    async def execute(self, operation: str, **kwargs: Any) -> str:
        """Execute an agent operation. Subclasses must implement."""
        pass

    @abstractmethod
    def status_summary(self) -> str:
        """Return a short status summary for the agent registry."""
        pass
