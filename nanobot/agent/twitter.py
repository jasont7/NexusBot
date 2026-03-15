"""Twitter/X agent: content scanning, tweet generation, style calibration, and posting."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.specialized import SpecializedAgent

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import TwitterConfig


class TwitterAgent(SpecializedAgent):
    """Manages Twitter content pipeline: scanning, drafting, approval, and posting."""

    def __init__(self, workspace: Path, bus: MessageBus, config: TwitterConfig):
        super().__init__(name="twitter", workspace=workspace, bus=bus)
        self.config = config
        self._queue_dir = self._workspace_dir / "queue"
        self._queue_dir.mkdir(parents=True, exist_ok=True)
        self._scans_dir = self._workspace_dir / "scans"
        self._scans_dir.mkdir(parents=True, exist_ok=True)
        self._style_file = self._workspace_dir / "STYLE.md"
        self._metrics_file = self._workspace_dir / "metrics.json"
        self._stories_file = self._workspace_dir / "stories.json"
        self._client: Any | None = None  # tweepy.Client, lazy

    def _get_client(self) -> Any:
        """Lazily initialize tweepy v2 client."""
        if self._client is not None:
            return self._client
        try:
            import tweepy
        except ImportError:
            raise RuntimeError("tweepy is not installed. Run: pip install tweepy>=4.14.0")
        c = self.config
        if not c.bearer_token and not c.api_key:
            raise RuntimeError("Twitter API credentials not configured (set twitter.bearer_token or twitter.api_key in config.json)")
        self._client = tweepy.Client(
            bearer_token=c.bearer_token or None,
            consumer_key=c.api_key or None,
            consumer_secret=c.api_secret or None,
            access_token=c.access_token or None,
            access_token_secret=c.access_secret or None,
            wait_on_rate_limit=True,
        )
        return self._client

    # ── Queue management ─────────────────────────────────────────

    def _queue_list(self) -> list[dict]:
        """List all queued tweet drafts sorted by creation time."""
        drafts = []
        for f in sorted(self._queue_dir.glob("*.json")):
            try:
                drafts.append(json.loads(f.read_text()))
            except Exception:
                pass
        return drafts

    def _queue_get(self, draft_id: str) -> dict | None:
        path = self._queue_dir / f"{draft_id}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def _queue_save(self, draft: dict) -> None:
        path = self._queue_dir / f"{draft['id']}.json"
        path.write_text(json.dumps(draft, indent=2, default=str))

    def _queue_delete(self, draft_id: str) -> bool:
        path = self._queue_dir / f"{draft_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def create_draft(self, text: str, reply_to: str | None = None,
                     source: str = "manual", metadata: dict | None = None) -> dict:
        """Create a new tweet draft in the queue."""
        draft = {
            "id": str(uuid.uuid4())[:8],
            "text": text,
            "reply_to": reply_to,
            "source": source,
            "state": "pending",  # pending | approved | posted | rejected
            "created_at": datetime.now().isoformat(),
            "posted_at": None,
            "tweet_id": None,
            "metadata": metadata or {},
        }
        self._queue_save(draft)
        return draft

    # ── Scan results ─────────────────────────────────────────────

    def save_scan(self, scan_type: str, data: list[dict]) -> str:
        """Save scan results to disk."""
        scan_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        scan_file = self._scans_dir / f"{scan_type}-{scan_id}.json"
        scan_file.write_text(json.dumps({
            "type": scan_type,
            "timestamp": datetime.now().isoformat(),
            "count": len(data),
            "items": data,
        }, indent=2, default=str))
        return str(scan_file)

    def get_latest_scan(self, scan_type: str) -> dict | None:
        """Get the most recent scan of a given type."""
        files = sorted(self._scans_dir.glob(f"{scan_type}-*.json"), reverse=True)
        if not files:
            return None
        return json.loads(files[0].read_text())

    # ── Stories ──────────────────────────────────────────────────

    def get_stories(self) -> list[dict]:
        if self._stories_file.exists():
            return json.loads(self._stories_file.read_text())
        return []

    def save_stories(self, stories: list[dict]) -> None:
        self._stories_file.write_text(json.dumps(stories, indent=2, default=str))

    # ── Style guide ──────────────────────────────────────────────

    def get_style(self) -> str:
        if self._style_file.exists():
            return self._style_file.read_text()
        return ""

    def save_style(self, content: str) -> None:
        self._style_file.write_text(content)

    # ── Metrics ──────────────────────────────────────────────────

    def get_metrics(self) -> dict:
        if self._metrics_file.exists():
            return json.loads(self._metrics_file.read_text())
        return {"tweets_posted": 0, "total_impressions": 0, "total_likes": 0,
                "total_retweets": 0, "history": []}

    def save_metrics(self, metrics: dict) -> None:
        self._metrics_file.write_text(json.dumps(metrics, indent=2, default=str))

    # ── X API operations ─────────────────────────────────────────

    async def scan_feed(self) -> list[dict]:
        """Fetch home timeline via X API v2. Returns list of tweet dicts."""
        client = self._get_client()
        tweets = []
        try:
            # Get authenticated user's timeline
            resp = client.get_home_timeline(
                max_results=50,
                tweet_fields=["created_at", "public_metrics", "author_id", "conversation_id"],
                expansions=["author_id"],
            )
            if resp.data:
                users = {u.id: u for u in (resp.includes.get("users", []) if resp.includes else [])}
                for t in resp.data:
                    author = users.get(t.author_id)
                    tweets.append({
                        "id": str(t.id),
                        "text": t.text,
                        "author": author.username if author else str(t.author_id),
                        "author_name": author.name if author else "",
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                        "metrics": dict(t.public_metrics) if t.public_metrics else {},
                    })
        except Exception as e:
            logger.error("Twitter scan_feed error: {}", e)
            raise
        self.save_scan("feed", tweets)
        self._state["last_scan"] = datetime.now().isoformat()
        self._state["last_scan_count"] = len(tweets)
        self.save_state()
        return tweets

    async def get_mentions(self) -> list[dict]:
        """Fetch recent mentions."""
        client = self._get_client()
        mentions = []
        try:
            me = client.get_me()
            if not me.data:
                return []
            resp = client.get_users_mentions(
                me.data.id,
                max_results=20,
                tweet_fields=["created_at", "public_metrics", "author_id", "conversation_id"],
                expansions=["author_id"],
            )
            if resp.data:
                users = {u.id: u for u in (resp.includes.get("users", []) if resp.includes else [])}
                for t in resp.data:
                    author = users.get(t.author_id)
                    mentions.append({
                        "id": str(t.id),
                        "text": t.text,
                        "author": author.username if author else str(t.author_id),
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                        "metrics": dict(t.public_metrics) if t.public_metrics else {},
                    })
        except Exception as e:
            logger.error("Twitter get_mentions error: {}", e)
        return mentions

    async def post_tweet(self, draft_id: str) -> str:
        """Post a queued draft tweet. Returns tweet URL or error."""
        draft = self._queue_get(draft_id)
        if not draft:
            return f"Error: Draft {draft_id} not found"
        if draft["state"] not in ("pending", "approved"):
            return f"Error: Draft is in state '{draft['state']}', cannot post"

        client = self._get_client()
        try:
            kwargs: dict[str, Any] = {"text": draft["text"]}
            if draft.get("reply_to"):
                kwargs["in_reply_to_tweet_id"] = draft["reply_to"]
            resp = client.create_tweet(**kwargs)
            tweet_id = resp.data["id"]
            draft["state"] = "posted"
            draft["posted_at"] = datetime.now().isoformat()
            draft["tweet_id"] = str(tweet_id)
            self._queue_save(draft)

            # Update metrics
            metrics = self.get_metrics()
            metrics["tweets_posted"] = metrics.get("tweets_posted", 0) + 1
            metrics["history"].append({
                "tweet_id": str(tweet_id),
                "text": draft["text"][:100],
                "posted_at": draft["posted_at"],
            })
            self.save_metrics(metrics)

            self._state["last_post"] = datetime.now().isoformat()
            self._state["total_posted"] = metrics["tweets_posted"]
            self.save_state()
            await self.notify_dashboard("twitter_posted", {"draft_id": draft_id, "tweet_id": str(tweet_id)})

            # Get the username for URL
            me = client.get_me()
            username = me.data.username if me.data else "user"
            return f"Posted: https://x.com/{username}/status/{tweet_id}"
        except Exception as e:
            draft["state"] = "pending"  # Reset to allow retry
            draft["metadata"]["last_error"] = str(e)
            self._queue_save(draft)
            logger.error("Twitter post error: {}", e)
            return f"Error posting tweet: {e}"

    async def fetch_user_tweets(self, username: str, max_results: int = 20) -> list[dict]:
        """Fetch recent tweets from a specific user (for style analysis)."""
        client = self._get_client()
        tweets = []
        try:
            user = client.get_user(username=username)
            if not user.data:
                return []
            resp = client.get_users_tweets(
                user.data.id,
                max_results=min(max_results, 100),
                tweet_fields=["created_at", "public_metrics"],
                exclude=["retweets", "replies"],
            )
            if resp.data:
                for t in resp.data:
                    tweets.append({
                        "text": t.text,
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                        "metrics": dict(t.public_metrics) if t.public_metrics else {},
                    })
        except Exception as e:
            logger.error("Twitter fetch_user_tweets({}) error: {}", username, e)
        return tweets

    async def get_bookmarks(self) -> list[dict]:
        """Fetch user's bookmarks."""
        client = self._get_client()
        bookmarks = []
        try:
            resp = client.get_bookmarks(
                max_results=50,
                tweet_fields=["created_at", "public_metrics", "author_id"],
                expansions=["author_id"],
            )
            if resp.data:
                users = {u.id: u for u in (resp.includes.get("users", []) if resp.includes else [])}
                for t in resp.data:
                    author = users.get(t.author_id)
                    bookmarks.append({
                        "id": str(t.id),
                        "text": t.text,
                        "author": author.username if author else str(t.author_id),
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                    })
        except Exception as e:
            logger.error("Twitter get_bookmarks error: {}", e)
        return bookmarks

    # ── SpecializedAgent interface ────────────────────────────────

    async def execute(self, operation: str, **kwargs: Any) -> str:
        if operation == "scan_feed":
            tweets = await self.scan_feed()
            return f"Scanned {len(tweets)} tweets from timeline."
        elif operation == "mentions":
            mentions = await self.get_mentions()
            return f"Found {len(mentions)} mentions."
        elif operation == "post":
            draft_id = kwargs.get("draft_id", "")
            return await self.post_tweet(draft_id)
        elif operation == "queue":
            drafts = self._queue_list()
            pending = [d for d in drafts if d["state"] == "pending"]
            return f"{len(pending)} pending drafts, {len(drafts)} total."
        elif operation == "bookmarks":
            bm = await self.get_bookmarks()
            return f"Fetched {len(bm)} bookmarks."
        return f"Unknown operation: {operation}"

    def status_summary(self) -> str:
        pending = len([d for d in self._queue_list() if d["state"] == "pending"])
        last_scan = self._state.get("last_scan", "never")
        posted = self._state.get("total_posted", 0)
        return f"{pending} pending, {posted} posted, last scan: {last_scan}"
