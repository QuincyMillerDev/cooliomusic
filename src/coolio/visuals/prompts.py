"""Visual prompt generation from music concepts.

Uses LLM to convert a music concept into simple color/atmosphere modification
instructions. These instructions tell the image generator how to transform
the reference venue photo (hue shifts, atmosphere changes) while preserving
the exact composition.

Also generates video motion prompts for Kling AI image-to-video generation.
"""

import json
import logging

from openai import OpenAI

from coolio.config import get_settings

logger = logging.getLogger(__name__)


VIDEO_MOTION_SYSTEM_PROMPT = """
You create video motion prompts for a DJ booth scene. The video will loop as background visuals for productivity music on YouTube.

Goal: Create an atmospheric, hypnotic visual that enhances focus without being distracting.

The source image shows an empty underground venue with DJ equipment. Describe subtle motion that brings the scene to life - atmospheric haze, gentle light shifts, ambient movement.

Output JSON:
{
  "motion_type": "atmospheric",
  "prompt": "Your motion description for Kling AI"
}
"""


SYSTEM_PROMPT = """
<role>
You generate color/atmosphere modification instructions for an existing DJ venue photograph.

The AI image generator will receive a REFERENCE PHOTO showing:
- Underground warehouse venue with exposed wooden ceiling beams
- Pioneer CDJ-2000/3000 setup on a wooden table (foreground)
- Red/orange lighting from stage lights on both sides
- DJ silhouette and dancing crowd (WILL BE REMOVED by the generator)
- Atmospheric haze throughout the space
- Items on table: yellow cup, water bottle, cables, disco ball/net on right

Your task: Based on the music concept, describe ONLY the color/hue shifts and atmosphere adjustments.
The image generator will handle removing people and keeping the exact composition.
</role>

<output_rules>
1. Keep instructions SIMPLE - just color and atmosphere changes
3. Focus on: lighting color, haze density, mood/atmosphere
</output_rules>

<output_format>
Return JSON:
{
  "scene_type": "hue_shift" or "custom_blend",
  "prompt": "Simple 1-2 sentence instruction for color/atmosphere change"
}
</output_format>
"""


def generate_visual_prompt(
    concept: str,
    visual_hint: str | None = None,
    model: str | None = None,
) -> dict:
    """Generate color/atmosphere modification instructions from a music concept.

    The output is a simple instruction for how to modify the reference image's
    colors and atmosphere while preserving the exact venue composition.

    Args:
        concept: The music concept/vibe (e.g., "Berlin techno, minimal").
        visual_hint: Optional atmosphere/style hints (e.g., "Stranger Things vibes").
        model: LLM model to use (defaults to settings).

    Returns:
        Dict with 'scene_type' and 'prompt' keys.
    """
    s = get_settings()
    client = OpenAI(
        base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key,
    )
    model = model or s.openrouter_model

    # Build user prompt with optional style hint
    hint_section = ""
    if visual_hint:
        hint_section = f'\nSTYLE HINT: "{visual_hint}"'

    user_prompt = f"""Generate color/atmosphere modification for this music concept:

CONCEPT: "{concept}"{hint_section}

Output a simple instruction describing the lighting color shift and atmosphere change.
The reference image (red/orange underground venue) will be transformed to match this vibe.
"""

    logger.info(f"Generating visual prompt for concept: {concept[:50]}...")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        raise ValueError(f"OpenRouter API error: {e}")

    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty response from visual prompt generator")

    # Clean markdown fences if present
    content = content.strip()
    if content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline != -1:
            content = content[first_newline + 1:]
        if content.endswith("```"):
            content = content[:-3].strip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from visual prompt generator: {e}")

    scene_type = data.get("scene_type", "warehouse")
    prompt = data.get("prompt", "")

    if not prompt:
        raise ValueError("Visual prompt generator returned empty prompt")

    logger.info(f"Generated visual prompt (scene: {scene_type})")

    return {
        "scene_type": scene_type,
        "prompt": prompt,
    }


def generate_video_motion_prompt(
    concept: str,
    image_prompt: str | None = None,
    model: str | None = None,
) -> dict:
    """Generate a video motion prompt for Kling AI image-to-video.

    Creates simple, atmospheric motion prompts that match the music concept.

    Args:
        concept: The music concept/vibe for context.
        image_prompt: Optional - the image prompt used to generate the source image.
        model: LLM model to use (defaults to settings).

    Returns:
        Dict with 'motion_type' and 'prompt' keys.
    """
    s = get_settings()
    client = OpenAI(
        base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key,
    )
    model = model or s.openrouter_model

    # Build context from concept and optional image prompt
    context_section = ""
    if image_prompt:
        context_section = f"""
IMAGE DESCRIPTION: "{image_prompt}"
Use this description to understand the scene's lighting, atmosphere, and environmental details.
"""

    user_prompt = f"""Create a video motion prompt for this music session:

MUSIC CONCEPT: "{concept}"
{context_section}
Describe atmospheric motion that matches this vibe.
"""

    logger.info("Generating video motion prompt...")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": VIDEO_MOTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        raise ValueError(f"OpenRouter API error: {e}")

    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty response from video motion prompt generator")

    # Clean markdown fences if present
    content = content.strip()
    if content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline != -1:
            content = content[first_newline + 1:]
        if content.endswith("```"):
            content = content[:-3].strip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from video motion prompt generator: {e}")

    motion_type = data.get("motion_type", "mixed")
    prompt = data.get("prompt", "")

    if not prompt:
        raise ValueError("Video motion prompt generator returned empty prompt")

    logger.info(f"Generated video motion prompt (type: {motion_type})")

    return {
        "motion_type": motion_type,
        "prompt": prompt,
    }
