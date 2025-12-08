"""YouTube metadata generation using LLM.

Generates SEO-optimized titles, descriptions, and tags for YouTube uploads.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from coolio.config import get_settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
<role>
You write YouTube metadata for "coolio music," a channel specializing in dark, minimal, and underground background music for productivity.
</role>

<critical_rules>
1. ALL LOWERCASE TITLES (STRICT):
   - Titles must be entirely lowercase. No capital letters. This is the channel aesthetic.
   - Example: "dark minimal techno for deep coding sessions [1 hour]"

2. TRADEMARK FIREWALL (STRICT):
   - NEVER use copyrighted names (no "stranger things", "blade runner", "cyberpunk 2077").
   - Replace with aesthetic terms: "80s sci-fi horror", "dystopian noir", "retro synths"

3. NO CLICKBAIT:
   - Don't promise "brain power" or "iq boost"
   - Do use: "focus", "deep work", "flow state", "late night"
</critical_rules>

<title_style>
All lowercase, max 80 chars. Clean and minimal.

Examples:
- "dark minimal techno for deep coding sessions [1 hour]"
- "late night deep house | underground focus music"
- "industrial techno flow state mix"
</title_style>

<description_style>
Write like a human, not a marketer. Evocative and conversational.

STRUCTURE:
1. THE HOOK (2-3 sentences): Poetic/storytelling opening about the feeling or moment this music captures. Make it evocative and personal.

2. THE CONTEXT (1-2 sentences): What this mix is good for—late nights, deep work, coding, introspection.

3. CTAs:
   "► subscribe to coolio music: @cooliomusic"
   "► support the channel: https://buymeacoffee.com/cooliomusic"

4. TRACKLIST: Use this exact format with timestamps:
   // tracklist
   00:00 - track name
   03:45 - track name
   (timestamps will be provided or use placeholders)

NO hashtags. NO excessive emojis. NO corporate language.
</description_style>

<example_description>
some nights don't follow the rules. they're a chaotic, beautiful blur of moments that don't quite make sense until later... or maybe they never do. this is the soundtrack for that feeling—a deep, hypnotic techno journey through a perfect, surreal memory you just can't explain.

this mix is perfect for late-night coding, introspection, or just embracing the beautiful chaos.

► subscribe to coolio music: @cooliomusic
► support the channel: https://buymeacoffee.com/cooliomusic

// tracklist
00:00 - fading language
06:04 - the unexplained night
12:42 - 4 am logic
</example_description>

<output_schema>
Return JSON only:
{
  "title": "all lowercase title here",
  "description": "evocative description with line breaks",
  "tags": ["15-20 tags", "mixing broad and niche keywords", "coolio music"]
}
</output_schema>
"""


@dataclass
class YouTubeMetadata:
    """YouTube upload metadata."""

    title: str
    description: str
    tags: list[str]

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
        }

    def to_txt(self) -> str:
        """Convert to copy-paste friendly text format."""
        tags_str = ", ".join(self.tags)
        return f"""TITLE:
{self.title}

DESCRIPTION:
{self.description}

TAGS:
{tags_str}
"""


def generate_youtube_metadata(
    concept: str,
    duration_minutes: float,
    tracklist: list[dict] | None = None,
    model: str | None = None,
) -> YouTubeMetadata:
    """Generate YouTube metadata from session concept.

    Args:
        concept: The original session concept/vibe.
        duration_minutes: Total duration of the video in minutes.
        tracklist: Optional list of tracks with titles and durations.
        model: LLM model to use (defaults to settings).

    Returns:
        YouTubeMetadata with title, description, and tags.
    """
    s = get_settings()
    client = OpenAI(
        base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key,
    )
    model = model or s.openrouter_model

    # Format duration nicely
    hours = int(duration_minutes // 60)
    mins = int(duration_minutes % 60)
    if hours > 0:
        duration_str = f"{hours} hour{'s' if hours > 1 else ''}"
        if mins > 0:
            duration_str += f" {mins} min"
    else:
        duration_str = f"{mins} minutes"

    # Format tracklist if provided
    tracklist_str = ""
    if tracklist:
        tracklist_str = "\n\nTRACKLIST:\n"
        for i, track in enumerate(tracklist, 1):
            title = track.get("title", f"Track {i}")
            tracklist_str += f"- {title}\n"

    user_prompt = f"""Generate YouTube metadata for this music mix:

CONCEPT: "{concept}"
DURATION: {duration_str} ({duration_minutes:.0f} minutes total)
{tracklist_str}

Create a compelling title, full description, and relevant tags.
"""

    logger.info(f"Generating YouTube metadata for: {concept[:50]}...")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        raise ValueError(f"OpenRouter API error: {e}")

    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty response from metadata generator")

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
        raise ValueError(f"Invalid JSON from metadata generator: {e}")

    title = data.get("title", "")
    description = data.get("description", "")
    tags = data.get("tags", [])

    if not title:
        raise ValueError("Metadata generator returned empty title")

    logger.info(f"Generated title: {title}")

    return YouTubeMetadata(
        title=title,
        description=description,
        tags=tags,
    )


def save_metadata(
    metadata: YouTubeMetadata,
    session_dir: Path,
) -> tuple[Path, Path]:
    """Save metadata to session directory.

    Saves both JSON (for programmatic use) and TXT (for manual copy/paste).

    Args:
        metadata: The generated YouTube metadata.
        session_dir: Path to session directory.

    Returns:
        Tuple of (json_path, txt_path).
    """
    json_path = session_dir / "youtube_metadata.json"
    txt_path = session_dir / "youtube_metadata.txt"

    # Save JSON
    with open(json_path, "w") as f:
        json.dump(metadata.to_dict(), f, indent=2)

    # Save TXT
    with open(txt_path, "w") as f:
        f.write(metadata.to_txt())

    logger.info(f"Saved metadata: {json_path}")
    logger.info(f"Saved metadata: {txt_path}")

    return json_path, txt_path

