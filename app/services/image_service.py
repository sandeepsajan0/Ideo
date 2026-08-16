"""
Image generation service.

Supports:
  - pollinations (FREE) — Open AI image generation, no key required
  - imagen (PREMIUM) — Google Imagen (Gemini API)
  - fal (PREMIUM) — Fal.ai FLUX API
"""

import asyncio
import logging
import urllib.parse
from pathlib import Path

from fastapi.concurrency import run_in_threadpool

from app.core.config import settings

logger = logging.getLogger(__name__)


async def generate_thumbnail(
    prompt: str,
    output_path: Path,
    engine: str | None = None,
    seed: int | None = None,
) -> Path:
    """
    Generate an image from a prompt.

    Args:
        prompt: Description of the desired image.
        output_path: Where to save the image.
        engine: "pollinations" (free), "imagen" (premium), or "fal" (premium).
        seed: Optional seed for reproducibility.

    Returns:
        Path to the saved image file.
    """
    if settings.mock_mode:
        return await _mock_thumbnail(output_path)

    selected_engine = engine or settings.image_engine

    if selected_engine == "fal":
        return await _generate_fal(prompt, output_path)
    elif selected_engine == "imagen":
        return await _generate_imagen(prompt, output_path)
    elif selected_engine == "huggingface":
        return await _generate_huggingface(prompt, output_path, seed=seed)
    else:
        # Default: pollinations (free)
        return await _generate_pollinations(prompt, output_path, seed=seed)


# ─────────────────────────────────────────────
# Engine: Pollinations (FREE)
# ─────────────────────────────────────────────
_pollinations_semaphore = asyncio.Semaphore(1)

async def _generate_pollinations(prompt: str, output_path: Path, seed: int | None = None) -> Path:
    """Generate image using Pollinations.ai (free, no key)."""
    logger.info("Generating thumbnail [pollinations]: %s", output_path.name)
    
    # URL encode the prompt
    safe_prompt = urllib.parse.quote(prompt)
    
    # Request a landscape image (e.g. 1280x720) with no logo
    url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1280&height=720&nologo=true"
    if seed is not None:
        url += f"&seed={seed}"
    
    # Pollinations limits to 1 concurrent request per IP
    async with _pollinations_semaphore:
        await _download_file(url, output_path)
        # Give Pollinations a 2-second cooldown so it doesn't instantly reject the next queued scene
        await asyncio.sleep(2.0)
        
    logger.info("Thumbnail saved [pollinations]: %s", output_path)
    return output_path


# ─────────────────────────────────────────────
# Engine: Fal.ai (PREMIUM)
# ─────────────────────────────────────────────
async def _generate_fal(prompt: str, output_path: Path) -> Path:
    """Generate image using Fal.ai FLUX (premium, paid API)."""
    import fal_client

    logger.info("Generating thumbnail [fal]: %s", output_path.name)

    def _sync_call() -> dict:
        return fal_client.subscribe(
            "fal-ai/flux/dev",
            arguments={
                "prompt": prompt,
                "image_size": "landscape_16_9",
                "num_images": 1,
            },
            with_logs=True,
        )

    result = await run_in_threadpool(_sync_call)
    image_url = result["images"][0]["url"]
    await _download_file(image_url, output_path)

    logger.info("Thumbnail saved [fal]: %s", output_path)
    return output_path


# ─────────────────────────────────────────────
# Engine: Google Imagen (Gemini API)
# ─────────────────────────────────────────────
async def _generate_imagen(prompt: str, output_path: Path) -> Path:
    """Generate image using Google Gemini Image Model (Gemini API)."""
    from google import genai
    from google.genai import types

    logger.info("Generating thumbnail [imagen]: %s", output_path.name)
    
    def _sync_call() -> bytes:
        client = genai.Client()
        response = client.models.generate_content(
            model='gemini-2.5-flash-image',
            contents=prompt,
        )
        
        # Extract image bytes from the response
        try:
            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if part.inline_data and part.inline_data.data:
                        return part.inline_data.data
        except AttributeError:
            pass
            
        raise RuntimeError("Image generation failed or returned unexpected format.")

    image_bytes = await run_in_threadpool(_sync_call)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_bytes)

    logger.info("Thumbnail saved [imagen]: %s", output_path)
    return output_path


