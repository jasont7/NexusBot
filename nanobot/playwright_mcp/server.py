"""Playwright MCP server — stdio-based browser automation for nanobot.

Run standalone:
    python -m nanobot.playwright_mcp.server

Or configure in config.json:
    "mcp_servers": {
        "browser": {
            "command": "python",
            "args": ["-m", "nanobot.playwright_mcp.server"]
        }
    }
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
from pathlib import Path

from mcp.server import FastMCP

# Persistent user-data directory for cookies/localStorage
_USER_DATA_DIR = os.environ.get(
    "PLAYWRIGHT_USER_DATA",
    str(Path.home() / ".nanobot" / "workspace" / "browser" / "user-data"),
)
_HEADLESS = os.environ.get("PLAYWRIGHT_HEADLESS", "1") != "0"

mcp = FastMCP(
    "nanobot-browser",
    instructions="Browser automation via Playwright. Navigate pages, click elements, type text, take screenshots, and extract content.",
)

# ── Shared browser state ──────────────────────────────────────────

_browser = None
_context = None
_page = None


async def _ensure_page():
    """Lazy-init: launch browser with persistent context, return the active page."""
    global _browser, _context, _page
    if _page and not _page.is_closed():
        return _page

    from playwright.async_api import async_playwright

    pw = await async_playwright().start()

    Path(_USER_DATA_DIR).mkdir(parents=True, exist_ok=True)

    _context = await pw.chromium.launch_persistent_context(
        user_data_dir=_USER_DATA_DIR,
        headless=_HEADLESS,
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        ignore_https_errors=True,
    )
    _browser = _context.browser
    _page = _context.pages[0] if _context.pages else await _context.new_page()
    return _page


# ── MCP Tools ─────────────────────────────────────────────────────


@mcp.tool()
async def navigate(url: str, wait_until: str = "domcontentloaded") -> str:
    """Navigate to a URL. Returns the page title and URL after navigation.

    Args:
        url: The URL to navigate to.
        wait_until: When to consider navigation complete: 'load', 'domcontentloaded', 'networkidle'.
    """
    page = await _ensure_page()
    resp = await page.goto(url, wait_until=wait_until, timeout=30000)
    status = resp.status if resp else "unknown"
    return json.dumps({
        "url": page.url,
        "title": await page.title(),
        "status": status,
    })


@mcp.tool()
async def click(selector: str) -> str:
    """Click an element matching the CSS selector.

    Args:
        selector: CSS selector for the element to click.
    """
    page = await _ensure_page()
    await page.click(selector, timeout=10000)
    await page.wait_for_load_state("domcontentloaded", timeout=5000)
    return json.dumps({
        "clicked": selector,
        "url": page.url,
        "title": await page.title(),
    })


@mcp.tool()
async def type_text(selector: str, text: str, press_enter: bool = False) -> str:
    """Type text into an input element.

    Args:
        selector: CSS selector for the input element.
        text: Text to type.
        press_enter: Whether to press Enter after typing.
    """
    page = await _ensure_page()
    await page.fill(selector, text, timeout=10000)
    if press_enter:
        await page.press(selector, "Enter")
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
    return json.dumps({
        "typed": text,
        "selector": selector,
        "url": page.url,
    })


@mcp.tool()
async def screenshot(full_page: bool = False, selector: str | None = None) -> str:
    """Take a screenshot of the current page or a specific element.

    Args:
        full_page: Capture the full scrollable page (default: viewport only).
        selector: Optional CSS selector to screenshot a specific element.
    """
    page = await _ensure_page()

    # Save to temp file and return base64
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name

    if selector:
        element = await page.query_selector(selector)
        if not element:
            return json.dumps({"error": f"Element not found: {selector}"})
        await element.screenshot(path=path)
    else:
        await page.screenshot(path=path, full_page=full_page)

    data = Path(path).read_bytes()
    Path(path).unlink(missing_ok=True)

    return json.dumps({
        "screenshot": base64.b64encode(data).decode(),
        "format": "png",
        "url": page.url,
        "title": await page.title(),
        "size_bytes": len(data),
    })


@mcp.tool()
async def extract_content(selector: str = "body", content_type: str = "text") -> str:
    """Extract text or HTML content from the page.

    Args:
        selector: CSS selector for the element to extract from (default: body).
        content_type: 'text' for inner text, 'html' for inner HTML.
    """
    page = await _ensure_page()
    element = await page.query_selector(selector)
    if not element:
        return json.dumps({"error": f"Element not found: {selector}"})

    if content_type == "html":
        content = await element.inner_html()
    else:
        content = await element.inner_text()

    # Truncate to avoid huge responses
    max_len = 50000
    truncated = len(content) > max_len
    content = content[:max_len]

    return json.dumps({
        "content": content,
        "selector": selector,
        "content_type": content_type,
        "truncated": truncated,
        "url": page.url,
    })


@mcp.tool()
async def scroll(direction: str = "down", amount: int = 500) -> str:
    """Scroll the page.

    Args:
        direction: 'up' or 'down'.
        amount: Pixels to scroll (default: 500).
    """
    page = await _ensure_page()
    delta = amount if direction == "down" else -amount
    await page.mouse.wheel(0, delta)
    await asyncio.sleep(0.5)

    scroll_y = await page.evaluate("window.scrollY")
    scroll_height = await page.evaluate("document.documentElement.scrollHeight")
    viewport_height = await page.evaluate("window.innerHeight")

    return json.dumps({
        "direction": direction,
        "amount": amount,
        "scroll_y": scroll_y,
        "scroll_height": scroll_height,
        "viewport_height": viewport_height,
        "at_bottom": scroll_y + viewport_height >= scroll_height - 10,
    })


@mcp.tool()
async def wait_for_selector(selector: str, state: str = "visible", timeout_ms: int = 10000) -> str:
    """Wait for an element to appear on the page.

    Args:
        selector: CSS selector to wait for.
        state: 'attached', 'detached', 'visible', or 'hidden'.
        timeout_ms: Maximum time to wait in milliseconds.
    """
    page = await _ensure_page()
    try:
        await page.wait_for_selector(selector, state=state, timeout=timeout_ms)
        return json.dumps({"found": True, "selector": selector, "state": state})
    except Exception as e:
        return json.dumps({"found": False, "selector": selector, "error": str(e)})


@mcp.tool()
async def get_cookies(url: str | None = None) -> str:
    """Get browser cookies, optionally filtered by URL.

    Args:
        url: Optional URL to filter cookies for.
    """
    page = await _ensure_page()
    ctx = page.context
    if url:
        cookies = await ctx.cookies(url)
    else:
        cookies = await ctx.cookies()

    # Summarize cookies (don't leak full values by default)
    summary = []
    for c in cookies:
        summary.append({
            "name": c["name"],
            "domain": c["domain"],
            "path": c["path"],
            "expires": c.get("expires", -1),
            "httpOnly": c.get("httpOnly", False),
            "secure": c.get("secure", False),
            "value_length": len(c.get("value", "")),
        })
    return json.dumps({"count": len(summary), "cookies": summary})


@mcp.tool()
async def set_cookies(cookies: list[dict]) -> str:
    """Set browser cookies.

    Args:
        cookies: List of cookie objects with keys: name, value, domain (or url), path.
    """
    page = await _ensure_page()
    ctx = page.context
    await ctx.add_cookies(cookies)
    return json.dumps({"set": len(cookies)})


@mcp.tool()
async def evaluate_js(expression: str) -> str:
    """Evaluate a JavaScript expression in the page context and return the result.

    Args:
        expression: JavaScript expression to evaluate.
    """
    page = await _ensure_page()
    try:
        result = await page.evaluate(expression)
        return json.dumps({"result": result}, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def page_info() -> str:
    """Get current page information: URL, title, viewport size."""
    page = await _ensure_page()
    return json.dumps({
        "url": page.url,
        "title": await page.title(),
        "viewport": page.viewport_size,
    })


# ── Entry point ───────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
