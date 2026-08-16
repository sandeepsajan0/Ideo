"""
Video generation service.

Supports:
  - slideshow (FREE) — Generates an image and converts it to a 5-second video clip using FFmpeg
  - veo (PREMIUM) — Google Veo (Gemini API)
  - fal (PREMIUM) — Fal.ai Hunyuan Video API
"""

import asyncio
import logging
from pathlib import Path

from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.services import image_service

logger = logging.getLogger(__name__)

# Map our aspect ratio strings to Fal.ai parameters
ASPECT_RATIO_MAP = {
    "9:16": {"resolution": "720p", "aspect_ratio": "9:16"},
    "16:9": {"resolution": "720p", "aspect_ratio": "16:9"},
    "1:1":  {"resolution": "720p", "aspect_ratio": "1:1"},
}


async def generate_video_clip(
    prompt: str,
    output_path: Path,
    aspect_ratio: str = "9:16",
    engine: str | None = None,
    image_engine: str | None = None,
    duration: float = 5.0,
) -> Path:
    """
    Generate a video clip from a prompt.

    Args:
        prompt: Visual description for the video.
        output_path: Where to save the MP4 file.
        aspect_ratio: One of "9:16", "16:9", "1:1".
        engine: "slideshow" (free), "veo" (premium) or "fal" (premium).
        image_engine: "pollinations", "huggingface", or "fal".

    Returns:
        Path to the saved video file.
    """
    if settings.mock_mode:
        return await _mock_video(output_path)

    selected_engine = engine or settings.video_engine

    if selected_engine == "fal":
        return await _generate_fal(prompt, output_path, aspect_ratio)
    elif selected_engine == "veo":
        return await _generate_veo(prompt, output_path, aspect_ratio)
    else:
        # Default: slideshow (free) with dynamic duration Ken Burns effect
        return await _generate_slideshow(prompt, output_path, aspect_ratio, image_engine=image_engine, duration=duration)


# ─────────────────────────────────────────────
# Engine: Slideshow (FREE)
# ─────────────────────────────────────────────
_ffmpeg_semaphore = asyncio.Semaphore(2)

async def _generate_slideshow(
    prompt: str,
    output_path: Path,
    aspect_ratio: str,
    image_engine: str | None = None,
    duration: float = 5.0,
) -> Path:
    """Generate a dynamic video clip by creating an image and applying a Ken Burns effect with FFmpeg."""
    logger.info("Generating video clip [slideshow]: %s", output_path.name)
    
    # 1. Generate an image using the configured free image engine
    temp_img_path = output_path.with_suffix(".jpg")
    await image_service.generate_thumbnail(
        prompt, 
        temp_img_path, 
        engine=image_engine or settings.image_engine
    )
    
    # 2. Use FFmpeg to apply a Ken Burns pan/zoom effect matching the audio duration
    frames = int(duration * 30)
    
    if aspect_ratio == "9:16":
        # 720x1280
        vf = f"zoompan=z='min(zoom+0.001,1.15)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=720x1280,format=yuv420p"
    elif aspect_ratio == "16:9":
        # 1280x720
        vf = f"zoompan=z='min(zoom+0.001,1.15)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1280x720,format=yuv420p"
    else:
        # 1:1
        vf = f"zoompan=z='min(zoom+0.001,1.15)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=720x720,format=yuv420p"
    
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-framerate", "30",
        "-i", str(temp_img_path),
        "-c:v", "libx264",
        "-preset", "fast",
        "-t", str(duration),
        "-vf", vf,
        str(output_path)
    ]
    
    async with _ffmpeg_semaphore:
        logger.info("Executing FFmpeg for %s", output_path.name)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    
    # Clean up the temp image
    if temp_img_path.exists():
        temp_img_path.unlink()
        
    if not output_path.exists():
        raise RuntimeError("Failed to generate slideshow video clip via FFmpeg")
        
    logger.info("Video clip saved [slideshow]: %s", output_path)
    return output_path


