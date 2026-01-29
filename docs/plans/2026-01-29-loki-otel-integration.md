# Loki + OTEL Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add first-class Loki log export alongside existing OTEL traces/metrics and bake branch/commit/push/PR steps into the SOP so dogfooding runs can be pulled and observed end-to-end.

**Architecture:** Keep OTEL traces/metrics as-is; add a Loki log exporter with minimal configuration (endpoint, tenant, labels). Use provider-agnostic logging hooks (PA/ShopFloor/Workstation) to emit structured JSON to Loki via HTTP push. Document a standard git workflow (branch naming, commit cadence, push, PR) in AGENTS/SOP.

**Tech Stack:** Python, OTEL SDK (already present), requests (for Loki HTTP), git.

---

## Backlog (checkboxes + deps)

- [ ] (T1) Git workflow SOP doc  
  - Files: `AGENTS.md`, `docs/WORKFLOW_GIT.md` (and `sf/AGENTS.md` if needed)  
  - Dep: none
- [ ] (T2) Loki config surface (env/CLI flags, README)  
  - Files: `sf/telemetry.py`, `sf/cli.py`, `README.md`  
  - Dep: T1
- [ ] (T3) Loki exporter helper (HTTP push)  
  - Files: `sf/telemetry.py`, `sf/telemetry_loki.py`  
  - Dep: T2
- [ ] (T4) Instrument PA/ShopFloor/QA events -> Loki helper  
  - Files: `sf/pa.py`, `sf/shopfloor/shopfloor.py`, `sf/workstation/quality_gate.py`  
  - Dep: T3
- [ ] (T5) Tests + dogfood command  
  - Files: `tests/unit/test_telemetry_loki.py`, `tests/integration/test_shopfloor_e2e.py`, `README.md`  
  - Dep: T3
- [ ] (T6) Final verify, branch push, PR  
  - Steps: install + pytest, commit, push `feat/loki-otel`, open PR  
  - Dep: T4, T5
