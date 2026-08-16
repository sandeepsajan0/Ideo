"""
Pipeline orchestrator for the Idea-to-Video generation workflow.

Coordinates all services (script, audio, video, assembly) and emits
real-time progress events via an async event queue.
"""

import asyncio
import logging
import traceback
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.schemas import (
    PipelineEvent,
    ProjectStatus,
    Scene,
    SceneStatus,
    VideoProject,
)
from app.services import (
    assembly_service,
    audio_service,
    image_service,
    script_service,
    video_service,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# In-memory project store and event queues
# ─────────────────────────────────────────────
projects: dict[str, VideoProject] = {}
event_queues: dict[str, list[asyncio.Queue]] = {}


def get_project(project_id: str) -> VideoProject | None:
    """Retrieve a project by ID."""
    return projects.get(project_id)


def list_projects() -> list[VideoProject]:
    """Return all projects, newest first."""
    return sorted(projects.values(), key=lambda p: p.created_at, reverse=True)


def delete_project(project_id: str) -> bool:
    """Remove a project and clean up its event queues."""
    if project_id in projects:
        del projects[project_id]
        event_queues.pop(project_id, None)
        return True
    return False


def subscribe(project_id: str) -> asyncio.Queue:
    """Create a new SSE subscriber queue for a project."""
    queue: asyncio.Queue = asyncio.Queue()
    if project_id not in event_queues:
        event_queues[project_id] = []
    event_queues[project_id].append(queue)
    return queue


def unsubscribe(project_id: str, queue: asyncio.Queue) -> None:
    """Remove an SSE subscriber queue."""
    if project_id in event_queues:
        try:
            event_queues[project_id].remove(queue)
        except ValueError:
            pass


async def _emit(project_id: str, event: PipelineEvent) -> None:
    """Push an event to all subscribers of a project."""
    if project_id in event_queues:
        for queue in event_queues[project_id]:
            await queue.put(event)


# ─────────────────────────────────────────────
# Pipeline Execution
# ─────────────────────────────────────────────
async def run_pipeline(project: VideoProject) -> None:
    """
    Execute the full video generation pipeline.

    Stages:
    1. Generate script (Gemini)
    2. Generate audio + video for each scene (concurrent)
    3. Merge each scene
    4. Assemble final video
    5. Generate thumbnail
    """
    projects[project.id] = project
    project_dir = settings.get_project_dir(project.id)

    try:
        # ── Stage 1: Script Generation ──
        project.status = ProjectStatus.GENERATING_SCRIPT
        project.progress = 5.0
        await _emit(project.id, PipelineEvent(
            project_id=project.id,
            event_type="status_change",
            message="Generating script with AI...",
            data={"status": project.status.value, "progress": project.progress},
        ))

        script_data = await script_service.generate_script(
            topic=project.topic,
            num_scenes=project.num_scenes,
            aspect_ratio=project.aspect_ratio,
            target_duration=project.target_duration,
            tts_engine=project.tts_engine,
            voice_id=project.voice_id,
        )

        # Save script to output folder
        import json
        with open(project_dir / "script.json", "w", encoding="utf-8") as f:
            json.dump(script_data, f, indent=2, ensure_ascii=False)

        # Build scene objects
        project.scenes = [
            Scene(
                index=i,
                narration=scene["narration"],
                visual_prompt=scene["visual_prompt"],
            )
            for i, scene in enumerate(script_data)
        ]

        project.progress = 15.0
        await _emit(project.id, PipelineEvent(
            project_id=project.id,
            event_type="script_ready",
            message=f"Script generated: {len(project.scenes)} scenes",
            data={
                "progress": project.progress,
                "scenes": [s.model_dump() for s in project.scenes],
            },
        ))

        # ── Stage 2: Generate Media (Audio + Video per scene) ──
        project.status = ProjectStatus.GENERATING_MEDIA
        await _emit(project.id, PipelineEvent(
            project_id=project.id,
            event_type="status_change",
            message="Generating audio and video for each scene...",
            data={"status": project.status.value, "progress": project.progress},
        ))

        # Process each scene concurrently
        scene_tasks = []
        for scene in project.scenes:
            task = asyncio.create_task(
                _process_scene(project, scene, project_dir)
            )
            scene_tasks.append(task)

        await asyncio.gather(*scene_tasks)

        # Check if any scene failed
        failed = [s for s in project.scenes if s.status == SceneStatus.FAILED]
        if failed:
            raise RuntimeError(
                f"{len(failed)} scene(s) failed: "
                + ", ".join(s.error or "unknown" for s in failed)
            )

        # ── Stage 3: Assemble Final Video ──
        project.status = ProjectStatus.ASSEMBLING
        project.progress = 85.0
        await _emit(project.id, PipelineEvent(
            project_id=project.id,
            event_type="status_change",
            message="Assembling final video...",
            data={"status": project.status.value, "progress": project.progress},
        ))

        merged_paths = [
            Path(s.merged_path)
            for s in project.scenes
            if s.merged_path
        ]

        final_path = project_dir / "final_output.mp4"
        await assembly_service.assemble_final_video(merged_paths, final_path)
        project.final_video_path = str(final_path)
        project.progress = 95.0

        # ── Stage 4: Generate Thumbnail ──
        await _emit(project.id, PipelineEvent(
            project_id=project.id,
            event_type="status_change",
            message="Generating thumbnail...",
            data={"status": project.status.value, "progress": project.progress},
        ))

        thumbnail_path = project_dir / "thumbnail.png"
        thumbnail_prompt = (
            f"A eye-catching YouTube thumbnail for a video about: {project.topic}. "
            "Bold, vibrant, cinematic style."
        )
        await image_service.generate_thumbnail(thumbnail_prompt, thumbnail_path)
        project.thumbnail_url = f"/api/projects/{project.id}/thumbnail"

        # ── Done ──
        project.status = ProjectStatus.COMPLETED
        project.progress = 100.0
        project.completed_at = datetime.utcnow()

        # Save final project metadata
        with open(project_dir / "project.json", "w", encoding="utf-8") as f:
            f.write(project.model_dump_json(indent=2))

        await _emit(project.id, PipelineEvent(
            project_id=project.id,
            event_type="complete",
            message="Video generation complete!",
            data={
                "status": project.status.value,
                "progress": 100.0,
                "final_video_url": f"/api/projects/{project.id}/download",
                "thumbnail_url": project.thumbnail_url,
            },
        ))

        logger.info("Pipeline completed for project %s", project.id)

    except Exception as e:
        logger.error("Pipeline failed for project %s: %s", project.id, e)
        logger.error(traceback.format_exc())

        project.status = ProjectStatus.FAILED
        project.error = str(e)

        await _emit(project.id, PipelineEvent(
            project_id=project.id,
            event_type="error",
            message=f"Pipeline failed: {e}",
            data={"status": project.status.value, "error": str(e)},
        ))


async def _process_scene(
    project: VideoProject,
    scene: Scene,
    project_dir: Path,
) -> None:
    """
    Process a single scene: generate audio and video concurrently, then merge.
    """
    total_scenes = len(project.scenes)
    base_progress = 15.0
    per_scene_progress = 70.0 / total_scenes  # Distribute 15-85% across scenes

    try:
        scene.status = SceneStatus.GENERATING_MEDIA
        await _emit(project.id, PipelineEvent(
            project_id=project.id,
            event_type="scene_update",
            message=f"Scene {scene.index + 1}: Generating media...",
            data={"scene_index": scene.index, "scene_status": scene.status.value},
        ))

        audio_path = project_dir / f"scene_{scene.index}_audio.mp3"
        video_path = project_dir / f"scene_{scene.index}_video.mp4"

        # Run audio generation first to get its duration for slideshows
        audio_result = await audio_service.generate_audio(
            scene.narration, audio_path,
            voice_id=project.voice_id,
            engine=project.tts_engine,
        )
        
        # Get duration for the video engine to match
        from app.services.assembly_service import get_duration
        audio_duration = await get_duration(Path(audio_result))

        video_result = await video_service.generate_video_clip(
            scene.visual_prompt, video_path, project.aspect_ratio,
            engine=project.video_engine,
            image_engine=project.image_engine,
            duration=audio_duration,
        )

        scene.audio_path = str(audio_result)
        scene.video_path = str(video_result)

        # Merge
        scene.status = SceneStatus.MERGING
        await _emit(project.id, PipelineEvent(
            project_id=project.id,
            event_type="scene_update",
            message=f"Scene {scene.index + 1}: Merging audio and video...",
            data={"scene_index": scene.index, "scene_status": scene.status.value},
        ))

        merged_path = project_dir / f"scene_{scene.index}_merged.mp4"
        await assembly_service.merge_scene(video_path, audio_path, merged_path)
        scene.merged_path = str(merged_path)

        scene.status = SceneStatus.COMPLETED
        project.progress = base_progress + per_scene_progress * (scene.index + 1)

        await _emit(project.id, PipelineEvent(
            project_id=project.id,
            event_type="scene_update",
            message=f"Scene {scene.index + 1}: Complete!",
            data={
                "scene_index": scene.index,
                "scene_status": scene.status.value,
                "progress": project.progress,
            },
        ))

    except Exception as e:
        scene.status = SceneStatus.FAILED
        scene.error = str(e)
        logger.error("Scene %d failed: %s", scene.index, e)
        raise
