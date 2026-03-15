"""GitHub scanning tool: trending repos, deep analysis, Product Hunt, repo scaffolding."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.config.schema import GitHubAgentConfig


class GitHubScanTool(Tool):
    """Scan GitHub trending repos, analyze repos, scan Product Hunt, scaffold new repos."""

    def __init__(self, config: GitHubAgentConfig, workspace: Path, web_proxy: str | None = None):
        from nanobot.config.schema import GitHubAgentConfig as _GC
        self._config = config or _GC()
        self._workspace = workspace
        self._scan_dir = workspace / "github_agent"
        self._scan_dir.mkdir(parents=True, exist_ok=True)
        self._insights_file = self._scan_dir / "insights.json"
        self._web_proxy = web_proxy

    @property
    def name(self) -> str:
        return "github_scan"

    @property
    def description(self) -> str:
        return (
            "GitHub and Product Hunt scanning. Operations:\n"
            "- trending: Scan GitHub trending repos (optionally filtered by language/since)\n"
            "- analyze_repo: Deep analysis of a specific repo (README, stats, tech stack)\n"
            "- scan_producthunt: Scrape Product Hunt trending products\n"
            "- search_repos: Search GitHub repos by query\n"
            "- get_insights: Get saved insights from past scans\n"
            "- save_insight: Save a pattern/insight from analysis\n"
            "- create_repo: Scaffold a new repo (creates plan for Engineer to execute)"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["trending", "analyze_repo", "scan_producthunt",
                             "search_repos", "get_insights", "save_insight", "create_repo"],
                    "description": "The operation to perform.",
                },
                "language": {
                    "type": "string",
                    "description": "Programming language filter for trending (e.g. 'python', 'typescript').",
                },
                "since": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly"],
                    "description": "Time range for trending (default: daily).",
                },
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/name format (for analyze_repo).",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (for search_repos).",
                },
                "insight": {
                    "type": "object",
                    "description": "Insight to save: {title, description, tags, repos}.",
                },
                "repo_plan": {
                    "type": "object",
                    "description": "Repo scaffold plan: {name, description, tech_stack, features}.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results (default 10).",
                },
            },
            "required": ["operation"],
        }

    async def execute(self, operation: str, **kwargs: Any) -> str:
        if operation == "trending":
            return await self._trending(kwargs.get("language", ""),
                                        kwargs.get("since", "daily"),
                                        kwargs.get("max_results", 10))
        elif operation == "analyze_repo":
            return await self._analyze_repo(kwargs.get("repo", ""))
        elif operation == "scan_producthunt":
            return await self._scan_producthunt(kwargs.get("max_results", 10))
        elif operation == "search_repos":
            return await self._search_repos(kwargs.get("query", ""),
                                            kwargs.get("max_results", 10))
        elif operation == "get_insights":
            return self._get_insights()
        elif operation == "save_insight":
            return self._save_insight(kwargs.get("insight", {}))
        elif operation == "create_repo":
            return self._create_repo(kwargs.get("repo_plan", {}))
        return f"Unknown operation: {operation}"

    async def _trending(self, language: str, since: str, max_results: int) -> str:
        """Scrape GitHub trending page."""
        import httpx
        url = "https://github.com/trending"
        if language:
            url += f"/{language}"
        url += f"?since={since}"

        async with httpx.AsyncClient(proxy=self._web_proxy, follow_redirects=True) as client:
            resp = await client.get(url, headers={"Accept": "text/html"}, timeout=15)
            resp.raise_for_status()
            html = resp.text

        repos = self._parse_trending_html(html, max_results)
        self._save_scan("trending", repos)

        if not repos:
            return "No trending repos found (parsing may have failed)."

        lines = [f"GitHub Trending ({since}{', ' + language if language else ''}) — {len(repos)} repos:\n"]
        for r in repos:
            stars = r.get("stars", "?")
            desc = r.get("description", "")[:120]
            lines.append(f"  - **{r['name']}** ({stars} stars)")
            if desc:
                lines.append(f"    {desc}")
        lines.append("\nUse github_scan(operation='analyze_repo', repo='owner/name') for deep analysis.")
        return "\n".join(lines)

    def _parse_trending_html(self, html: str, max_results: int) -> list[dict]:
        """Parse trending repos from GitHub HTML. Simple regex-based parser."""
        import re
        repos = []
        # Match repo links: /owner/name
        pattern = r'<h2[^>]*>\s*<a[^>]*href="/([^"]+)"[^>]*>'
        for match in re.finditer(pattern, html):
            repo_path = match.group(1).strip()
            if "/" not in repo_path or repo_path.count("/") != 1:
                continue
            if repo_path in [r["name"] for r in repos]:
                continue

            # Try to find description nearby
            desc = ""
            desc_match = re.search(
                rf'href="/{re.escape(repo_path)}".*?<p[^>]*>(.*?)</p>',
                html[match.start():match.start() + 2000], re.DOTALL)
            if desc_match:
                desc = re.sub(r'<[^>]+>', '', desc_match.group(1)).strip()

            # Try to find star count
            stars = ""
            star_match = re.search(
                rf'href="/{re.escape(repo_path)}/stargazers"[^>]*>([\d,]+)',
                html[match.start():match.start() + 3000])
            if star_match:
                stars = star_match.group(1).strip()

            repos.append({
                "name": repo_path,
                "description": desc[:200],
                "stars": stars,
                "url": f"https://github.com/{repo_path}",
            })
            if len(repos) >= max_results:
                break
        return repos

    async def _analyze_repo(self, repo: str) -> str:
        """Deep analysis of a GitHub repo via API."""
        if not repo or "/" not in repo:
            return "Error: repo must be in owner/name format."
        import httpx
        async with httpx.AsyncClient(proxy=self._web_proxy) as client:
            # Fetch repo metadata
            resp = await client.get(
                f"https://api.github.com/repos/{repo}",
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=15,
            )
            if resp.status_code == 404:
                return f"Repo not found: {repo}"
            resp.raise_for_status()
            data = resp.json()

            # Fetch README
            readme = ""
            try:
                readme_resp = await client.get(
                    f"https://api.github.com/repos/{repo}/readme",
                    headers={"Accept": "application/vnd.github.v3.raw"},
                    timeout=15,
                )
                if readme_resp.status_code == 200:
                    readme = readme_resp.text[:3000]
            except Exception:
                pass

            # Fetch languages
            langs = {}
            try:
                lang_resp = await client.get(
                    f"https://api.github.com/repos/{repo}/languages",
                    headers={"Accept": "application/vnd.github.v3+json"},
                    timeout=10,
                )
                if lang_resp.status_code == 200:
                    langs = lang_resp.json()
            except Exception:
                pass

        lines = [
            f"## {data.get('full_name', repo)}",
            f"**Description:** {data.get('description', 'N/A')}",
            f"**Stars:** {data.get('stargazers_count', 0):,} | **Forks:** {data.get('forks_count', 0):,}",
            f"**Language:** {data.get('language', 'N/A')}",
            f"**Created:** {data.get('created_at', '?')[:10]} | **Updated:** {data.get('updated_at', '?')[:10]}",
            f"**License:** {data.get('license', {}).get('spdx_id', 'None') if data.get('license') else 'None'}",
            f"**Topics:** {', '.join(data.get('topics', [])) or 'none'}",
            f"**Open Issues:** {data.get('open_issues_count', 0)}",
            f"**URL:** {data.get('html_url', '')}",
        ]

        if langs:
            total = sum(langs.values())
            lang_str = ", ".join(f"{k} ({v * 100 // total}%)" for k, v in
                                sorted(langs.items(), key=lambda x: -x[1])[:5])
            lines.append(f"**Tech Stack:** {lang_str}")

        if readme:
            lines.append(f"\n### README (first 3000 chars)\n{readme}")

        return "\n".join(lines)

    async def _scan_producthunt(self, max_results: int) -> str:
        """Scan Product Hunt trending. Product Hunt is JS-rendered, so static
        scraping is unreliable. Use gstack's /browse skill for best results:
            exec('~/.claude/skills/gstack/browse/dist/browse goto https://www.producthunt.com')
            exec('~/.claude/skills/gstack/browse/dist/browse text')
        """
        import httpx
        async with httpx.AsyncClient(proxy=self._web_proxy, follow_redirects=True) as client:
            resp = await client.get("https://www.producthunt.com",
                                    headers={"Accept": "text/html",
                                             "User-Agent": "Mozilla/5.0"},
                                    timeout=15)
            if resp.status_code != 200:
                return f"Failed to fetch Product Hunt (HTTP {resp.status_code}). Try using web_fetch instead."
            html = resp.text

        # Simple extraction of product names from HTML (fragile — PH is JS-rendered)
        import re
        products = []
        for match in re.finditer(r'data-test="post-name[^"]*"[^>]*>([^<]+)', html):
            name = match.group(1).strip()
            if name and name not in [p["name"] for p in products]:
                products.append({"name": name})
                if len(products) >= max_results:
                    break

        if not products:
            return ("Could not parse Product Hunt page (JS-rendered content).\n"
                    "Use the exec tool with gstack browse for reliable results:\n"
                    "  exec('B=~/.claude/skills/gstack/browse/dist/browse && "
                    "$B goto https://www.producthunt.com && $B text')")

        self._save_scan("producthunt", products)
        lines = [f"Product Hunt Trending ({len(products)} products):\n"]
        for p in products:
            lines.append(f"  - {p['name']}")
        return "\n".join(lines)

    async def _search_repos(self, query: str, max_results: int) -> str:
        """Search GitHub repos via API."""
        if not query:
            return "Error: query is required."
        import httpx
        async with httpx.AsyncClient(proxy=self._web_proxy) as client:
            resp = await client.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "sort": "stars", "per_page": max_results},
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

        items = data.get("items", [])
        if not items:
            return f"No repos found for: {query}"

        lines = [f"GitHub search: \"{query}\" ({data.get('total_count', 0)} total, showing {len(items)}):\n"]
        for r in items:
            desc = (r.get("description") or "")[:100]
            lines.append(f"  - **{r['full_name']}** ({r.get('stargazers_count', 0):,} stars, {r.get('language', '?')})")
            if desc:
                lines.append(f"    {desc}")
        return "\n".join(lines)

    def _save_scan(self, scan_type: str, data: list[dict]) -> None:
        scan_file = self._scan_dir / f"{scan_type}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        scan_file.write_text(json.dumps({
            "type": scan_type,
            "timestamp": datetime.now().isoformat(),
            "count": len(data),
            "items": data,
        }, indent=2, default=str))

    def _get_insights(self) -> str:
        if not self._insights_file.exists():
            return "No insights saved yet. Use save_insight after analyzing trends."
        insights = json.loads(self._insights_file.read_text())
        if not insights:
            return "No insights saved."
        lines = [f"{len(insights)} insight(s):\n"]
        for i in insights:
            lines.append(f"  - **{i.get('title', '?')}**")
            if i.get("description"):
                lines.append(f"    {i['description'][:150]}")
            if i.get("tags"):
                lines.append(f"    Tags: {', '.join(i['tags'])}")
        return "\n".join(lines)

    def _save_insight(self, insight: dict) -> str:
        if not insight or not insight.get("title"):
            return "Error: insight object with 'title' is required."
        insights = []
        if self._insights_file.exists():
            try:
                insights = json.loads(self._insights_file.read_text())
            except Exception:
                pass
        insight["saved_at"] = datetime.now().isoformat()
        insights.append(insight)
        self._insights_file.write_text(json.dumps(insights, indent=2, default=str))
        return f"Insight saved: {insight['title']}"

    def _create_repo(self, plan: dict) -> str:
        if not plan or not plan.get("name"):
            return "Error: repo_plan with 'name' is required. Include: name, description, tech_stack, features."
        # Save the plan for the Engineer to execute
        plan_file = self._scan_dir / f"repo-plan-{plan['name']}.json"
        plan["created_at"] = datetime.now().isoformat()
        plan_file.write_text(json.dumps(plan, indent=2, default=str))
        return (
            f"Repo plan saved: {plan['name']}\n"
            f"Description: {plan.get('description', 'N/A')}\n"
            f"Tech stack: {plan.get('tech_stack', 'N/A')}\n"
            f"To scaffold, use the dispatch tool to create an Engineer project from this plan."
        )
