"""Visual prompt generation from music concepts.

Uses LLM to convert a music concept into a Flux image prompt
that matches the chill DJ aesthetic.
"""

import json
import logging

from openai import OpenAI

from coolio.config import get_settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a visual director for a productivity YouTube music channel.

Your job is to create image prompts for AI image generation (Flux) that will become 
YouTube thumbnails and video backgrounds.

AESTHETIC RULES (MUST follow):
1. ALWAYS a DJ booth OR vinyl turntable setup - never anything else
2. ALWAYS dark, minimal, atmospheric lighting
3. NEVER any people - empty scene only
4. Scene should feel underground, authentic, professional
5. Strong single color accent (green, red, amber, blue) through lighting
6. Industrial/warehouse textures: concrete, metal, exposed pipes
7. Haze/smoke in the air for atmosphere
8. Film grain, high contrast, cinematic look

SCENE VARIATIONS (pick one based on concept vibe):
- "berghain": Dark concrete warehouse, industrial green lights, brutalist
- "rooftop": Night cityscape backdrop, neon accents, urban minimal
- "studio": Intimate recording space, warm amber light, analog gear
- "underground": Basement club, red emergency lighting, raw concrete
- "warehouse": Massive industrial space, dramatic single spotlight

OUTPUT FORMAT (JSON only):
{
  "scene_type": "berghain|rooftop|studio|underground|warehouse",
  "prompt": "Detailed Flux prompt describing the scene..."
}

PROMPT STRUCTURE:
Start with the main subject (turntable/DJ booth), then lighting, then atmosphere,
then style modifiers. Be specific about colors, textures, and mood.

Example good prompt:
"vinyl turntable on concrete pedestal in dark warehouse, two green industrial 
spotlights from above, thick smoke haze drifting through light beams, exposed 
pipes on ceiling, no people, Berghain aesthetic, high contrast, cinematic 
film grain, 16:9 composition"

Example bad prompt:
"DJ equipment in a club" (too vague, no atmosphere details)
"""


def generate_visual_prompt(concept: str, model: str | None = None) -> dict:
    """Generate a visual prompt from a music concept.

    Args:
        concept: The music concept/vibe (e.g., "Berlin techno, minimal").
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

    user_prompt = f"""Create a visual prompt for this music concept:

CONCEPT: "{concept}"

Generate a Flux image prompt that captures this vibe while following the aesthetic rules.
The image will be used as both the YouTube thumbnail and the video background.
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

