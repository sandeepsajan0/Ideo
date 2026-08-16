"""
Audio generation service with multiple TTS engine support.

Supports:
  - edge-tts (FREE) — Microsoft neural voices, no API key needed
  - elevenlabs (PREMIUM) — Highest quality, requires paid API key

The engine is selected via the TTS_ENGINE setting or per-request.
"""

import asyncio
import logging
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────
async def generate_audio(
    text: str,
    output_path: Path,
    voice_id: str | None = None,
    engine: str | None = None,
) -> Path:
    """
    Generate a voiceover audio file from text.

    Args:
        text: The narration text to convert to speech.
        output_path: Where to save the audio file.
        voice_id: Voice identifier (engine-specific).
        engine: TTS engine override ("edge" or "elevenlabs").

    Returns:
        Path to the saved audio file.
    """
    if settings.mock_mode:
        return await _mock_audio(output_path)

    selected_engine = engine or settings.tts_engine

    if selected_engine == "elevenlabs":
        return await _generate_elevenlabs(text, output_path, voice_id)
    else:
        # Default: edge-tts (free)
        return await _generate_edge_tts(text, output_path, voice_id)


# ─────────────────────────────────────────────
# Engine: edge-tts (FREE)
# ─────────────────────────────────────────────
async def _generate_edge_tts(
    text: str,
    output_path: Path,
    voice: str | None = None,
) -> Path:
    """
    Generate audio using Microsoft Edge TTS (free, neural voices).

    Popular voices:
      - en-US-GuyNeural (male, natural)
      - en-US-JennyNeural (female, natural)
      - en-US-AriaNeural (female, expressive)
      - en-GB-RyanNeural (British male)
      - en-IN-PrabhatNeural (Indian male)
      - hi-IN-SwaraNeural (Hindi female)
    """
    import edge_tts

    selected_voice = voice or settings.default_edge_voice

    # edge-tts outputs MP3 natively
    mp3_path = output_path.with_suffix(".mp3")
    mp3_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Generating audio [edge-tts]: %s (voice=%s)", mp3_path.name, selected_voice)

    communicate = edge_tts.Communicate(text, selected_voice)
    try:
        await communicate.save(str(mp3_path))
    except edge_tts.exceptions.NoAudioReceived as e:
        raise RuntimeError(
            f"Failed to generate audio. The selected voice '{selected_voice}' likely "
            "does not support the language of the script (e.g., an English voice trying to read Hindi). "
            "Please select a voice in the UI that matches your script's language."
        ) from e

    logger.info("Audio saved [edge-tts]: %s", mp3_path)
    return mp3_path


# ─────────────────────────────────────────────
# Engine: ElevenLabs (PREMIUM)
# ─────────────────────────────────────────────
async def _generate_elevenlabs(
    text: str,
    output_path: Path,
    voice_id: str | None = None,
) -> Path:
    """Generate audio using ElevenLabs v3 (premium, paid API)."""
    from fastapi.concurrency import run_in_threadpool
    from elevenlabs.client import ElevenLabs

    voice = voice_id or settings.default_voice_id

    logger.info("Generating audio [elevenlabs]: %s (voice=%s)", output_path.name, voice)

    mp3_path = output_path.with_suffix(".mp3")
    mp3_path.parent.mkdir(parents=True, exist_ok=True)

    def _sync_call() -> Path:
        client = ElevenLabs(api_key=settings.elevenlabs_api_key)
        audio_stream = client.text_to_speech.convert(
            voice_id=voice,
            text=text,
            model_id="eleven_v3",
            output_format="mp3_44100_128",
        )
        with open(mp3_path, "wb") as f:
            for chunk in audio_stream:
                if chunk:
                    f.write(chunk)
        return mp3_path

    result = await run_in_threadpool(_sync_call)
    logger.info("Audio saved [elevenlabs]: %s", result)
    return result


# ─────────────────────────────────────────────
# Mock mode
# ─────────────────────────────────────────────
async def _mock_audio(output_path: Path) -> Path:
    """Create a silent placeholder audio file for development (pure Python)."""
    import struct

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate a minimal silent WAV file (3 seconds, 44100Hz, mono, 16-bit)
    sample_rate = 44100
    duration_sec = 3
    num_samples = sample_rate * duration_sec
    bits_per_sample = 16
    num_channels = 1
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = num_samples * block_align
    file_size = 36 + data_size

    wav_path = output_path.with_suffix('.wav')

    with open(wav_path, 'wb') as f:
        # RIFF header
        f.write(b'RIFF')
        f.write(struct.pack('<I', file_size))
        f.write(b'WAVE')
        # fmt chunk
        f.write(b'fmt ')
        f.write(struct.pack('<I', 16))
        f.write(struct.pack('<H', 1))      # PCM
        f.write(struct.pack('<H', num_channels))
        f.write(struct.pack('<I', sample_rate))
        f.write(struct.pack('<I', byte_rate))
        f.write(struct.pack('<H', block_align))
        f.write(struct.pack('<H', bits_per_sample))
        # data chunk
        f.write(b'data')
        f.write(struct.pack('<I', data_size))
        f.write(b'\x00' * data_size)

    logger.info("Mock audio created: %s", wav_path)
    return wav_path


# ─────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────
async def list_edge_voices(language: str = "en") -> list[dict]:
    """List available edge-tts voices for a language prefix."""
    import edge_tts

    voices = await edge_tts.list_voices()
    return [
        {"name": v["ShortName"], "gender": v["Gender"], "locale": v["Locale"]}
        for v in voices
        if v["Locale"].startswith(language)
    ]
