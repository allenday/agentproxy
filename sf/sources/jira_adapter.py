"""
Jira Source Adapter
===================

Maps Jira webhook events to WorkOrders.

Mapping:
  - Epic -> production run (multiple work orders)
  - Story -> single WorkOrder
  - Subtask -> WorkOrder with depends_on
  - Story points -> capability hints
  - Sprint -> scheduling metadata
"""

from typing import Any, Dict, List, Optional

from .base import SourceAdapter, SourceEvent


# Jira issue type to SOP mapping
_TYPE_SOP: Dict[str, str] = {
    "Bug": "hotfix",
    "Story": "v0",
    "Task": "v0",
    "Sub-task": "v0",
    "Documentation": "documentation",
    "Technical Debt": "refactor",
}


class JiraSourceAdapter(SourceAdapter):
    """Converts Jira webhook payloads into WorkOrders."""

    @property
    def source_type(self) -> str:
        return "jira"

    def parse_event(self, payload: Dict[str, Any]) -> Optional[SourceEvent]:
        """Parse Jira webhook payload.

        Handles:
          - jira:issue_created
          - jira:issue_updated (status transitions to "To Do" or "In Progress")

        Args:
            payload: Jira webhook JSON body.

        Returns:
            SourceEvent or None if not actionable.
        """
        event_type = payload.get("webhookEvent", "")
        issue = payload.get("issue")

        if not issue:
            return None

        # Only act on creation or transition to actionable status
        if event_type == "jira:issue_created":
            return self._parse_issue(issue, payload)

        if event_type == "jira:issue_updated":
            changelog = payload.get("changelog", {})
            for item in changelog.get("items", []):
                if item.get("field") == "status":
                    to_status = item.get("toString", "").lower()
                    if to_status in ("to do", "in progress", "selected for development"):
                        return self._parse_issue(issue, payload)

        return None

    def _parse_issue(
        self, issue: Dict[str, Any], payload: Dict[str, Any],
    ) -> SourceEvent:
        """Parse a Jira issue into a SourceEvent."""
        fields = issue.get("fields", {})
        issue_key = issue.get("key", "UNKNOWN-0")
        issue_type = (fields.get("issuetype") or {}).get("name", "Task")
        labels = fields.get("labels", [])
        priority_name = (fields.get("priority") or {}).get("name", "Medium")
        story_points = fields.get("story_points") or fields.get("customfield_10028")

        # Extract parent link for subtask dependencies
        parent_key = None
        parent = fields.get("parent")
        if parent:
            parent_key = parent.get("key")

        # Extract linked issues for depends_on
        linked_keys: List[str] = []
        for link in fields.get("issuelinks", []):
            link_type = (link.get("type") or {}).get("name", "")
            if link_type in ("Blocks", "is blocked by"):
                inward = link.get("inwardIssue", {})
                if inward:
                    linked_keys.append(inward.get("key", ""))

        return SourceEvent(
            source_type="jira",
            source_ref=issue_key,
            title=fields.get("summary", ""),
            body=fields.get("description", "") or "",
            labels=labels,
            priority=self._priority_to_int(priority_name),
            metadata={
                "issue_type": issue_type,
                "project": issue_key.split("-")[0] if "-" in issue_key else "",
                "parent_key": parent_key,
                "linked_keys": linked_keys,
                "story_points": story_points,
                "sprint": self._extract_sprint(fields),
                "assignee": (fields.get("assignee") or {}).get("displayName"),
                "reporter": (fields.get("reporter") or {}).get("displayName"),
                "status": (fields.get("status") or {}).get("name"),
                "url": f"{issue.get('self', '')}/browse/{issue_key}",
            },
        )

    def _infer_capabilities(self, event: SourceEvent) -> Dict[str, Any]:
        """Infer capabilities from Jira metadata."""
        caps: Dict[str, Any] = {}
        story_points = event.metadata.get("story_points")

        # Large stories may need more context window
        if story_points and story_points > 8:
            caps["context_window"] = {"min": 150_000}

        # Label-based capabilities
        for label in event.labels:
            label_lower = label.lower()
            if label_lower in ("python", "typescript", "rust", "go"):
                caps.setdefault("languages", []).append(label_lower)
            if label_lower == "docker":
                caps.setdefault("tools", []).append("docker")
            if label_lower == "gpu":
                caps["gpu"] = True

        return caps

    def infer_sop(self, event: SourceEvent) -> Optional[str]:
        """Infer SOP name from Jira issue type.

        Args:
            event: Parsed Jira event.

        Returns:
            SOP name or None.
        """
        issue_type = event.metadata.get("issue_type", "")
        return _TYPE_SOP.get(issue_type)

    @staticmethod
    def _priority_to_int(priority_name: str) -> int:
        """Map Jira priority names to integers."""
        mapping = {
            "Highest": 0, "Blocker": 0,
            "High": 1, "Critical": 1,
            "Medium": 2,
            "Low": 3,
            "Lowest": 4,
        }
        return mapping.get(priority_name, 2)

    @staticmethod
    def _extract_sprint(fields: Dict[str, Any]) -> Optional[str]:
        """Extract sprint name from Jira fields."""
        sprint_field = fields.get("sprint") or fields.get("customfield_10020")
        if isinstance(sprint_field, dict):
            return sprint_field.get("name")
        if isinstance(sprint_field, list) and sprint_field:
            item = sprint_field[0]
            if isinstance(item, dict):
                return item.get("name")
            if isinstance(item, str) and "name=" in item:
                for part in item.split(","):
                    if "name=" in part:
                        return part.split("name=")[1].strip()
        return None
