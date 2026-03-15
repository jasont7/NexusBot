"""Email triage tool: classify inbox, draft responses, archive, snooze, undo."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.email_pa import EmailPAAgent


class EmailTriageTool(Tool):
    """Smart email triage: classify, respond, archive, snooze, with full undo support."""

    def __init__(self, agent: EmailPAAgent):
        self._agent = agent

    @property
    def name(self) -> str:
        return "email_triage"

    @property
    def description(self) -> str:
        return (
            "Smart email personal assistant. Operations:\n"
            "- triage: Classify emails by importance (1-5) and category "
            "(action-required, fyi, newsletter, spam). Pass classified items as triage_items.\n"
            "- respond: Draft a response to an email (requires email_id, to, subject, body)\n"
            "- send_draft: Send a previously saved draft (requires draft_id)\n"
            "- list_drafts: List pending draft responses\n"
            "- archive: Log an archive action for an email (requires email_id, sender)\n"
            "- snooze: Remind about an email later (requires email_id, remind_at as ISO datetime)\n"
            "- check_snoozes: Check for due snoozed items\n"
            "- undo: Reverse the last action (requires action_id)\n"
            "- actions: View recent action log\n"
            "- rules: List learned triage rules\n"
            "- add_rule: Add a triage rule (requires condition, action, reason)\n"
            "- delete_rule: Remove a rule (requires rule_id)\n"
            "- toggle_rule: Enable/disable a rule (requires rule_id)\n"
            "- match_rules: Test which rules match an email (requires sender, subject)\n"
            "- get_triage: Get current triage results"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "triage", "respond", "send_draft", "list_drafts",
                        "archive", "snooze", "check_snoozes", "undo",
                        "actions", "rules", "add_rule", "delete_rule",
                        "toggle_rule", "match_rules", "get_triage",
                    ],
                    "description": "The operation to perform.",
                },
                "triage_items": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Classified email items for triage operation. Each item: {email_id, sender, subject, importance (1-5), category, summary}.",
                },
                "email_id": {
                    "type": "string",
                    "description": "Email message ID (for respond, archive, snooze).",
                },
                "sender": {
                    "type": "string",
                    "description": "Sender email (for archive, match_rules).",
                },
                "to": {
                    "type": "string",
                    "description": "Recipient (for respond).",
                },
                "subject": {
                    "type": "string",
                    "description": "Subject line (for respond, snooze, match_rules).",
                },
                "body": {
                    "type": "string",
                    "description": "Email body (for respond).",
                },
                "draft_id": {
                    "type": "string",
                    "description": "Draft ID (for send_draft).",
                },
                "action_id": {
                    "type": "string",
                    "description": "Action ID (for undo).",
                },
                "remind_at": {
                    "type": "string",
                    "description": "ISO datetime for snooze reminder.",
                },
                "condition": {
                    "type": "string",
                    "description": "Rule condition (e.g. 'from:noreply@github.com', 'subject:contains:newsletter', 'domain:example.com').",
                },
                "action": {
                    "type": "string",
                    "description": "Rule action (e.g. 'archive', 'label:fyi', 'importance:1').",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this rule was created.",
                },
                "rule_id": {
                    "type": "string",
                    "description": "Rule ID (for delete_rule, toggle_rule).",
                },
            },
            "required": ["operation"],
        }

    async def execute(self, operation: str, **kwargs: Any) -> str:
        agent = self._agent

        if operation == "triage":
            items = kwargs.get("triage_items", [])
            if not items:
                return ("No triage_items provided. First read emails using the email channel, "
                        "then classify each one and call email_triage(operation='triage', triage_items=[...]) "
                        "with items containing: email_id, sender, subject, importance (1-5), "
                        "category (action-required|fyi|newsletter|spam), summary.")
            agent.save_triage(items)

            # Auto-apply matching rules
            auto_actions = []
            for item in items:
                matches = agent.match_rules(
                    item.get("sender", ""), item.get("subject", ""))
                for rule in matches:
                    rule["times_applied"] = rule.get("times_applied", 0) + 1
                    auto_actions.append(f"  Rule '{rule['condition']}' → {rule['action']} on {item.get('sender', '?')}")

            # Save updated rule counts
            if auto_actions:
                rules = agent.get_rules()
                agent._save_rules(rules)

            action_req = [i for i in items if i.get("category") == "action-required"]
            fyi = [i for i in items if i.get("category") == "fyi"]
            news = [i for i in items if i.get("category") == "newsletter"]
            spam = [i for i in items if i.get("category") == "spam"]

            lines = [f"Triaged {len(items)} emails:"]
            lines.append(f"  Action required: {len(action_req)}")
            lines.append(f"  FYI: {len(fyi)}")
            lines.append(f"  Newsletter: {len(news)}")
            lines.append(f"  Spam/noise: {len(spam)}")
            if auto_actions:
                lines.append(f"\nAuto-applied {len(auto_actions)} rule(s):")
                lines.extend(auto_actions[:10])

            await agent.notify_dashboard("email_triage", {"count": len(items)})
            return "\n".join(lines)

        elif operation == "respond":
            email_id = kwargs.get("email_id", "")
            to = kwargs.get("to", "")
            subject = kwargs.get("subject", "")
            body = kwargs.get("body", "")
            if not to or not body:
                return "Error: to and body are required."
            draft = agent.save_draft(email_id, to, subject, body)
            agent.log_action("draft_response", email_id, {"draft_id": draft["id"], "to": to})
            return f"Draft response saved: {draft['id']}\nTo: {to}\nSubject: {subject}\nReview in dashboard or use send_draft to send."

        elif operation == "send_draft":
            draft_id = kwargs.get("draft_id", "")
            if not draft_id:
                return "Error: draft_id is required."
            draft = agent.get_draft(draft_id)
            if not draft:
                return f"Error: Draft {draft_id} not found."
            if draft["state"] != "draft":
                return f"Error: Draft is in state '{draft['state']}'."
            # Send via message bus
            from nanobot.bus.events import OutboundMessage
            await agent.bus.publish_outbound(OutboundMessage(
                channel="email",
                chat_id=draft["to"],
                content=draft["body"],
                metadata={"subject": draft["subject"], "force_send": True},
            ))
            agent.update_draft(draft_id, state="sent")
            agent.log_action("send_response", draft.get("email_id", ""), {
                "draft_id": draft_id, "to": draft["to"],
            })
            return f"Draft {draft_id} sent to {draft['to']}."

        elif operation == "list_drafts":
            drafts = agent.list_drafts()
            if not drafts:
                return "No pending drafts."
            lines = [f"{len(drafts)} draft(s):"]
            for d in drafts:
                lines.append(f"  [{d['id']}] To: {d['to']} | Subject: {d.get('subject', '(none)')}")
            return "\n".join(lines)

        elif operation == "archive":
            email_id = kwargs.get("email_id", "")
            sender = kwargs.get("sender", "")
            if not email_id:
                return "Error: email_id is required."
            agent.log_action("archive", email_id, {"sender": sender})
            return f"Archived email {email_id} from {sender}. Action logged (undo available)."

        elif operation == "snooze":
            email_id = kwargs.get("email_id", "")
            remind_at = kwargs.get("remind_at", "")
            subject = kwargs.get("subject", "")
            if not email_id or not remind_at:
                return "Error: email_id and remind_at are required."
            entry = agent.snooze(email_id, remind_at, subject)
            return f"Snoozed email {email_id} until {remind_at}. Snooze ID: {entry['id']}"

        elif operation == "check_snoozes":
            due = agent.get_due_snoozes()
            if not due:
                return "No snoozed items due."
            lines = [f"{len(due)} snoozed item(s) due:"]
            for s in due:
                lines.append(f"  [{s['id']}] {s.get('subject', s['email_id'])} (due: {s['remind_at']})")
            return "\n".join(lines)

        elif operation == "undo":
            action_id = kwargs.get("action_id", "")
            if not action_id:
                # Undo the most recent action
                actions = agent.get_actions(1)
                if not actions:
                    return "No actions to undo."
                action_id = actions[0]["id"]
            return agent.undo_action(action_id)

        elif operation == "actions":
            actions = agent.get_actions(20)
            if not actions:
                return "No recent actions."
            lines = [f"{len(actions)} recent action(s):"]
            for a in actions:
                undone = " [UNDONE]" if a.get("undone") else ""
                lines.append(f"  [{a['id']}] {a['type']} → {a['target']}{undone} ({a['timestamp'][:16]})")
            return "\n".join(lines)

        elif operation == "rules":
            rules = agent.get_rules()
            if not rules:
                return "No triage rules configured. Rules are learned from your triage patterns."
            lines = [f"{len(rules)} rule(s):"]
            for r in rules:
                status = "on" if r.get("enabled", True) else "off"
                applied = r.get("times_applied", 0)
                lines.append(f"  [{r['id']}] {r['condition']} → {r['action']} ({status}, applied {applied}x)")
                if r.get("reason"):
                    lines.append(f"    reason: {r['reason']}")
            return "\n".join(lines)

        elif operation == "add_rule":
            condition = kwargs.get("condition", "")
            action = kwargs.get("action", "")
            reason = kwargs.get("reason", "")
            if not condition or not action:
                return "Error: condition and action are required."
            rule = agent.add_rule(condition, action, reason)
            return f"Rule added: {rule['id']}\nCondition: {condition}\nAction: {action}"

        elif operation == "delete_rule":
            rule_id = kwargs.get("rule_id", "")
            if not rule_id:
                return "Error: rule_id is required."
            if agent.delete_rule(rule_id):
                return f"Rule {rule_id} deleted."
            return f"Rule {rule_id} not found."

        elif operation == "toggle_rule":
            rule_id = kwargs.get("rule_id", "")
            if not rule_id:
                return "Error: rule_id is required."
            return agent.toggle_rule(rule_id)

        elif operation == "match_rules":
            sender = kwargs.get("sender", "")
            subject = kwargs.get("subject", "")
            if not sender:
                return "Error: sender is required."
            matches = agent.match_rules(sender, subject)
            if not matches:
                return f"No rules match sender='{sender}' subject='{subject}'."
            lines = [f"{len(matches)} matching rule(s):"]
            for r in matches:
                lines.append(f"  [{r['id']}] {r['condition']} → {r['action']}")
            return "\n".join(lines)

        elif operation == "get_triage":
            triage = agent.get_triage()
            items = triage.get("items", [])
            if not items:
                return "No triage results yet."
            lines = [f"Last triage ({triage.get('timestamp', '?')}): {len(items)} emails\n"]
            for i in sorted(items, key=lambda x: x.get("importance", 5)):
                imp = i.get("importance", "?")
                cat = i.get("category", "?")
                lines.append(f"  [{imp}] {cat}: {i.get('sender', '?')} — {i.get('subject', '(no subject)')}")
                if i.get("summary"):
                    lines.append(f"      {i['summary'][:100]}")
            return "\n".join(lines)

        return f"Unknown operation: {operation}"
