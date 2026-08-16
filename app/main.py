"""
Idea-to-Video Generator — FastAPI Application Entry Point

A full-stack platform that transforms a topic into a complete video
using AI-powered script generation, voiceover, video clips, and assembly.
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import router
from app.core.config import settings

# ── Configure Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)
# Silence noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# ── Create Application ──
app = FastAPI(
    title="Idea-to-Video Generator",
    description="Transform any topic into a complete video using AI",
    version="1.0.0",
)

# ── Middleware ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Lifecycle Events ──
@app.on_event("startup")
async def startup():
    """Initialize services on application startup."""
    settings.setup_environment()

    # Ensure output directory exists
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("  Idea-to-Video Generator — Starting Up")
    logger.info("  Mock Mode: %s", "ENABLED" if settings.mock_mode else "DISABLED")
    logger.info("=" * 60)


# ── API Routes ──
app.include_router(router)


# ── Health Check ──
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "mock_mode": settings.mock_mode,
    }


# ── Serve Frontend (must be LAST — catches all unmatched routes) ──
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
    logger.info("Frontend served from: %s", frontend_dir)
