"""
Video assembly service using FFmpeg.

Handles merging audio + video for individual scenes and
concatenating all scenes into a final video.
In mock mode, it creates placeholder files without requiring FFmpeg.
"""

import asyncio
import logging
import shutil
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


async def merge_scene(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """
    Merge a video clip with its audio narration.

    The video is looped if shorter than the audio, and the result
    is trimmed to the audio duration.

    Args:
        video_path: Path to the video clip (MP4).
        audio_path: Path to the audio file (MP3/WAV).
        output_path: Where to save the merged file.

    Returns:
        Path to the merged video file.
    """
    logger.info("Merging scene: %s + %s", video_path.name, audio_path.name)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if settings.mock_mode:
        # In mock mode, just copy the video file as the "merged" output
        shutil.copy2(video_path, output_path)
        logger.info("Mock merge: copied %s -> %s", video_path.name, output_path.name)
        return output_path

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(video_path),   # Loop video
        "-i", str(audio_path),                           # Audio input
        "-map", "0:v:0", "-map", "1:a:0",               # Map streams
        "-c:v", "libx264", "-preset", "fast",            # Re-encode video
        "-c:a", "aac", "-b:a", "128k",                  # Encode audio
        "-shortest",                                      # Stop at shortest stream
        "-movflags", "+faststart",                        # Web-optimized
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode() if stderr else "Unknown FFmpeg error"
        raise RuntimeError(f"FFmpeg merge failed: {error_msg}")

    logger.info("Scene merged: %s", output_path)
    return output_path


async def assemble_final_video(
    scene_files: list[Path],
    output_path: Path,
) -> Path:
    """
    Concatenate multiple scene videos into one final video.

    Args:
        scene_files: Ordered list of merged scene MP4 paths.
        output_path: Where to save the final video.

    Returns:
        Path to the final assembled video.
    """
    logger.info("Assembling %d scenes into final video", len(scene_files))

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if settings.mock_mode:
        # In mock mode, concatenate the raw bytes of scene files
        with open(output_path, 'wb') as out_f:
            for scene_path in scene_files:
                with open(scene_path, 'rb') as in_f:
                    out_f.write(in_f.read())
        logger.info("Mock assembly: concatenated %d files -> %s", len(scene_files), output_path.name)
        return output_path

    # Create FFmpeg concat list
    concat_file = output_path.parent / "concat_list.txt"
    with open(concat_file, "w") as f:
        for scene_path in scene_files:
            f.write(f"file '{scene_path.resolve()}'\n")

    # First, re-encode all scenes to ensure consistent format
    normalized_files = []
    for i, scene_path in enumerate(scene_files):
        normalized_path = scene_path.parent / f"normalized_{i}.mp4"
        await _normalize_video(scene_path, normalized_path)
        normalized_files.append(normalized_path)

    # Update concat list with normalized files
    with open(concat_file, "w") as f:
        for norm_path in normalized_files:
            f.write(f"file '{norm_path.resolve()}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode() if stderr else "Unknown FFmpeg error"
        raise RuntimeError(f"FFmpeg concat failed: {error_msg}")

    # Cleanup
    concat_file.unlink(missing_ok=True)
    for f in normalized_files:
        f.unlink(missing_ok=True)

    logger.info("Final video assembled: %s", output_path)
    return output_path


async def _normalize_video(input_path: Path, output_path: Path) -> None:
    """
    Re-encode a video to ensure consistent codec/resolution for concatenation.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-r", "30",  # Consistent frame rate
        "-movflags", "+faststart",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


async def get_duration(file_path: Path) -> float:
    """Get the duration of a media file in seconds."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()

    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 0.0
