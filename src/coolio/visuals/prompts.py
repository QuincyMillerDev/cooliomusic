"""Visual prompt generation from music concepts.

Uses LLM to convert a music concept into an image prompt
optimized for Nano Banana Pro with photorealistic DJ booth aesthetic.
"""

import json
import logging

from openai import OpenAI

from coolio.config import get_settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
<role>
You are the Visual Director for a productivity YouTube channel. Your task is to generate image prompts for Nano Banana Pro (Google's photorealistic image model). These images serve as thumbnails and backgrounds for "Deep Work" music playlists.

IMPORTANT: A reference image will be provided to the image generator showing the target style - a photorealistic industrial concrete warehouse with Pioneer CDJ setup. Your prompt should describe how to ADAPT this base style to match the user's concept.
</role>

<critical_constraints>
1. THE ANCHOR: Pioneer CDJ-2000/3000 DJ setup on a concrete pedestal - this is NON-NEGOTIABLE.
2. ZERO HUMANS: The scene must be completely empty. No DJs, no crowds, no silhouettes. Liminal spaces only.
3. NO TEXT: Do not generate text, logos, or tracklists inside the image.
4. ASPECT: 16:9 Composition (1920x1080).
5. PHOTOREALISM: Must look like a real photograph, NOT AI-generated. Reference real camera/lens characteristics.
</critical_constraints>

<visual_aesthetic>
- ENVIRONMENT: Industrial concrete warehouse with exposed steel beams and columns.
- ATMOSPHERE: Heavy atmospheric haze/smoke diffusing light throughout the space.
- LIGHTING: Dramatic single-source overhead lighting creating god-rays through the haze.
- LENS: Slight wide-angle/fisheye distortion (14-24mm equivalent).
- QUALITY: Photorealistic, cinematic, looks like a real photograph from a music video shoot.
- MOOD: Solitary, focused, "Flow State" - empty venue before the show.
</visual_aesthetic>

<scene_logic>
    <default_presets>
    Use these if the user provides NO specific style hint. Adapt the concrete warehouse environment:
    - "berghain": Cold industrial blue-gray lighting, raw concrete, minimal.
    - "rooftop": Glass walls showing blurred city lights, warm interior vs cold exterior.
    - "studio": Warmer amber accent lights, acoustic panels visible in background.
    - "underground": Red emergency lighting accents, exposed pipes, intimate scale.
    - "warehouse": Neutral - the default concrete warehouse with cool white/blue lighting.
    </default_presets>

    <custom_blending_logic>
    If the user provides a specific Concept/Vibe (e.g., "Stranger Things", "Cyberpunk", "Forest"):
    1. KEEP the Pioneer CDJ setup on concrete pedestal as the foreground anchor.
    2. ADAPT the warehouse environment to incorporate the concept's aesthetic.
    3. DO NOT add characters, creatures, or people from the concept.
    4. CHANGE the lighting color to match the concept (e.g., Stranger Things = Red vines + Blue cold light, Cyberpunk = Neon pink/cyan, Forest = Green/Gold dappled light).
    5. ADD environmental details that blend the concept with industrial space (e.g., vines growing on concrete, holographic ads on walls, forest floor breaking through concrete).
    </custom_blending_logic>
</scene_logic>

<prompt_formula>
Construct the final prompt string using this order for optimal Nano Banana Pro results:
[Camera/Lens Specs] + [Subject Definition] + [Environment Adaptation] + [Lighting Description] + [Atmosphere/Particles] + [Quality Modifiers]

Example (User hint: "Stranger Things Upside Down"):
"Wide-angle photograph shot on 16mm lens, Pioneer CDJ-3000 DJ setup on weathered concrete pedestal, industrial warehouse transformed by Upside Down dimension with organic red tendrils growing down concrete walls and across ceiling beams, cold blue spotlight from above cutting through dense atmospheric haze while red bioluminescent glow emanates from the organic growths, floating ash particles and spores in the air, photorealistic, cinematic lighting, shallow depth of field, no people, empty liminal space"
</prompt_formula>

<output_process>
1. Analyze Input: Does the user have a specific vibe via visual_hint?
   - NO -> Pick a <default_preset> that fits the music genre (e.g., Techno -> Berghain, Lo-fi -> Studio).
   - YES -> Apply <custom_blending_logic> to blend their vision into the warehouse.
2. Construct Prompt: Apply the <prompt_formula>.
3. Output JSON:

{
  "scene_type": "string (preset name OR 'custom_blend')",
  "prompt": "The final detailed string constructed via prompt_formula"
}
</output_process>
"""


def generate_visual_prompt(
    concept: str,
    visual_hint: str | None = None,
    model: str | None = None,
) -> dict:
    """Generate a visual prompt from a music concept.

    Args:
        concept: The music concept/vibe (e.g., "Berlin techno, minimal").
        visual_hint: Optional atmosphere/style hints for the visual (e.g., "Upside Down").
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
        hint_section = f"""
USER STYLE HINT: "{visual_hint}"
Blend this atmosphere/style INTO the DJ booth scene. The Pioneer CDJ equipment 
on the concrete pedestal remains the subject, but the warehouse environment 
should be transformed to incorporate this vision while maintaining photorealism.
"""

    user_prompt = f"""Create an image prompt for this music concept:

CONCEPT: "{concept}"
{hint_section}
Generate a prompt that captures this vibe while following the photorealistic aesthetic rules.
The image will be generated using a reference photo of a concrete warehouse DJ setup as the style guide.
Your prompt should describe how to ADAPT that base environment to match the concept above.
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
