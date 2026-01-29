#!/usr/bin/env python3
"""
PA Web Server

Exposes PA functionality via HTTP API with Server-Sent Events (SSE) for streaming.

Endpoints:
    POST /task          - Start a new task (returns SSE stream)
    GET  /sessions      - List all sessions
    GET  /session/{id}  - Get session details
    POST /stop          - Stop current task

Usage:
    python server.py                    # Start server on port 8000
    python server.py --port 8080        # Custom port
    uvicorn server:app --reload         # Development mode
"""

import argparse
import asyncio
import json
import os
from typing import Optional, AsyncGenerator
from threading import Thread
from queue import Queue, Empty

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .pa import PA, create_pa, list_sessions, OutputEvent, EventType
from .telemetry import get_telemetry


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title="PA Server",
    description="Proxy Agent - AI supervisor for Claude Code",
    version="1.0.0",
)

# Enable CORS for web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auto-instrument FastAPI if telemetry enabled
telemetry = get_telemetry()
telemetry.instrument_fastapi(app)


# =============================================================================
# Request/Response Models
# =============================================================================

class ScreenshotInput(BaseModel):
    """Screenshot with optional description."""
    path: str
    description: Optional[str] = None


class TaskRequest(BaseModel):
    """Request to start a new task."""
    task: str
    working_dir: str = "./sandbox"
    session_id: Optional[str] = None
    mission: Optional[str] = None
    max_iterations: int = 100
    screenshots: Optional[list[ScreenshotInput]] = None
    context_type: str = "auto"
    repo_url: str = ""


class SessionResponse(BaseModel):
    """Session information."""
    session_id: str
    mission: Optional[str]
    task_count: int
    last_active: str


class StopRequest(BaseModel):
    """Request to stop a task."""
    session_id: str


# =============================================================================
# Global State
# =============================================================================

# Track active PA instances by session
active_sessions: dict[str, PA] = {}

# Webhook → ShopFloor queue
from .shopfloor.queue import WorkOrderQueue
from .shopfloor.models import WorkOrder

webhook_queue = WorkOrderQueue()
_next_wo_index = 0
_wo_index_lock = __import__("threading").Lock()


def _next_index() -> int:
    global _next_wo_index
    with _wo_index_lock:
        idx = _next_wo_index
        _next_wo_index += 1
        return idx


# =============================================================================
# SSE Streaming
# =============================================================================

def event_to_sse(event: OutputEvent) -> str:
    """Convert OutputEvent to SSE format."""
    data = {
        "type": event.event_type.value,
        "content": event.content,
        "metadata": event.metadata or {},
    }
    return f"data: {json.dumps(data)}\n\n"


async def stream_task(
    task: str,
    working_dir: str,
    session_id: Optional[str],
    mission: Optional[str],
    max_iterations: int,
    screenshots: Optional[list[ScreenshotInput]] = None,
    context_type: str = "auto",
    repo_url: str = "",
) -> AsyncGenerator[str, None]:
    """
    Stream task execution as SSE events.
    
    Runs PA in a background thread and yields events as they arrive.
    """
    # Create event queue for thread communication
    event_queue: Queue = Queue()
    
    def run_pa():
        """Run PA in background thread."""
        try:
            # Create working directory if needed
            if not os.path.exists(working_dir):
                os.makedirs(working_dir)
            
            # Create PA instance
            pa = create_pa(
                working_dir=working_dir,
                session_id=session_id,
                user_mission=mission,
                claude_bin=os.getenv("CLAUDE_BIN"),
                context_type=context_type,
                repo_url=repo_url,
            )
            
            # Attach screenshots if provided
            if screenshots:
                for ss in screenshots:
                    desc = ss.description or ss.path.split("/")[-1].replace("_", " ").replace("-", " ")
                    pa.memory.session.add_screenshot(ss.path, desc)
                    event_queue.put(OutputEvent(
                        event_type=EventType.TEXT,
                        content=f"📸 Attached screenshot: {ss.path}",
                        metadata={"screenshot": ss.path},
                    ))
            
            # Track active session
            active_sessions[pa.session_id] = pa
            
            # Send session info as first event
            event_queue.put(OutputEvent(
                event_type=EventType.TEXT,
                content=f"Session: {pa.session_id}",
                metadata={"session_id": pa.session_id},
            ))
            
            # Run task and queue events
            for event in pa.run_task(task, max_iterations=max_iterations):
                event_queue.put(event)
            
            # Signal completion
            event_queue.put(None)
            
            # Cleanup
            if pa.session_id in active_sessions:
                del active_sessions[pa.session_id]
                
        except Exception as e:
            event_queue.put(OutputEvent(
                event_type=EventType.ERROR,
                content=f"Server error: {str(e)}",
                metadata={"error": str(e)},
            ))
            event_queue.put(None)
    
    # Start PA in background thread
    thread = Thread(target=run_pa, daemon=True)
    thread.start()
    
    # Yield events as they arrive
    while True:
        try:
            # Check for events with timeout to allow async cancellation
            event = await asyncio.get_event_loop().run_in_executor(
                None, lambda: event_queue.get(timeout=0.1)
            )
            
            if event is None:
                # Stream complete
                break
            
            yield event_to_sse(event)
            
        except Empty:
            # No event yet, continue waiting
            continue
        except asyncio.CancelledError:
            # Client disconnected
            break
    
    # Send final SSE event
    yield "data: {\"type\": \"done\"}\n\n"


