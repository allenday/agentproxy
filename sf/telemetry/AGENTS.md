# sf/telemetry/ — Telemetry Wiring

Purpose: OpenTelemetry enablement and event enrichment wiring.

Main entry points:
- `get_telemetry()` in `sf/telemetry.py`
- Event enrichment in `sf/event_processors/`

Where to look:
- **Collector templates:** `examples/otel-stack/`
- **Runtime env vars:** `README.md` (Observability section)
- **SOP + fixtures:** `sf/workstation/` (see `sf/workstation/AGENTS.md`)
