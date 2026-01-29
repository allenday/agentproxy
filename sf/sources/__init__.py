"""
Source Adapters Package
=======================

External demand channels that produce WorkOrders for the ShopFloor.
Each adapter converts an external signal (GitHub issue, Jira ticket,
Prometheus alert, CLI input) into a WorkOrder with proper source tracking.
"""

from .base import SourceAdapter, SourceEvent
from .github_adapter import GitHubSourceAdapter
from .jira_adapter import JiraSourceAdapter
from .alert_adapter import AlertSourceAdapter
from .cli_adapter import CLISourceAdapter

__all__ = [
    "SourceAdapter",
    "SourceEvent",
    "GitHubSourceAdapter",
    "JiraSourceAdapter",
    "AlertSourceAdapter",
    "CLISourceAdapter",
]