# =============================================================================
# API Endpoints
# =============================================================================

@app.post("/task")
async def start_task(request: TaskRequest):
    """
    Start a new task with SSE streaming.
    
    Returns a stream of events as the task executes.
    """
    return StreamingResponse(
        stream_task(
            task=request.task,
            working_dir=request.working_dir,
            session_id=request.session_id,
            mission=request.mission,
            max_iterations=request.max_iterations,
            screenshots=request.screenshots,
            context_type=request.context_type,
            repo_url=request.repo_url,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/sessions")
async def get_sessions():
    """List all available sessions."""
    sessions = list_sessions()
    return {"sessions": sessions}


@app.get("/session/{session_id}")
async def get_session(session_id: str):
    """Get details for a specific session."""
    sessions = list_sessions()
    for s in sessions:
        if s.get("session_id", "").startswith(session_id):
            return s
    raise HTTPException(status_code=404, detail="Session not found")


@app.post("/stop")
async def stop_task(request: StopRequest):
    """Stop a running task."""
    session_id = request.session_id
    
    # Find matching session
    for sid, pa in active_sessions.items():
        if sid.startswith(session_id):
            pa.stop()
            return {"status": "stopped", "session_id": sid}
    
    raise HTTPException(status_code=404, detail="Active session not found")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "active_sessions": len(active_sessions),
    }


# =============================================================================
# Webhook Endpoints (Phase 5: External Work Order Sources)
# =============================================================================

class WebhookResponse(BaseModel):
    """Response from webhook endpoints."""
    accepted: bool
    source_type: str
    source_ref: Optional[str] = None
    message: str = ""


@app.post("/webhook/github")
async def webhook_github(payload: dict):
    """Receive GitHub webhook events (issues, PRs).

    Configure in GitHub repo Settings > Webhooks:
      URL: https://<host>/webhook/github
      Content type: application/json
      Events: Issues, Pull requests
    """
    from .sources.github_adapter import GitHubSourceAdapter

    adapter = GitHubSourceAdapter()
    event = adapter.parse_event(payload)

    if event is None:
        return WebhookResponse(
            accepted=False,
            source_type="github",
            message="Event not actionable (ignored action/type)",
        )

    wo_params = adapter.to_work_order_params(event)
    wo = WorkOrder(index=_next_index(), **wo_params)
    webhook_queue.enqueue(wo)

    # Record source metric
    _record_source_event("github", accepted=True)

    return WebhookResponse(
        accepted=True,
        source_type="github",
        source_ref=event.source_ref,
        message=f"WorkOrder created from {event.source_ref}: {event.title[:80]}",
    )


@app.post("/webhook/jira")
async def webhook_jira(payload: dict):
    """Receive Jira webhook events (issue created/updated).

    Configure in Jira Settings > System > WebHooks:
      URL: https://<host>/webhook/jira
      Events: Issue created, Issue updated
    """
    from .sources.jira_adapter import JiraSourceAdapter

    adapter = JiraSourceAdapter()
    event = adapter.parse_event(payload)

    if event is None:
        return WebhookResponse(
            accepted=False,
            source_type="jira",
            message="Event not actionable (ignored event type or status)",
        )

    wo_params = adapter.to_work_order_params(event)
    wo = WorkOrder(index=_next_index(), **wo_params)
    webhook_queue.enqueue(wo)

    _record_source_event("jira", accepted=True)

    return WebhookResponse(
        accepted=True,
        source_type="jira",
        source_ref=event.source_ref,
        message=f"WorkOrder created from {event.source_ref}: {event.title[:80]}",
    )


@app.post("/webhook/alert")
async def webhook_alert(payload: dict):
    """Receive Prometheus AlertManager webhook events.

    Configure in AlertManager config:
      receivers:
        - name: sf
          webhook_configs:
            - url: https://<host>/webhook/alert
    """
    from .sources.alert_adapter import AlertSourceAdapter

    adapter = AlertSourceAdapter()
    event = adapter.parse_event(payload)

    if event is None:
        return WebhookResponse(
            accepted=False,
            source_type="telemetry",
            message="No firing alerts in payload",
        )

    wo_params = adapter.to_work_order_params(event)
    wo = WorkOrder(index=_next_index(), **wo_params)
    webhook_queue.enqueue(wo)

    _record_source_event("telemetry", accepted=True)

    return WebhookResponse(
        accepted=True,
        source_type="telemetry",
        source_ref=event.source_ref,
        message=f"Maintenance WO created from {event.source_ref}: {event.title[:80]}",
    )


@app.get("/queue")
async def get_queue():
    """Inspect the webhook work order queue."""
    return {
        "size": webhook_queue.size,
        "empty": webhook_queue.empty,
        "next": webhook_queue.peek().model_dump(mode="json") if not webhook_queue.empty else None,
    }


class ProduceRequest(BaseModel):
    """Request to drain the webhook queue through ShopFloor."""
    working_dir: str = "./sandbox"
    max_iterations: int = 100
    context_type: str = "auto"
    repo_url: str = ""


@app.post("/produce")
async def produce(request: ProduceRequest):
    """Drain the webhook queue through ShopFloor as an SSE stream.

    Builds synthetic breakdown text from queued WOs, creates PA in
    ShopFloor mode, and streams ShopFloor.produce() events.
    """
    if webhook_queue.empty:
        raise HTTPException(status_code=404, detail="Webhook queue is empty")

    # Drain all queued WOs
    work_orders = webhook_queue.dequeue_batch(max_size=100)
    if not work_orders:
        raise HTTPException(status_code=404, detail="No work orders to process")

    # Build synthetic breakdown text matching parse_work_orders() format
    lines = []
    for wo in work_orders:
        deps = f" (depends: {','.join(str(d) for d in wo.depends_on)})" if wo.depends_on else ""
        lines.append(f"{wo.index}. {wo.prompt}{deps}")
    breakdown_text = "\n".join(lines)
    task = f"Process {len(work_orders)} queued work orders"

    async def stream_produce():
        event_queue: Queue = Queue()

        def run_shopfloor():
            try:
                if not os.path.exists(request.working_dir):
                    os.makedirs(request.working_dir)

                pa = create_pa(
                    working_dir=request.working_dir,
                    claude_bin=os.getenv("CLAUDE_BIN"),
                    context_type=request.context_type,
                    repo_url=request.repo_url,
                    use_shopfloor=True,
                )

                from .shopfloor import ShopFloor
                from .workstation.quality_gate import VerificationGate

                sf = pa._shopfloor
                if sf is None:
                    sf = ShopFloor(pa=pa)
                    sf.quality_gates.append(VerificationGate())

                for event in sf.produce(task, breakdown_text, request.max_iterations):
                    event_queue.put(event)

                event_queue.put(None)
            except Exception as e:
                event_queue.put(OutputEvent(
                    event_type=EventType.ERROR,
                    content=f"ShopFloor error: {e}",
                    metadata={"error": str(e)},
                ))
                event_queue.put(None)

        thread = Thread(target=run_shopfloor, daemon=True)
        thread.start()

        while True:
            try:
                event = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: event_queue.get(timeout=0.1)
                )
                if event is None:
                    break
                yield event_to_sse(event)
            except Empty:
                continue
            except asyncio.CancelledError:
                break

        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        stream_produce(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _record_source_event(source_type: str, accepted: bool) -> None:
    """Record source adapter metrics."""
    try:
        telemetry = get_telemetry()
        if telemetry.enabled and hasattr(telemetry, "source_events_received"):
            telemetry.source_events_received.add(1, {"source_type": source_type})
            if accepted and hasattr(telemetry, "source_events_accepted"):
                telemetry.source_events_accepted.add(1, {"source_type": source_type})
    except Exception:
        pass


# =============================================================================
# Main
# =============================================================================

def main():
    """Run the server."""
    # Load .env file if present (for telemetry and other config)
    # Override=True ensures .env values take precedence over shell environment
    try:
        from dotenv import load_dotenv
        from pathlib import Path
        # Load from project root .env
        env_path = Path.cwd() / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=True)
    except ImportError:
        # python-dotenv not installed, skip
        pass

    parser = argparse.ArgumentParser(description="PA Web Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()
    
    import uvicorn
    uvicorn.run(
        "sf.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
