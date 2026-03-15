"""Allow running as `python -m nanobot.playwright_mcp`."""

from nanobot.playwright_mcp.server import mcp

mcp.run(transport="stdio")