# ─────────────────────────────────────────────
# Engine: Hugging Face (FREE with Key)
# ─────────────────────────────────────────────
async def _generate_huggingface(prompt: str, output_path: Path, seed: int | None = None) -> Path:
    """Generate image using Hugging Face Inference API."""
    logger.info("Generating thumbnail [huggingface]: %s", output_path.name)
    
    if not settings.hf_token:
        logger.warning("HF_TOKEN not set. Falling back to mock thumbnail.")
        return await _mock_thumbnail(output_path)
        
    url = "https://router.huggingface.co/hf-inference/models/stabilityai/stable-diffusion-xl-base-1.0"
    headers = {
        "Authorization": f"Bearer {settings.hf_token}",
        "Content-Type": "application/json",
    }
    
    payload = {"inputs": prompt}
    if seed is not None:
        payload["parameters"] = {"seed": seed}

    import json
    import urllib.request
    import urllib.error
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    def _fetch_hf_image():
        req = urllib.request.Request(
            url, 
            data=json.dumps(payload).encode("utf-8"), 
            headers=headers, 
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                return response.read(), None
        except urllib.error.HTTPError as e:
            return None, e.read().decode("utf-8", errors="ignore")
        except Exception as e:
            return None, str(e)
            
    img_data, error_msg = await asyncio.to_thread(_fetch_hf_image)
    
    if img_data and len(img_data) > 20480: # > 20KB
        with open(output_path, "wb") as f:
            f.write(img_data)
        logger.info("Thumbnail saved [huggingface]: %s", output_path)
        global _last_valid_image
        _last_valid_image = output_path
    else:
        if error_msg:
            logger.error("Hugging Face API Error: %s", error_msg)
        else:
            logger.error("Hugging Face API failed or returned invalid data. Size: %s", len(img_data) if img_data else 0)
            
        logger.warning("Falling back to previous image or mock...")
        import shutil
        if _last_valid_image and _last_valid_image.exists():
            logger.info("Using previously generated image as fallback.")
            shutil.copy2(_last_valid_image, output_path)
        else:
            logger.warning("No previous image available. Using mock placeholder.")
            await _mock_thumbnail(output_path)
            
    return output_path


# ─────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────
_last_valid_image: Path | None = None

async def _download_file(url: str, output_path: Path) -> None:
    """Download a file from URL."""
    global _last_valid_image
    output_path.parent.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "curl", "-m", "15", "-s", "-L", "-A", "Mozilla/5.0", "-o", str(output_path), url,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    # If the download failed or returned 0 bytes (which Pollinations sometimes does),
    # or if it returned a JSON error (can be up to ~10KB with long prompts).
    is_valid = True
    if not output_path.exists() or output_path.stat().st_size == 0:
        is_valid = False
    elif output_path.stat().st_size < 50000:  # Any real 1280x720 image will be > 50KB
        with open(output_path, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(100)
            if "{" in head and "error" in head.lower():
                is_valid = False

    if is_valid:
        _last_valid_image = output_path
    else:
        logger.warning("Image API failed or returned an error. Falling back...")
        import shutil
        if _last_valid_image and _last_valid_image.exists():
            logger.info("Using previously generated image as fallback.")
            shutil.copy2(_last_valid_image, output_path)
        else:
            logger.warning("No previous image available. Using mock placeholder.")
            await _mock_thumbnail(output_path)


async def _mock_thumbnail(output_path: Path) -> Path:
    """Create a placeholder thumbnail using FFmpeg to ensure valid dimensions and encoding."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "ffmpeg", "-y", 
        "-f", "lavfi", 
        "-i", "color=c=0x16213e:s=1280x720:d=1",
        "-frames:v", "1", 
        str(output_path)
    ]
    
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    logger.info("Mock thumbnail created: %s", output_path)
    return output_path
