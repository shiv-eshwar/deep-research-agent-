"""
api.py — Production FastAPI server for the deep research agent.

Endpoints:
  GET  /health                     → Health check (used by Cloud Run)
  GET  /ready                      → Readiness check (checks API keys)
  POST /research                   → Sync research (returns when done)
  POST /research/stream            → SSE streaming (real-time node updates)
  POST /research/async             → Background job (returns job_id immediately)
  GET  /research/jobs/{job_id}     → Poll job status and result
  GET  /docs                       → Auto-generated API docs (FastAPI built-in)

Production patterns:
  - /health vs /ready distinction (Cloud Run needs both)
  - Background tasks with in-memory job store (swap Redis for real production)
  - Server-Sent Events for real-time streaming to frontend
  - Request ID in all log lines for traceability
  - Proper HTTP status codes and error messages
  - CORS headers for browser access
"""

import os
import uuid
import logging
import asyncio
import json
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from graph import build_graph
from state import create_initial_state

load_dotenv()
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
# APP STARTUP
# ══════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs on startup and shutdown."""
    # Startup: validate environment
    if not os.getenv("OPENAI_API_KEY"):
        logger.critical("OPENAI_API_KEY not set! API will fail on research calls.")
    if os.getenv("LANGCHAIN_API_KEY"):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ.setdefault("LANGCHAIN_PROJECT", "deep-research-agent")
        logger.info("LangSmith tracing enabled")
    logger.info("Deep Research Agent API starting up")
    yield
    logger.info("Deep Research Agent API shutting down")


app = FastAPI(
    title="Deep Research Agent API",
    description=(
        "A production-grade deep research AI agent powered by LangGraph. "
        "Searches the web, synthesizes information, and writes comprehensive reports."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allows browsers to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Lock this down in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════
# REQUEST / RESPONSE MODELS
# ══════════════════════════════════════════════════════════════════

class ResearchRequest(BaseModel):
    query: str = Field(
        min_length=10,
        max_length=500,
        description="The research question to investigate"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "query": "What are the biggest risks and opportunities of AI agents in enterprise software in 2025?"
            }
        }
    }


class JobStatus(BaseModel):
    job_id: str
    status: str           # "queued" | "running" | "completed" | "failed"
    query: str
    created_at: str
    completed_at: Optional[str] = None
    report: Optional[str] = None
    error: Optional[str] = None
    metadata: dict = {}


# ── In-memory job store ───────────────────────────────────────────
# For production: replace with Redis or a database
# Key: job_id, Value: JobStatus dict
jobs: dict[str, dict] = {}


# ══════════════════════════════════════════════════════════════════
# HEALTH ENDPOINTS
# Cloud Run calls these to check if your container is alive
# ══════════════════════════════════════════════════════════════════

@app.get("/health", tags=["Health"])
def health_check():
    """Basic liveness check. Returns 200 if the server is running."""
    return {"status": "healthy", "service": "deep-research-agent", "version": "1.0.0"}


@app.get("/ready", tags=["Health"])
def readiness_check():
    """
    Readiness check. Returns 200 only if the service is ready to handle requests.
    Cloud Run uses this to decide if traffic should be sent to this instance.
    """
    issues = []
    if not os.getenv("OPENAI_API_KEY"):
        issues.append("OPENAI_API_KEY not set")

    if issues:
        raise HTTPException(status_code=503, detail={"issues": issues})

    return {
        "status": "ready",
        "checks": {
            "openai_key": "ok",
            "tavily_key": "ok" if os.getenv("TAVILY_API_KEY") else "missing (optional)",
            "langsmith": "enabled" if os.getenv("LANGCHAIN_API_KEY") else "disabled",
        }
    }


# ══════════════════════════════════════════════════════════════════
# SYNC RESEARCH — Simple request/response
# Warning: research takes 2-5 minutes, may timeout in some clients
# ══════════════════════════════════════════════════════════════════

