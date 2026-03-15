"""Research tool: multi-source search, Obsidian KB indexing, bookmark crawling."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.config.schema import ResearchConfig


class ResearchTool(Tool):
    """Multi-source research: search, deep dive, knowledge base, and bookmarks."""

    def __init__(self, config: ResearchConfig, workspace: Path,
                 brave_api_key: str | None = None, web_proxy: str | None = None):
        from nanobot.config.schema import ResearchConfig as _RC
        self._config = config or _RC()
        self._workspace = workspace
        self._research_dir = workspace / "research"
        self._research_dir.mkdir(parents=True, exist_ok=True)
        self._results_dir = self._research_dir / "results"
        self._results_dir.mkdir(parents=True, exist_ok=True)
        self._brave_api_key = brave_api_key
        self._web_proxy = web_proxy
        self._vault_path = Path(self._config.obsidian_vault_path).expanduser()

    @property
    def name(self) -> str:
        return "research"

    @property
    def description(self) -> str:
        return (
            "Multi-source research and knowledge management. Operations:\n"
            "- search: Query multiple sources (Brave, Exa, Grok, Gemini) in parallel, return consolidated results\n"
            "- deep_dive: Iterative multi-round search with consolidation\n"
            "- query_kb: Search the Obsidian knowledge base for existing notes\n"
            "- index: Save content as a .md note in the Obsidian vault with YAML frontmatter\n"
            "- list_notes: List recent notes in the knowledge base\n"
            "- read_note: Read a specific note from the vault\n"
            "- crawl_bookmarks: Process Twitter bookmarks into vault notes (requires twitter agent)"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["search", "deep_dive", "query_kb", "index",
                             "list_notes", "read_note", "crawl_bookmarks"],
                    "description": "The research operation to perform.",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (for search, deep_dive, query_kb).",
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Sources to search: brave, exa, grok, gemini. Default: all configured.",
                },
                "title": {
                    "type": "string",
                    "description": "Note title (for index).",
                },
                "content": {
                    "type": "string",
                    "description": "Note content in markdown (for index).",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for the note (for index).",
                },
                "source_url": {
                    "type": "string",
                    "description": "Source URL for the note (for index).",
                },
                "note_path": {
                    "type": "string",
                    "description": "Relative path within vault (for read_note).",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results per source (default 5).",
                },
                "rounds": {
                    "type": "integer",
                    "description": "Number of search rounds for deep_dive (default 3).",
                },
            },
            "required": ["operation"],
        }

    async def execute(self, operation: str, **kwargs: Any) -> str:
        if operation == "search":
            return await self._search(kwargs.get("query", ""), kwargs.get("sources"),
                                      kwargs.get("max_results", 5))
        elif operation == "deep_dive":
            return await self._deep_dive(kwargs.get("query", ""), kwargs.get("rounds", 3),
                                         kwargs.get("max_results", 5))
        elif operation == "query_kb":
            return self._query_kb(kwargs.get("query", ""))
        elif operation == "index":
            return self._index_note(kwargs.get("title", ""), kwargs.get("content", ""),
                                    kwargs.get("tags", []), kwargs.get("source_url", ""))
        elif operation == "list_notes":
            return self._list_notes()
        elif operation == "read_note":
            return self._read_note(kwargs.get("note_path", ""))
        elif operation == "crawl_bookmarks":
            return "Use the twitter tool to fetch bookmarks first: twitter(operation='bookmarks'), " \
                   "then index each one: research(operation='index', title='...', content='...', tags=[...])"
        return f"Unknown operation: {operation}"

    # ── Multi-source search ──────────────────────────────────────

    async def _search(self, query: str, sources: list[str] | None = None,
                      max_results: int = 5) -> str:
        if not query:
            return "Error: query is required."

        available = self._available_sources()
        use_sources = sources or list(available.keys())
        use_sources = [s for s in use_sources if s in available]

        if not use_sources:
            return "No search sources configured. Set API keys in config (brave, exa, grok, gemini)."

        # Fan out searches in parallel
        tasks = {}
        for src in use_sources:
            tasks[src] = asyncio.create_task(self._search_source(src, query, max_results))

        results: dict[str, list[dict]] = {}
        for src, task in tasks.items():
            try:
                results[src] = await task
            except Exception as e:
                results[src] = [{"error": str(e)}]

        # Save raw results
        result_file = self._results_dir / f"search-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        result_file.write_text(json.dumps({
            "query": query,
            "timestamp": datetime.now().isoformat(),
            "sources": use_sources,
            "results": results,
        }, indent=2, default=str))

        # Format for LLM
        lines = [f"Search results for: \"{query}\"\n"]
        total = 0
        for src, items in results.items():
            lines.append(f"\n### {src.upper()} ({len(items)} results)")
            for item in items:
                if "error" in item:
                    lines.append(f"  Error: {item['error']}")
                    continue
                total += 1
                title = item.get("title", "")
                url = item.get("url", "")
                snippet = item.get("snippet", "")[:200]
                lines.append(f"  - **{title}**")
                if url:
                    lines.append(f"    {url}")
                if snippet:
                    lines.append(f"    {snippet}")

        lines.append(f"\nTotal: {total} results from {len(use_sources)} source(s).")
        lines.append("Use research(operation='index', ...) to save important findings to the knowledge base.")
        return "\n".join(lines)

    async def _deep_dive(self, query: str, rounds: int = 3, max_results: int = 5) -> str:
        if not query:
            return "Error: query is required."

        all_results: list[str] = []
        current_query = query

        for i in range(rounds):
            result = await self._search(current_query, max_results=max_results)
            all_results.append(f"\n--- Round {i+1}: \"{current_query}\" ---\n{result}")

            # Generate follow-up queries by extracting key terms from results
            # The LLM will handle the actual query refinement in practice
            if i < rounds - 1:
                current_query = f"{query} (round {i+2}, deeper analysis)"

        return "\n".join(all_results) + \
            f"\n\nDeep dive complete: {rounds} rounds. Synthesize the findings above."

    async def _search_source(self, source: str, query: str, max_results: int) -> list[dict]:
        """Search a single source. Returns list of result dicts."""
        if source == "brave":
            return await self._search_brave(query, max_results)
        elif source == "exa":
            return await self._search_exa(query, max_results)
        elif source == "grok":
            return await self._search_openai_compat(query, max_results,
                                                     api_key=self._config.grok_api_key,
                                                     base_url="https://api.x.ai/v1",
                                                     model="grok-3-mini")
        elif source == "gemini":
            return await self._search_openai_compat(query, max_results,
                                                     api_key=self._config.gemini_api_key,
                                                     base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                                                     model="gemini-2.0-flash")
        return [{"error": f"Unknown source: {source}"}]

    async def _search_brave(self, query: str, max_results: int) -> list[dict]:
        """Search via Brave Search API."""
        import httpx
        if not self._brave_api_key:
            return [{"error": "Brave API key not configured"}]
        async with httpx.AsyncClient(proxy=self._web_proxy) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results},
                headers={"X-Subscription-Token": self._brave_api_key, "Accept": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        results = []
        for item in data.get("web", {}).get("results", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
            })
        return results

    async def _search_exa(self, query: str, max_results: int) -> list[dict]:
        """Search via Exa API."""
        if not self._config.exa_api_key:
            return [{"error": "Exa API key not configured"}]
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.exa.ai/search",
                json={"query": query, "num_results": max_results, "use_autoprompt": True},
                headers={"x-api-key": self._config.exa_api_key, "Content-Type": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        results = []
        for item in data.get("results", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("text", "")[:300] if item.get("text") else "",
            })
        return results

    async def _search_openai_compat(self, query: str, max_results: int,
                                     api_key: str, base_url: str, model: str) -> list[dict]:
        """Search via an OpenAI-compatible API (Grok, Gemini, etc.)."""
        if not api_key:
            return [{"error": f"API key not configured for {model}"}]
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a research assistant. Return search results as a JSON array of objects with 'title', 'url' (if available), and 'snippet' fields. Be factual and concise."},
                        {"role": "user", "content": f"Search for: {query}\nReturn up to {max_results} relevant results."},
                    ],
                    "max_tokens": 1000,
                    "temperature": 0.3,
                },
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        # Try to parse JSON from the response
        try:
            # Find JSON array in response
            start = content.find("[")
            end = content.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])[:max_results]
        except (json.JSONDecodeError, ValueError):
            pass
        # Fallback: return as a single result
        return [{"title": f"{model} response", "snippet": content[:500]}]

    def _available_sources(self) -> dict[str, bool]:
        """Return dict of source_name → is_configured."""
        sources = {}
        if self._brave_api_key:
            sources["brave"] = True
        if self._config.exa_api_key:
            sources["exa"] = True
        if self._config.grok_api_key:
            sources["grok"] = True
        if self._config.gemini_api_key:
            sources["gemini"] = True
        return sources

    # ── Obsidian Knowledge Base ──────────────────────────────────

    def _query_kb(self, query: str) -> str:
        """Search the Obsidian vault for notes matching the query."""
        if not query:
            return "Error: query is required."
        if not self._vault_path.exists():
            return f"Vault not found at {self._vault_path}. Set research.obsidian_vault_path in config."

        terms = query.lower().split()
        matches = []
        for md_file in self._vault_path.rglob("*.md"):
            try:
                content = md_file.read_text(errors="replace")
                content_lower = content.lower()
                score = sum(1 for t in terms if t in content_lower)
                if score > 0:
                    # Extract first few lines as preview
                    lines = [l for l in content.split("\n") if l.strip()][:3]
                    preview = " ".join(lines)[:200]
                    rel_path = md_file.relative_to(self._vault_path)
                    matches.append((score, str(rel_path), preview))
            except Exception:
                continue

        matches.sort(key=lambda x: -x[0])
        if not matches:
            return f"No notes matching '{query}' in vault."

        lines = [f"Found {len(matches)} note(s) matching '{query}':\n"]
        for score, path, preview in matches[:15]:
            lines.append(f"  - **{path}** (score: {score})")
            lines.append(f"    {preview}")
        return "\n".join(lines)

    def _index_note(self, title: str, content: str, tags: list[str] | None = None,
                    source_url: str = "") -> str:
        """Save content as a .md note in the Obsidian vault."""
        if not title or not content:
            return "Error: title and content are required."
        if not self._vault_path.exists():
            self._vault_path.mkdir(parents=True, exist_ok=True)

        # Build YAML frontmatter
        frontmatter_lines = ["---"]
        frontmatter_lines.append(f"title: \"{title}\"")
        frontmatter_lines.append(f"date: {datetime.now().strftime('%Y-%m-%d')}")
        if tags:
            frontmatter_lines.append(f"tags: [{', '.join(tags)}]")
        if source_url:
            frontmatter_lines.append(f"source: \"{source_url}\"")
        frontmatter_lines.append(f"indexed_at: {datetime.now().isoformat()}")
        frontmatter_lines.append("---")
        frontmatter = "\n".join(frontmatter_lines)

        # Sanitize title for filename
        safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
        safe_title = safe_title.strip()[:80]
        filename = f"{safe_title}.md"

        # Write to vault (NexusBot subfolder)
        note_dir = self._vault_path / "NexusBot"
        note_dir.mkdir(parents=True, exist_ok=True)
        note_path = note_dir / filename

        # Avoid overwriting
        if note_path.exists():
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"{safe_title}-{timestamp}.md"
            note_path = note_dir / filename

        note_path.write_text(f"{frontmatter}\n\n{content}")
        rel = note_path.relative_to(self._vault_path)
        return f"Indexed note: {rel} ({len(content)} chars)"

    def _list_notes(self) -> str:
        """List recent notes in the NexusBot vault folder."""
        note_dir = self._vault_path / "NexusBot"
        if not note_dir.exists():
            return "No notes yet. Use research(operation='index') to create one."

        notes = sorted(note_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not notes:
            return "No notes in vault."

        lines = [f"{len(notes)} note(s) in NexusBot vault:\n"]
        for n in notes[:20]:
            size = n.stat().st_size
            mtime = datetime.fromtimestamp(n.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  - {n.name} ({size}B, {mtime})")
        return "\n".join(lines)

    def _read_note(self, note_path: str) -> str:
        """Read a specific note from the vault."""
        if not note_path:
            return "Error: note_path is required (relative to vault root)."
        full_path = self._vault_path / note_path
        if not full_path.exists():
            # Try in NexusBot subfolder
            full_path = self._vault_path / "NexusBot" / note_path
        if not full_path.exists():
            return f"Note not found: {note_path}"
        content = full_path.read_text(errors="replace")
        return content[:10000]
