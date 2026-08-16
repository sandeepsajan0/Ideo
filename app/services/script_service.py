"""
Script generation service using Google Gemini.

Generates a structured JSON script with narration text and visual prompts
for each scene of the video.
"""

import json
import logging
from typing import Any

from google import genai
from google.genai import types

from app.core.config import settings

logger = logging.getLogger(__name__)


SCRIPT_PROMPT_TEMPLATE = """You are a professional video scriptwriter. Write an engaging {num_scenes}-scene video script about: {topic}

The video will be in {aspect_ratio} format.
Target duration: {target_duration} minutes. 
You must write enough narration to fill {target_duration} minutes of spoken audio (roughly {total_words} words total). Each scene's narration should be proportionally long (around {words_per_scene} words per scene).

Output STRICTLY in JSON format as a list of objects. Each object must have exactly two keys:
- "narration": The exact text to be spoken aloud by a narrator. Make it engaging, informative, and conversational. Make sure it hits the required word count.
- "visual_prompt": A detailed, cinematic prompt for an AI video generator describing what should appear on screen. Include camera angles, lighting, mood, colors, and motion. Be specific and vivid.

Rules:
1. Start with a hook that grabs attention in the first scene.
2. Build a narrative arc across scenes.
3. End with a memorable conclusion or call-to-action.
4. Each visual_prompt should be self-contained and describe a distinct, visually rich scene.
5. Do NOT include markdown, code fences, or any text outside the JSON array.

Output the raw JSON array only."""


async def generate_script(
    topic: str,
    num_scenes: int = 3,
    aspect_ratio: str = "9:16",
    target_duration: int = 2,
    tts_engine: str = "edge",
    voice_id: str = "en-US-GuyNeural"
) -> list[dict[str, Any]]:
    """
    Generate a video script with narration and visual prompts using Gemini.

    Returns a list of dicts, each with 'narration' and 'visual_prompt' keys.
    """
    if settings.mock_mode:
        return _mock_script(topic, num_scenes)

    client = genai.Client(api_key=settings.gemini_api_key)

    total_words = target_duration * 150
    words_per_scene = total_words // num_scenes

    # Determine language from voice_id if using edge-tts
    language_instruction = ""
    if tts_engine == "edge" and voice_id:
        lang_code = voice_id.split("-")[0].lower()
        lang_map = {"hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese", "ja": "Japanese"}
        if lang_code in lang_map:
            language_instruction = f"\nCRITICAL INSTRUCTION: You MUST write the 'narration' entirely in {lang_map[lang_code]} (the visual_prompt must remain in English). Do not output English narration."

    prompt = SCRIPT_PROMPT_TEMPLATE.format(
        num_scenes=num_scenes,
        topic=topic,
        aspect_ratio=aspect_ratio,
        target_duration=target_duration,
        total_words=total_words,
        words_per_scene=words_per_scene,
    ) + language_instruction

    logger.info("Generating script for topic: %s (%d scenes, ~%dmins)", topic, num_scenes, target_duration)

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )

    script_data = json.loads(response.text)

    # Validate structure
    if not isinstance(script_data, list):
        raise ValueError("Gemini returned non-list JSON")

    for i, scene in enumerate(script_data):
        if "narration" not in scene or "visual_prompt" not in scene:
            raise ValueError(f"Scene {i} missing required keys")

    logger.info("Script generated successfully: %d scenes", len(script_data))
    return script_data


def _mock_script(topic: str, num_scenes: int) -> list[dict[str, Any]]:
    """Return a placeholder script for development without API calls."""
    scenes = []
    for i in range(num_scenes):
        scenes.append({
            "narration": f"Scene {i + 1} narration about {topic}. "
                         f"This is a placeholder for development and testing.",
            "visual_prompt": f"A cinematic wide shot related to {topic}, "
                             f"scene {i + 1}. Golden hour lighting, "
                             f"dramatic composition, 4K quality.",
        })
    return scenes