@app.post("/research", tags=["Research"])
def run_research_sync(request: ResearchRequest):
    """
    Run a full research job synchronously. Waits for completion.
    Best for server-to-server calls where timeouts aren't a concern.
    """
    request_id = str(uuid.uuid4())[:8]
    logger.info(f"[{request_id}] Sync research: {request.query[:60]}")

    try:
        graph = build_graph(use_memory=False)
        final_state = graph.invoke(create_initial_state(request.query))

        return {
            "request_id": request_id,
            "status": "completed",
            "query": request.query,
            "report": final_state.get("final_report", ""),
            "metadata": {
                "research_iterations": final_state.get("research_iterations", 0),
                "revision_count": final_state.get("revision_count", 0),
                "sources_found": len(final_state.get("search_results", [])),
                "coverage_score": final_state.get("reflection", {}).get("coverage_score"),
                "quality_score": final_state.get("critique", {}).get("quality_score"),
            }
        }
    except Exception as e:
        logger.error(f"[{request_id}] Research failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════
# STREAMING RESEARCH — Server-Sent Events
# Real-time updates as each node completes
# ══════════════════════════════════════════════════════════════════

@app.post("/research/stream", tags=["Research"])
def stream_research(request: ResearchRequest):
    """
    Run research with real-time streaming via Server-Sent Events (SSE).
    Each graph node sends an update as it completes.

    How to consume in JavaScript:
      const es = new EventSource('/research/stream');
      es.onmessage = (e) => console.log(JSON.parse(e.data));
    """

    def event_generator():
        request_id = str(uuid.uuid4())[:8]
        try:
            # Send start event
            yield _sse_event({"type": "start", "request_id": request_id,
                              "query": request.query})

            graph = build_graph(use_memory=True)
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}

            yield _sse_event({"type": "thread_created", "thread_id": thread_id})

            # Stream node updates
            for chunk in graph.stream(
                create_initial_state(request.query),
                config=config,
                stream_mode="updates"
            ):
                node_name = list(chunk.keys())[0]
                node_data = chunk[node_name]

                event = {
                    "type": "node_complete",
                    "node": node_name,
                    "status": node_data.get("status", ""),
                }

                # Add relevant output previews
                if node_name == "planner":
                    sqs = node_data.get("sub_questions", [])
                    event["sub_questions"] = [sq["question"] for sq in sqs]

                elif node_name == "searcher":
                    event["sources_found"] = len(node_data.get("search_results", []))
                    event["iteration"] = node_data.get("research_iterations", 0)

                elif node_name == "reflector":
                    ref = node_data.get("reflection", {})
                    event["coverage_score"] = ref.get("coverage_score", 0)
                    event["is_sufficient"] = ref.get("is_sufficient", False)
                    event["gaps"] = ref.get("gaps", [])

                elif node_name == "writer":
                    draft = node_data.get("draft_report", "")
                    event["word_count"] = len(draft.split()) if draft else 0
                    event["revision"] = node_data.get("revision_count", 1)

                elif node_name == "critic":
                    critique = node_data.get("critique", {})
                    event["quality_score"] = critique.get("quality_score", 0)
                    event["approved"] = bool(node_data.get("final_report"))
                    if node_data.get("final_report"):
                        event["report"] = node_data["final_report"]

                yield _sse_event(event)

            yield _sse_event({"type": "completed"})

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield _sse_event({"type": "error", "message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


def _sse_event(data: dict) -> str:
    """Format a dict as an SSE event string."""
    return f"data: {json.dumps(data)}\n\n"


# ══════════════════════════════════════════════════════════════════
# ASYNC / BACKGROUND JOB RESEARCH
# Returns job_id immediately, runs in background, client polls for result
# ══════════════════════════════════════════════════════════════════

@app.post("/research/async", response_model=JobStatus, tags=["Research"])
def start_async_research(request: ResearchRequest, background_tasks: BackgroundTasks):
    """
    Start a research job in the background. Returns a job_id immediately.
    Poll GET /research/jobs/{job_id} for status and results.
    """
    job_id = str(uuid.uuid4())

    job: dict = {
        "job_id": job_id,
        "status": "queued",
        "query": request.query,
        "created_at": datetime.utcnow().isoformat(),
        "completed_at": None,
        "report": None,
        "error": None,
        "metadata": {},
    }
    jobs[job_id] = job

    background_tasks.add_task(_run_research_background, job_id, request.query)

    return JobStatus(**job)


def _run_research_background(job_id: str, query: str):
    """Runs in a background thread. Updates jobs dict when complete."""
    jobs[job_id]["status"] = "running"
    try:
        graph = build_graph(use_memory=False)
        final_state = graph.invoke(create_initial_state(query))

        jobs[job_id].update({
            "status": "completed",
            "report": final_state.get("final_report", ""),
            "completed_at": datetime.utcnow().isoformat(),
            "metadata": {
                "research_iterations": final_state.get("research_iterations", 0),
                "revision_count": final_state.get("revision_count", 0),
                "sources_found": len(final_state.get("search_results", [])),
            }
        })
    except Exception as e:
        logger.error(f"Background job {job_id} failed: {e}")
        jobs[job_id].update({
            "status": "failed",
            "error": str(e),
            "completed_at": datetime.utcnow().isoformat(),
        })


@app.get("/research/jobs/{job_id}", response_model=JobStatus, tags=["Research"])
def get_job_status(job_id: str):
    """Get the status and result of an async research job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return JobStatus(**jobs[job_id])
