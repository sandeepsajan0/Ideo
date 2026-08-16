"""
API router for the Idea-to-Video Generator.

Provides REST endpoints for project management and SSE streaming
for real-time pipeline progress.
"""

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.schemas import (
    PipelineEvent,
    ProjectSummary,
    SceneEditRequest,
    VideoProject,
    VideoRequest,
)
from app.services import pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


# ─────────────────────────────────────────────
# Create & List Projects
# ─────────────────────────────────────────────
@router.post("/projects", response_model=VideoProject, status_code=201)
async def create_project(request: VideoRequest):
    """
    Create a new video project and start the generation pipeline.

    The pipeline runs in the background. Use the SSE stream endpoint
    to monitor progress in real time.
    """
    project = VideoProject(
        topic=request.topic,
        aspect_ratio=request.aspect_ratio,
        target_duration=request.target_duration,
        num_scenes=request.num_scenes,
        tts_engine=request.tts_engine,
        video_engine=request.video_engine,
        image_engine=request.image_engine,
        voice_id=request.voice_id or (
            settings.default_voice_id if request.tts_engine == "elevenlabs"
            else settings.default_edge_voice
        ),
    )

    # Store the project immediately
    pipeline.projects[project.id] = project

    # Start the pipeline as a background task
    asyncio.create_task(pipeline.run_pipeline(project))

    logger.info("Project created: %s (topic=%s)", project.id, project.topic)
    return project


@router.get("/projects", response_model=list[ProjectSummary])
async def list_projects():
    """List all video projects with summary info."""
    return [
        ProjectSummary(
            id=p.id,
            topic=p.topic,
            status=p.status,
            progress=p.progress,
            created_at=p.created_at,
            completed_at=p.completed_at,
            thumbnail_url=p.thumbnail_url,
        )
        for p in pipeline.list_projects()
    ]


# ─────────────────────────────────────────────
# Get / Delete Project
# ─────────────────────────────────────────────
@router.get("/projects/{project_id}", response_model=VideoProject)
async def get_project(project_id: str):
    """Get full details of a video project."""
    project = pipeline.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a project and its generated assets."""
    if not pipeline.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    # Clean up files
    project_dir = Path(settings.output_dir) / project_id
    if project_dir.exists():
        import shutil
        shutil.rmtree(project_dir, ignore_errors=True)

    return {"message": "Project deleted"}


# ─────────────────────────────────────────────
# SSE Stream for Real-Time Progress
# ─────────────────────────────────────────────
@router.get("/projects/{project_id}/stream")
async def stream_project(project_id: str):
    """
    Server-Sent Events stream for real-time pipeline progress.

    Events include: status_change, script_ready, scene_update, progress, complete, error
    """
    project = pipeline.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    queue = pipeline.subscribe(project_id)

    async def event_generator():
        try:
            # Send current state immediately
            yield {
                "event": "connected",
                "data": json.dumps({
                    "project_id": project_id,
                    "status": project.status.value,
                    "progress": project.progress,
                }),
            }

            while True:
                try:
                    event: PipelineEvent = await asyncio.wait_for(
                        queue.get(), timeout=30.0
                    )
                    yield {
                        "event": event.event_type,
                        "data": json.dumps({
                            "message": event.message,
                            **(event.data or {}),
                        }),
                    }

                    # Close stream on completion or error
                    if event.event_type in ("complete", "error"):
                        break

                except asyncio.TimeoutError:
                    # Send keepalive
                    yield {"event": "ping", "data": "{}"}

        finally:
            pipeline.unsubscribe(project_id, queue)

    return EventSourceResponse(event_generator())


# ─────────────────────────────────────────────
# Download & Serve Assets
# ─────────────────────────────────────────────
@router.get("/projects/{project_id}/download")
async def download_video(project_id: str):
    """Download the final generated video."""
    project = pipeline.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.final_video_path:
        raise HTTPException(status_code=400, detail="Video not yet generated")

    video_path = Path(project.final_video_path)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")

    return FileResponse(
        path=video_path,
        media_type="video/mp4",
        filename=f"{project.topic[:50].replace(' ', '_')}_video.mp4",
    )


@router.get("/projects/{project_id}/thumbnail")
async def get_thumbnail(project_id: str):
    """Get the project thumbnail image."""
    project_dir = Path(settings.output_dir) / project_id
    thumbnail_path = project_dir / "thumbnail.png"

    if not thumbnail_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    return FileResponse(path=thumbnail_path, media_type="image/png")


# ─────────────────────────────────────────────
# Scene Editing
# ─────────────────────────────────────────────
@router.put("/projects/{project_id}/scenes/{scene_index}")
async def edit_scene(project_id: str, scene_index: int, edit: SceneEditRequest):
    """
    Edit a scene's narration or visual prompt and trigger re-generation.
    """
    project = pipeline.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if scene_index < 0 or scene_index >= len(project.scenes):
        raise HTTPException(status_code=400, detail="Invalid scene index")

    scene = project.scenes[scene_index]

    if edit.narration is not None:
        scene.narration = edit.narration
    if edit.visual_prompt is not None:
        scene.visual_prompt = edit.visual_prompt

    return {"message": "Scene updated", "scene": scene.model_dump()}


# ─────────────────────────────────────────────
# Voice Listing
# ─────────────────────────────────────────────
@router.get("/voices")
async def list_voices(language: str = "en"):
    """List available edge-tts voices for a given language prefix."""
    from app.services.audio_service import list_edge_voices
    voices = await list_edge_voices(language)
    return {"engine": "edge", "voices": voices}


# ─────────────────────────────────────────────
# Dummy Endpoints (to silence rogue 404s from old tabs)
# ─────────────────────────────────────────────
@router.get("/dashboard/stats")
async def dummy_dashboard_stats():
    """Dummy endpoint to catch rogue requests from old browser tabs."""
    return {}

