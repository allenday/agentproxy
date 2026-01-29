"""
Alert Source Adapter
====================

Maps Prometheus AlertManager webhook payloads to WorkOrders.
Closes the Plane 2 loop: field incidents -> maintenance work orders
with source="telemetry".

This is the key bridge between product telemetry (Plane 2) and
the factory floor (Plane 0/1). When a deployed product signals a
problem, this adapter converts it into a corrective work order.
"""

from typing import Any, Dict, List, Optional

from .base import SourceAdapter, SourceEvent


# Alert name to SOP mapping
_ALERT_SOP: Dict[str, str] = {
    "HighErrorRate": "hotfix",
    "ServiceDown": "hotfix",
    "HighLatency": "hotfix",
    "MemoryLeak": "hotfix",
    "SecurityVulnerability": "hotfix",
    "TestFailure": "v0",
    "CoverageDropped": "v0",
}


class AlertSourceAdapter(SourceAdapter):
    """Converts Prometheus AlertManager webhooks to WorkOrders.

    Handles the standard AlertManager webhook format:
    https://prometheus.io/docs/alerting/latest/configuration/#webhook_config
    """

    @property
    def source_type(self) -> str:
        return "telemetry"

    def parse_event(self, payload: Dict[str, Any]) -> Optional[SourceEvent]:
        """Parse AlertManager webhook payload.

        Args:
            payload: AlertManager webhook JSON body containing 'alerts' array.

        Returns:
            SourceEvent for the highest-severity firing alert, or None.
        """
        alerts = payload.get("alerts", [])
        if not alerts:
            return None

        # Filter to firing alerts only
        firing = [a for a in alerts if a.get("status") == "firing"]
        if not firing:
            return None

        # Take the highest-severity alert
        alert = self._highest_severity(firing)
        return self._parse_alert(alert, payload)

    def _parse_alert(
        self, alert: Dict[str, Any], payload: Dict[str, Any],
    ) -> SourceEvent:
        """Parse a single alert into a SourceEvent."""
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        alert_name = labels.get("alertname", "UnknownAlert")
        severity = labels.get("severity", "warning")
        service = labels.get("service", labels.get("job", "unknown"))
        instance = labels.get("instance", "")

        # Build a descriptive body from annotations
        summary = annotations.get("summary", "")
        description = annotations.get("description", "")
        runbook = annotations.get("runbook_url", "")

        body_parts = []
        if summary:
            body_parts.append(f"Summary: {summary}")
        if description:
            body_parts.append(f"Description: {description}")
        if runbook:
            body_parts.append(f"Runbook: {runbook}")
        body_parts.append(f"\nService: {service}")
        body_parts.append(f"Instance: {instance}")
        body_parts.append(f"Severity: {severity}")

        # Include raw label values for context
        body_parts.append(f"\nAlert labels: {labels}")

        return SourceEvent(
            source_type="telemetry",
            source_ref=f"ALERT:{alert_name}:{service}",
            title=f"[{severity.upper()}] {alert_name} on {service}",
            body="\n".join(body_parts),
            labels=[alert_name, severity, service],
            priority=self._severity_to_priority(severity),
            metadata={
                "alert_name": alert_name,
                "severity": severity,
                "service": service,
                "instance": instance,
                "starts_at": alert.get("startsAt", ""),
                "ends_at": alert.get("endsAt", ""),
                "generator_url": alert.get("generatorURL", ""),
                "fingerprint": alert.get("fingerprint", ""),
                "group_key": payload.get("groupKey", ""),
                "external_url": payload.get("externalURL", ""),
                "raw_labels": labels,
                "raw_annotations": annotations,
            },
        )

    def _infer_capabilities(self, event: SourceEvent) -> Dict[str, Any]:
        """Alerts typically require the language of the affected service."""
        caps: Dict[str, Any] = {}
        # The service name may hint at language
        service = event.metadata.get("service", "")
        if "python" in service.lower():
            caps["languages"] = ["python"]
        elif "node" in service.lower() or "js" in service.lower():
            caps["languages"] = ["typescript"]
        return caps

    def infer_sop(self, event: SourceEvent) -> Optional[str]:
        """Infer SOP from alert name. Most alerts map to hotfix.

        Args:
            event: Parsed alert event.

        Returns:
            SOP name or None.
        """
        alert_name = event.metadata.get("alert_name", "")
        return _ALERT_SOP.get(alert_name, "hotfix")

    @staticmethod
    def _severity_to_priority(severity: str) -> int:
        """Map AlertManager severity to priority integer."""
        mapping = {
            "critical": 0,
            "error": 0,
            "warning": 1,
            "info": 2,
            "none": 3,
        }
        return mapping.get(severity.lower(), 1)

    @staticmethod
    def _highest_severity(alerts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Pick the alert with the highest severity."""
        severity_order = {"critical": 0, "error": 1, "warning": 2, "info": 3}
        return min(
            alerts,
            key=lambda a: severity_order.get(
                a.get("labels", {}).get("severity", "info"), 99,
            ),
        )