# ─────────────────────────────────────────────
# Engine: Fal.ai (PREMIUM)
# ─────────────────────────────────────────────
async def _generate_fal(
    prompt: str,
    output_path: Path,
    aspect_ratio: str,
) -> Path:
    """Generate video clip using Fal.ai Hunyuan Video (premium, paid API)."""
    import fal_client

    logger.info("Generating video clip [fal]: %s", output_path.name)
    ratio_config = ASPECT_RATIO_MAP.get(aspect_ratio, ASPECT_RATIO_MAP["9:16"])

    result = await fal_client.subscribe_async(
        "fal-ai/hunyuan-video",
        arguments={
            "prompt": prompt,
            **ratio_config,
        },
        with_logs=True,
    )
    video_url = result["video"]["url"]
    await _download_file(video_url, output_path)

    logger.info("Video clip saved [fal]: %s", output_path)
    return output_path


# ─────────────────────────────────────────────
# Engine: Google Veo (Gemini API)
# ─────────────────────────────────────────────
async def _generate_veo(
    prompt: str,
    output_path: Path,
    aspect_ratio: str,
) -> Path:
    """Generate video clip using Google Veo (Gemini API)."""
    from google import genai
    from google.genai import types
    import time

    logger.info("Generating video clip [veo]: %s", output_path.name)
    
    # Map our aspect ratio to Veo's supported formats
    ratio = aspect_ratio if aspect_ratio in ["16:9", "9:16", "1:1"] else "9:16"

    def _sync_call() -> bytes:
        client = genai.Client()  # Automatically uses GEMINI_API_KEY from environment
        
        # Initiate video generation
        operation = client.models.generate_videos(
            model="veo-3.1-generate-preview",
            prompt=prompt,
            config=types.GenerateVideosConfig(
                aspect_ratio=ratio,
            )
        )
        
        # Poll for completion
        while not operation.done:
            logger.info("Waiting for Veo video generation to complete... (%s)", output_path.name)
            time.sleep(10)
            operation = client.operations.get(operation=operation)
            
        if operation.response and operation.response.generated_videos:
            generated_video = operation.response.generated_videos[0]
            video_bytes = client.files.download(file=generated_video.video)
            return video_bytes
        else:
            raise RuntimeError(f"Veo video generation failed: {operation.error}")

    video_bytes = await run_in_threadpool(_sync_call)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(video_bytes)

    logger.info("Video clip saved [veo]: %s", output_path)
    return output_path


# ─────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────
async def _download_file(url: str, output_path: Path) -> None:
    """Download a file from URL."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "curl", "-s", "-L", "-o", str(output_path), url,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    if not output_path.exists():
        raise RuntimeError(f"Failed to download video from {url}")


async def _mock_video(output_path: Path) -> Path:
    """Create a minimal placeholder MP4 video for development (pure Python)."""
    import struct

    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 720, 1280

    def box(box_type: bytes, data: bytes) -> bytes:
        return struct.pack('>I', len(data) + 8) + box_type + data

    sps = bytes([
        0x67, 0x42, 0x00, 0x0a, 0xe9, 0x40, 0x40, 0x04,
        0x00, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0xc8,
        0x40
    ])
    pps = bytes([0x68, 0xce, 0x38, 0x80])
    idr = bytes([0x65, 0x88, 0x80, 0x40, 0x00])

    sample_data = b''
    for nalu in [sps, pps, idr]:
        sample_data += struct.pack('>I', len(nalu)) + nalu

    ftyp = box(b'ftyp', b'isom' + struct.pack('>I', 512) + b'isom' + b'iso2' + b'mp41')

    creation_time = 0
    timescale = 1000
    duration = 5000

    mvhd_data = struct.pack('>I', 0)
    mvhd_data += struct.pack('>II', creation_time, creation_time)
    mvhd_data += struct.pack('>I', timescale)
    mvhd_data += struct.pack('>I', duration)
    mvhd_data += struct.pack('>I', 0x00010000)
    mvhd_data += struct.pack('>H', 0x0100)
    mvhd_data += b'\x00' * 10
    mvhd_data += struct.pack('>9I',
        0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000)
    mvhd_data += b'\x00' * 24
    mvhd_data += struct.pack('>I', 2)
    mvhd = box(b'mvhd', mvhd_data)

    with open(output_path, 'wb') as f:
        f.write(ftyp)
        f.write(box(b'mdat', sample_data))
        f.write(box(b'moov', mvhd))

    logger.info("Mock video created: %s", output_path)
    return output_path
