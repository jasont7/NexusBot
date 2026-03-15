"""Agent registry for managing specialized agents."""

from __future__ import annotations

from typing import Any

from loguru import logger

from nanobot.agent.specialized import SpecializedAgent


class AgentRegistry:
    """Registry for specialized agents (Engineer, TwitterAgent, etc.)."""

    def __init__(self) -> None:
        self._agents: dict[str, SpecializedAgent] = {}

    def register(self, agent: SpecializedAgent) -> None:
        """Register a specialized agent."""
        self._agents[agent.name] = agent
        logger.info("Registered agent: {}", agent.name)

    def unregister(self, name: str) -> None:
        """Remove an agent from the registry."""
        if name in self._agents:
            del self._agents[name]

    def get(self, name: str) -> SpecializedAgent | None:
        """Get an agent by name."""
        return self._agents.get(name)

    def list(self) -> list[str]:
        """List all registered agent names."""
        return list(self._agents.keys())

    def all(self) -> dict[str, SpecializedAgent]:
        """Return all registered agents."""
        return dict(self._agents)

    def status(self) -> list[dict[str, Any]]:
        """Get status of all registered agents."""
        return [
            {
                "name": agent.name,
                "workspace": str(agent.workspace_dir),
                "summary": agent.status_summary(),
            }
            for agent in self._agents.values()
        ]
