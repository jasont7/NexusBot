"""Email Personal Assistant agent: triage, classify, draft responses, auto-archive."""

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


class EmailPAAgent(SpecializedAgent):
    """Smart email triage: classifies inbox, drafts responses, archives noise, tracks actions for undo."""

    def __init__(self, workspace: Path, bus: MessageBus):
        super().__init__(name="email_pa", workspace=workspace, bus=bus)
        self._actions_file = self._workspace_dir / "actions.json"
        self._rules_file = self._workspace_dir / "rules.json"
        self._triage_file = self._workspace_dir / "triage.json"
        self._snoozed_file = self._workspace_dir / "snoozed.json"
        self._drafts_dir = self._workspace_dir / "drafts"
        self._drafts_dir.mkdir(parents=True, exist_ok=True)

    # ── Action log (for undo) ────────────────────────────────────

    def _load_actions(self) -> list[dict]:
        if self._actions_file.exists():
            try:
                return json.loads(self._actions_file.read_text())
            except Exception:
                pass
        return []

    def _save_actions(self, actions: list[dict]) -> None:
        # Keep last 500 actions
        self._actions_file.write_text(json.dumps(actions[-500:], indent=2, default=str))

    def log_action(self, action_type: str, target: str, details: dict | None = None) -> dict:
        """Log an action for undo tracking."""
        entry = {
            "id": str(uuid.uuid4())[:8],
            "type": action_type,  # archive, respond, snooze, label
            "target": target,  # email identifier (message_id or sender)
            "details": details or {},
            "timestamp": datetime.now().isoformat(),
            "undone": False,
        }
        actions = self._load_actions()
        actions.append(entry)
        self._save_actions(actions)
        return entry

    def undo_action(self, action_id: str) -> str:
        """Mark an action as undone. Returns description of what was undone."""
        actions = self._load_actions()
        for a in actions:
            if a["id"] == action_id and not a["undone"]:
                a["undone"] = True
                self._save_actions(actions)
                return f"Undone: {a['type']} on {a['target']}"
        return f"Action {action_id} not found or already undone."

    def get_actions(self, limit: int = 20) -> list[dict]:
        """Get recent actions (most recent first)."""
        actions = self._load_actions()
        return list(reversed(actions[-limit:]))

    # ── Triage rules ─────────────────────────────────────────────

    def _load_rules(self) -> list[dict]:
        if self._rules_file.exists():
            try:
                return json.loads(self._rules_file.read_text())
            except Exception:
                pass
        return []

    def _save_rules(self, rules: list[dict]) -> None:
        self._rules_file.write_text(json.dumps(rules, indent=2, default=str))

    def add_rule(self, condition: str, action: str, reason: str = "") -> dict:
        """Add a learned triage rule.

        Args:
            condition: e.g. "from:noreply@github.com", "subject:contains:newsletter"
            action: e.g. "archive", "label:fyi", "importance:1"
            reason: why this rule was created
        """
        rule = {
            "id": str(uuid.uuid4())[:8],
            "condition": condition,
            "action": action,
            "reason": reason,
            "created_at": datetime.now().isoformat(),
            "enabled": True,
            "times_applied": 0,
        }
        rules = self._load_rules()
        rules.append(rule)
        self._save_rules(rules)
        return rule

    def get_rules(self) -> list[dict]:
        return self._load_rules()

    def delete_rule(self, rule_id: str) -> bool:
        rules = self._load_rules()
        filtered = [r for r in rules if r["id"] != rule_id]
        if len(filtered) < len(rules):
            self._save_rules(filtered)
            return True
        return False

    def toggle_rule(self, rule_id: str) -> str:
        rules = self._load_rules()
        for r in rules:
            if r["id"] == rule_id:
                r["enabled"] = not r["enabled"]
                self._save_rules(rules)
                return f"Rule {rule_id} {'enabled' if r['enabled'] else 'disabled'}."
        return f"Rule {rule_id} not found."

    def match_rules(self, sender: str, subject: str) -> list[dict]:
        """Find rules that match a given email. Returns matching rules."""
        rules = self._load_rules()
        matches = []
        for r in rules:
            if not r.get("enabled", True):
                continue
            cond = r["condition"].lower()
            if cond.startswith("from:") and cond[5:] in sender.lower():
                matches.append(r)
            elif cond.startswith("subject:contains:") and cond[17:] in subject.lower():
                matches.append(r)
            elif cond.startswith("domain:"):
                domain = cond[7:]
                if sender.lower().endswith(f"@{domain}") or sender.lower().endswith(f".{domain}"):
                    matches.append(r)
        return matches

    # ── Triage results ───────────────────────────────────────────

    def save_triage(self, items: list[dict]) -> None:
        """Save triage results (classified emails)."""
        self._triage_file.write_text(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "count": len(items),
            "items": items,
        }, indent=2, default=str))
        self._state["last_triage"] = datetime.now().isoformat()
        self._state["triage_count"] = len(items)
        self.save_state()

    def get_triage(self) -> dict:
        if self._triage_file.exists():
            return json.loads(self._triage_file.read_text())
        return {"items": [], "count": 0}

    # ── Snoozed items ────────────────────────────────────────────

    def snooze(self, email_id: str, remind_at: str, subject: str = "") -> dict:
        """Snooze an email for later."""
        snoozed = self._load_snoozed()
        entry = {
            "id": str(uuid.uuid4())[:8],
            "email_id": email_id,
            "subject": subject,
            "remind_at": remind_at,
            "created_at": datetime.now().isoformat(),
            "reminded": False,
        }
        snoozed.append(entry)
        self._save_snoozed(snoozed)
        self.log_action("snooze", email_id, {"remind_at": remind_at, "subject": subject})
        return entry

    def get_snoozed(self) -> list[dict]:
        return [s for s in self._load_snoozed() if not s.get("reminded")]

    def get_due_snoozes(self) -> list[dict]:
        """Get snoozed items that are past their remind_at time."""
        now = datetime.now().isoformat()
        return [s for s in self._load_snoozed()
                if not s.get("reminded") and s.get("remind_at", "") <= now]

    def mark_reminded(self, snooze_id: str) -> None:
        snoozed = self._load_snoozed()
        for s in snoozed:
            if s["id"] == snooze_id:
                s["reminded"] = True
                break
        self._save_snoozed(snoozed)

    def _load_snoozed(self) -> list[dict]:
        if self._snoozed_file.exists():
            try:
                return json.loads(self._snoozed_file.read_text())
            except Exception:
                pass
        return []

    def _save_snoozed(self, snoozed: list[dict]) -> None:
        self._snoozed_file.write_text(json.dumps(snoozed, indent=2, default=str))

    # ── Draft responses ──────────────────────────────────────────

    def save_draft(self, email_id: str, to: str, subject: str, body: str) -> dict:
        """Save a draft email response."""
        draft = {
            "id": str(uuid.uuid4())[:8],
            "email_id": email_id,
            "to": to,
            "subject": subject,
            "body": body,
            "state": "draft",  # draft | sent | discarded
            "created_at": datetime.now().isoformat(),
        }
        path = self._drafts_dir / f"{draft['id']}.json"
        path.write_text(json.dumps(draft, indent=2, default=str))
        return draft

    def list_drafts(self) -> list[dict]:
        drafts = []
        for f in sorted(self._drafts_dir.glob("*.json")):
            try:
                d = json.loads(f.read_text())
                if d.get("state") == "draft":
                    drafts.append(d)
            except Exception:
                pass
        return drafts

    def get_draft(self, draft_id: str) -> dict | None:
        path = self._drafts_dir / f"{draft_id}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def update_draft(self, draft_id: str, **fields: Any) -> dict | None:
        draft = self.get_draft(draft_id)
        if not draft:
            return None
        draft.update(fields)
        path = self._drafts_dir / f"{draft_id}.json"
        path.write_text(json.dumps(draft, indent=2, default=str))
        return draft

    # ── SpecializedAgent interface ────────────────────────────────

    async def execute(self, operation: str, **kwargs: Any) -> str:
        if operation == "triage":
            triage = self.get_triage()
            items = triage.get("items", [])
            if not items:
                return "No triage results. Use the email_triage tool to classify inbox."
            action_req = [i for i in items if i.get("category") == "action-required"]
            return f"Triage: {len(items)} emails ({len(action_req)} action-required)"
        elif operation == "rules":
            rules = self.get_rules()
            return f"{len(rules)} triage rules configured."
        elif operation == "actions":
            actions = self.get_actions()
            return f"{len(actions)} recent actions."
        return f"Unknown operation: {operation}"

    def status_summary(self) -> str:
        triage = self.get_triage()
        items = triage.get("items", [])
        action_req = len([i for i in items if i.get("category") == "action-required"])
        rules = len(self.get_rules())
        drafts = len(self.list_drafts())
        last = self._state.get("last_triage", "never")
        return f"{action_req} action-required, {drafts} drafts, {rules} rules, last triage: {last}"
