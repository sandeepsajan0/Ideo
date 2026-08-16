"""
Pydantic schemas for API requests, responses, and internal project state.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────
class ProjectStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATING_SCRIPT = "generating_script"
    GENERATING_MEDIA = "generating_media"
    ASSEMBLING = "assembling"
    COMPLETED = "completed"
    FAILED = "failed"


class SceneStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATING_AUDIO = "generating_audio"
    GENERATING_VIDEO = "generating_video"
    GENERATING_MEDIA = "generating_media"
    MERGING = "merging"
    COMPLETED = "completed"
    FAILED = "failed"


# ─────────────────────────────────────────────
# Request Models
# ─────────────────────────────────────────────
class VideoRequest(BaseModel):
    """Incoming request to generate a video from a topic."""
    topic: str = Field(..., min_length=3, max_length=500, description="The topic for the video")
    aspect_ratio: str = Field(default="9:16", description="9:16 | 16:9 | 1:1")
    target_duration: int = Field(default=2, description="Target video duration in minutes")
    num_scenes: int = Field(default=3, ge=2, le=8, description="Number of scenes (2-8)")
    tts_engine: str = Field(default="edge", description="TTS engine: 'edge' (free) or 'elevenlabs' (premium)")
    video_engine: str = Field(default="slideshow", description="Video engine: 'slideshow' (free) or 'fal' (premium)")
    image_engine: str = Field(default="pollinations", description="Image engine: 'pollinations', 'huggingface', or 'fal'")
    voice_id: Optional[str] = Field(default=None, description="Voice ID override (engine-specific)")


class SceneEditRequest(BaseModel):
    """Request to edit and regenerate a single scene."""
    narration: Optional[str] = None
    visual_prompt: Optional[str] = None


# ─────────────────────────────────────────────
# Internal / Response Models
# ─────────────────────────────────────────────
class Scene(BaseModel):
    """A single scene within a video project."""
    index: int = 0
    narration: str = ""
    visual_prompt: str = ""
    audio_path: Optional[str] = None
    video_path: Optional[str] = None
    merged_path: Optional[str] = None
    status: SceneStatus = SceneStatus.PENDING
    error: Optional[str] = None


class VideoProject(BaseModel):
    """Full state of a video generation project."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    topic: str = ""
    aspect_ratio: str = "9:16"
    target_duration: int = 2
    num_scenes: int = 3
    tts_engine: str = "edge"
    video_engine: str = "slideshow"
    image_engine: str = "pollinations"
    voice_id: str = ""
    status: ProjectStatus = ProjectStatus.PENDING
    progress: float = 0.0  # 0.0 – 100.0
    scenes: list[Scene] = Field(default_factory=list)
    final_video_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class ProjectSummary(BaseModel):
    """Lightweight project info for listing."""
    id: str
    topic: str
    status: ProjectStatus
    progress: float
    created_at: datetime
    completed_at: Optional[datetime] = None
    thumbnail_url: Optional[str] = None


# ─────────────────────────────────────────────
# SSE Event Model
# ─────────────────────────────────────────────
class PipelineEvent(BaseModel):
    """A single progress event emitted via SSE."""
    project_id: str
    event_type: str  # e.g. "status_change", "scene_update", "progress", "error", "complete"
    message: str = ""
    data: Optional[dict] = None
