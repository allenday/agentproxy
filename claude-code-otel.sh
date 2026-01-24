#!/bin/sh
# Run Claude Code with upstream OTEL telemetry pointed at bastion.
# Uses Claude Code's built-in OTel exporters to our collector.
# Defaults baked in; override via env if desired.

set -eu

export OTEL_SERVICE_NAMESPACE=${OTEL_SERVICE_NAMESPACE:-dev}
export OTEL_SERVICE_NAME="${OTEL_SERVICE_NAME:-claude-code}"

###

export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_METRICS_EXPORTER="${OTEL_METRICS_EXPORTER:-otlp}"
export OTEL_LOGS_EXPORTER="${OTEL_LOGS_EXPORTER:-otlp}"

export OTEL_EXPORTER_OTLP_PROTOCOL="${OTEL_EXPORTER_OTLP_PROTOCOL:-grpc}"
export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://100.91.20.46:4317}"

export OTEL_EXPORTER_OTLP_LOGS_PROTOCOL="${OTEL_EXPORTER_OTLP_LOGS_PROTOCOL:-grpc}"
export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT="${OTEL_EXPORTER_OTLP_LOGS_ENDPOINT:-http://100.91.20.46:4317}"

export OTEL_EXPORTER_OTLP_METRICS_PROTOCOL="${OTEL_EXPORTER_OTLP_METRICS_PROTOCOL:-grpc}"
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="${OTEL_EXPORTER_OTLP_LOGS_ENDPOINT:-http://100.91.20.46:4317}"

export OTEL_METRIC_EXPORT_INTERVAL="${OTEL_METRIC_EXPORT_INTERVAL:-10000}"
export OTEL_LOGS_EXPORT_INTERVAL="${OTEL_LOGS_EXPORT_INTERVAL:-5000}"

# Resource tagging for multi-tenant dashboards
_resource_attrs="service.name=${OTEL_SERVICE_NAME},service.namespace=${OTEL_SERVICE_NAMESPACE},host.name=${HOSTNAME}"
if [ -n "${CLAUDE_OWNER_ID:-}" ]; then
  _resource_attrs="$_resource_attrs,claude.owner_id=${CLAUDE_OWNER_ID}"
else
  # fall back to current user if no explicit owner is provided
  _user="$(whoami 2>/dev/null || true)"
  if [ -n "$_user" ]; then
    _resource_attrs="$_resource_attrs,claude.owner_id=${_user}"
  fi
fi
export OTEL_RESOURCE_ATTRIBUTES="${OTEL_RESOURCE_ATTRIBUTES:-${_resource_attrs}}"

export CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.claude/local/claude}"

exec "$CLAUDE_BIN" "$@"

