"""
GitHub Source Adapter
=====================

Maps GitHub issues and pull requests to WorkOrders.

Mapping:
  - Issue title -> WorkOrder prompt
  - Issue labels -> required_capabilities hints
  - Issue milestone -> dependency hints
  - Issue assignee -> routing hint
  - PR review comments -> feedback work orders
"""

from typing import Any, Dict, List, Optional

from .base import SourceAdapter, SourceEvent


# Label-to-capability mapping
_LABEL_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "python": {"languages": ["python"]},
    "typescript": {"languages": ["typescript"]},
    "rust": {"languages": ["rust"]},
    "docker": {"tools": ["docker"]},
    "gpu": {"gpu": True},
    "large-context": {"context_window": {"min": 100_000}},
    "security": {"tools": ["bandit", "semgrep"]},
}

# Labels that map to SOP names
_LABEL_SOP: Dict[str, str] = {
    "bug": "hotfix",
    "hotfix": "hotfix",
    "refactor": "refactor",
    "docs": "documentation",
    "documentation": "documentation",
}


class GitHubSourceAdapter(SourceAdapter):
    """Converts GitHub webhook payloads into WorkOrders."""

    @property
    def source_type(self) -> str:
        return "github"

    def parse_event(self, payload: Dict[str, Any]) -> Optional[SourceEvent]:
        """Parse GitHub webhook payload.

        Handles:
          - issues (opened, labeled)
          - pull_request (opened, review_requested)

        Args:
            payload: GitHub webhook JSON body.

        Returns:
            SourceEvent or None if not actionable.
        """
        action = payload.get("action", "")

        # Issue events
        issue = payload.get("issue")
        if issue and action in ("opened", "labeled", "assigned"):
            return self._parse_issue(issue, payload)

        # PR events
        pr = payload.get("pull_request")
        if pr and action in ("opened", "review_requested"):
            return self._parse_pull_request(pr, payload)

        return None

    def _parse_issue(
        self, issue: Dict[str, Any], payload: Dict[str, Any],
    ) -> SourceEvent:
        """Parse a GitHub issue into a SourceEvent."""
        labels = [lbl.get("name", "") for lbl in issue.get("labels", [])]
        number = issue.get("number", 0)
        repo = payload.get("repository", {}).get("full_name", "unknown")

        return SourceEvent(
            source_type="github",
            source_ref=f"GH#{number}",
            title=issue.get("title", ""),
            body=issue.get("body", "") or "",
            labels=labels,
            priority=self._label_priority(labels),
            metadata={
                "repo": repo,
                "number": number,
                "url": issue.get("html_url", ""),
                "assignee": (issue.get("assignee") or {}).get("login"),
                "milestone": (issue.get("milestone") or {}).get("title"),
                "state": issue.get("state", "open"),
            },
        )

    def _parse_pull_request(
        self, pr: Dict[str, Any], payload: Dict[str, Any],
    ) -> SourceEvent:
        """Parse a GitHub PR into a SourceEvent."""
        labels = [lbl.get("name", "") for lbl in pr.get("labels", [])]
        number = pr.get("number", 0)
        repo = payload.get("repository", {}).get("full_name", "unknown")

        return SourceEvent(
            source_type="github",
            source_ref=f"GH#PR{number}",
            title=f"Review PR: {pr.get('title', '')}",
            body=pr.get("body", "") or "",
            labels=labels,
            priority=self._label_priority(labels),
            metadata={
                "repo": repo,
                "number": number,
                "url": pr.get("html_url", ""),
                "head_ref": pr.get("head", {}).get("ref"),
                "base_ref": pr.get("base", {}).get("ref"),
                "draft": pr.get("draft", False),
            },
        )

    def _infer_capabilities(self, event: SourceEvent) -> Dict[str, Any]:
        """Infer capabilities from GitHub labels."""
        caps: Dict[str, Any] = {}
        for label in event.labels:
            label_lower = label.lower()
            if label_lower in _LABEL_CAPABILITIES:
                caps.update(_LABEL_CAPABILITIES[label_lower])
        return caps

    def infer_sop(self, event: SourceEvent) -> Optional[str]:
        """Infer SOP name from GitHub labels.

        Args:
            event: Parsed GitHub event.

        Returns:
            SOP name or None.
        """
        for label in event.labels:
            label_lower = label.lower()
            if label_lower in _LABEL_SOP:
                return _LABEL_SOP[label_lower]
        return None

    @staticmethod
    def _label_priority(labels: List[str]) -> int:
        """Map labels to priority (lower = higher priority)."""
        label_set = {lbl.lower() for lbl in labels}
        if "critical" in label_set or "p0" in label_set:
            return 0
        if "high" in label_set or "p1" in label_set:
            return 1
        if "medium" in label_set or "p2" in label_set:
            return 2
        return 3
