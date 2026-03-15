"""Twitter tool: interface for the agent to control the TwitterAgent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.twitter import TwitterAgent


class TwitterTool(Tool):
    """Manage Twitter/X presence: scan feeds, generate tweets, manage queue, post."""

    def __init__(self, agent: TwitterAgent):
        self._agent = agent

    @property
    def name(self) -> str:
        return "twitter"

    @property
    def description(self) -> str:
        return (
            "Manage Twitter/X presence. Operations:\n"
            "- scan_feed: Fetch home timeline, store results\n"
            "- scan_newsletters: Fetch & summarize configured newsletter URLs\n"
            "- build_stories: Aggregate scanned signals into stories by sector\n"
            "- generate_tweet: Create a tweet draft (added to queue for approval)\n"
            "- generate_reply: Create a reply draft to a specific tweet\n"
            "- post: Publish a queued draft (requires draft_id)\n"
            "- analyze_performance: Fetch engagement metrics for posted tweets\n"
            "- build_style: Analyze target profiles to generate STYLE.md\n"
            "- queue_review: List pending drafts for approval\n"
            "- approve: Approve a draft for posting (requires draft_id)\n"
            "- reject: Reject/delete a draft (requires draft_id)\n"
            "- edit: Edit a draft's text (requires draft_id and text)\n"
            "- mentions: Fetch recent mentions\n"
            "- bookmarks: Fetch user's bookmarks\n"
            "- get_style: Read current style guide\n"
            "- set_style: Update style guide (requires content)"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "scan_feed", "scan_newsletters", "build_stories",
                        "generate_tweet", "generate_reply", "post",
                        "analyze_performance", "build_style", "queue_review",
                        "approve", "reject", "edit", "mentions", "bookmarks",
                        "get_style", "set_style",
                    ],
                    "description": "The operation to perform.",
                },
                "text": {
                    "type": "string",
                    "description": "Tweet text (for generate_tweet, generate_reply, edit).",
                },
                "draft_id": {
                    "type": "string",
                    "description": "Draft ID (for post, approve, reject, edit).",
                },
                "reply_to": {
                    "type": "string",
                    "description": "Tweet ID to reply to (for generate_reply).",
                },
                "content": {
                    "type": "string",
                    "description": "Content for set_style.",
                },
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Newsletter URLs (for scan_newsletters).",
                },
                "stories": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Story objects (for build_stories).",
                },
            },
            "required": ["operation"],
        }

    async def execute(self, operation: str, **kwargs: Any) -> str:
        agent = self._agent

        if operation == "scan_feed":
            tweets = await agent.scan_feed()
            # Return summarized results for LLM processing
            if not tweets:
                return "No tweets found in timeline."
            lines = [f"Scanned {len(tweets)} tweets:\n"]
            for t in tweets[:20]:  # Top 20 for LLM context
                metrics = t.get("metrics", {})
                engagement = metrics.get("like_count", 0) + metrics.get("retweet_count", 0)
                lines.append(f"- @{t['author']}: {t['text'][:150]} [engagement: {engagement}]")
            return "\n".join(lines)

        elif operation == "scan_newsletters":
            urls = kwargs.get("urls", [])
            if not urls:
                return "No newsletter URLs provided."
            # For now, return the URLs to be fetched by the agent using web_fetch
            return f"Newsletter URLs to process:\n" + "\n".join(f"- {u}" for u in urls)

        elif operation == "build_stories":
            stories = kwargs.get("stories", [])
            if not stories:
                return "No stories provided. Use scan_feed first, then call build_stories with aggregated story objects."
            agent.save_stories(stories)
            return f"Saved {len(stories)} stories."

        elif operation == "generate_tweet":
            text = kwargs.get("text", "")
            if not text:
                return "Error: text is required for generate_tweet."
            if len(text) > 280:
                return f"Error: tweet is {len(text)} chars, max is 280."
            draft = agent.create_draft(text, source="generated")
            await agent.notify_dashboard("twitter_draft", {"draft_id": draft["id"]})
            return f"Draft created: {draft['id']}\nText: {text}\nState: pending (needs approval)"

        elif operation == "generate_reply":
            text = kwargs.get("text", "")
            reply_to = kwargs.get("reply_to", "")
            if not text or not reply_to:
                return "Error: text and reply_to are required for generate_reply."
            if len(text) > 280:
                return f"Error: reply is {len(text)} chars, max is 280."
            draft = agent.create_draft(text, reply_to=reply_to, source="reply")
            await agent.notify_dashboard("twitter_draft", {"draft_id": draft["id"]})
            return f"Reply draft created: {draft['id']}\nReply to: {reply_to}\nText: {text}"

        elif operation == "post":
            draft_id = kwargs.get("draft_id", "")
            if not draft_id:
                return "Error: draft_id is required."
            return await agent.post_tweet(draft_id)

        elif operation == "approve":
            draft_id = kwargs.get("draft_id", "")
            if not draft_id:
                return "Error: draft_id is required."
            draft = agent._queue_get(draft_id)
            if not draft:
                return f"Error: Draft {draft_id} not found."
            draft["state"] = "approved"
            agent._queue_save(draft)
            return f"Draft {draft_id} approved. Call post with this draft_id to publish."

        elif operation == "reject":
            draft_id = kwargs.get("draft_id", "")
            if not draft_id:
                return "Error: draft_id is required."
            draft = agent._queue_get(draft_id)
            if not draft:
                return f"Error: Draft {draft_id} not found."
            draft["state"] = "rejected"
            agent._queue_save(draft)
            return f"Draft {draft_id} rejected."

        elif operation == "edit":
            draft_id = kwargs.get("draft_id", "")
            text = kwargs.get("text", "")
            if not draft_id or not text:
                return "Error: draft_id and text are required."
            if len(text) > 280:
                return f"Error: tweet is {len(text)} chars, max is 280."
            draft = agent._queue_get(draft_id)
            if not draft:
                return f"Error: Draft {draft_id} not found."
            draft["text"] = text
            agent._queue_save(draft)
            return f"Draft {draft_id} updated."

        elif operation == "queue_review":
            drafts = agent._queue_list()
            pending = [d for d in drafts if d["state"] == "pending"]
            if not pending:
                return "No pending drafts in queue."
            lines = [f"{len(pending)} pending draft(s):\n"]
            for d in pending:
                lines.append(f"- [{d['id']}] {d['text'][:120]}{'...' if len(d['text']) > 120 else ''}")
                if d.get("reply_to"):
                    lines.append(f"  (reply to: {d['reply_to']})")
            return "\n".join(lines)

        elif operation == "analyze_performance":
            metrics = agent.get_metrics()
            if not metrics.get("history"):
                return "No posted tweets to analyze yet."
            return (
                f"Performance summary:\n"
                f"- Total posted: {metrics.get('tweets_posted', 0)}\n"
                f"- Recent tweets: {len(metrics.get('history', []))}\n"
                f"Use scan_feed to fetch engagement data for individual tweets."
            )

        elif operation == "build_style":
            profiles = agent.config.style_profiles
            if not profiles:
                return "No style_profiles configured in twitter config. Set twitter.style_profiles to a list of @handles."
            all_tweets = []
            for handle in profiles:
                handle = handle.lstrip("@")
                tweets = await agent.fetch_user_tweets(handle, max_results=30)
                all_tweets.append({"handle": handle, "tweets": tweets})
            # Return raw data for LLM to analyze and produce STYLE.md
            lines = [f"Fetched tweets from {len(profiles)} profile(s) for style analysis:\n"]
            for entry in all_tweets:
                lines.append(f"\n## @{entry['handle']} ({len(entry['tweets'])} tweets)")
                for t in entry["tweets"][:10]:
                    lines.append(f"- {t['text'][:200]}")
            lines.append("\nAnalyze these tweets for tone, vocabulary, structure, and engagement patterns. "
                        "Then call twitter(operation='set_style', content='...') with the generated STYLE.md.")
            return "\n".join(lines)

        elif operation == "get_style":
            style = agent.get_style()
            return style if style else "No style guide yet. Use build_style to generate one."

        elif operation == "set_style":
            content = kwargs.get("content", "")
            if not content:
                return "Error: content is required."
            agent.save_style(content)
            return f"Style guide updated ({len(content)} chars)."

        elif operation == "mentions":
            mentions = await agent.get_mentions()
            if not mentions:
                return "No recent mentions."
            lines = [f"{len(mentions)} recent mention(s):\n"]
            for m in mentions[:10]:
                lines.append(f"- @{m['author']}: {m['text'][:150]}")
            return "\n".join(lines)

        elif operation == "bookmarks":
            bm = await agent.get_bookmarks()
            if not bm:
                return "No bookmarks found."
            lines = [f"{len(bm)} bookmark(s):\n"]
            for b in bm[:20]:
                lines.append(f"- @{b['author']}: {b['text'][:150]}")
            return "\n".join(lines)

        return f"Unknown operation: {operation}"
