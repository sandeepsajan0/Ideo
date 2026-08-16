"""
Application settings loaded from environment variables / .env file.
"""

import os
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration for the Idea-to-Video Generator."""

    # ── API Keys ──
    gemini_api_key: str = ""
    elevenlabs_api_key: str = ""  # Only needed if tts_engine="elevenlabs"
    fal_key: str = ""
    hf_token: str = ""  # Only needed if image_engine="huggingface"

    # ── TTS Engine ──
    tts_engine: str = "edge"  # "edge" (free) or "elevenlabs" (premium)
    default_edge_voice: str = "en-US-GuyNeural"
    default_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"

    # ── Media Engines ──
    video_engine: str = "slideshow"  # "slideshow" (free), "veo" (premium) or "fal" (premium)
    image_engine: str = "pollinations"  # "pollinations" (free), "huggingface" (free), or "fal" (premium)

    # ── Defaults ──
    default_num_scenes: int = 3
    default_aspect_ratio: str = "9:16"  # 9:16 | 16:9 | 1:1

    # ── Paths ──
    output_dir: str = "output"

    # ── Feature Flags ──
    mock_mode: bool = False

    class Config:
        # Load .env from the project root (one level above 'app')
        env_file = str(Path(__file__).parent.parent.parent / ".env")
        env_file_encoding = "utf-8"

    def setup_environment(self) -> None:
        """Push API keys into os.environ so third-party SDKs can pick them up."""
        if self.gemini_api_key:
            os.environ.setdefault("GEMINI_API_KEY", self.gemini_api_key)
        if self.elevenlabs_api_key:
            os.environ.setdefault("ELEVENLABS_API_KEY", self.elevenlabs_api_key)
        if self.fal_key:
            os.environ.setdefault("FAL_KEY", self.fal_key)
        if self.hf_token:
            os.environ.setdefault("HF_TOKEN", self.hf_token)

    def get_project_dir(self, project_id: str) -> Path:
        """Return (and create) the output directory for a specific project."""
        p = Path(self.output_dir) / project_id
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
