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


SYSTEM_PROMPT = """You are a YouTube SEO expert for a productivity music channel.

Your job is to create metadata for YouTube videos featuring long-form study/focus music mixes.

CHANNEL STYLE:
- Target audience: Students, remote workers, focus seekers
- Content: 1-2+ hour continuous DJ mixes
- Genres: House, techno, lofi, ambient, electronic
- Aesthetic: Dark, minimal, underground club vibes

OUTPUT FORMAT (JSON only):
{
  "title": "Catchy, SEO-friendly title (max 100 chars)",
  "description": "Full YouTube description with sections",
  "tags": ["array", "of", "relevant", "tags"]
}

TITLE RULES:
- Include genre/mood keywords
- Include duration (e.g., "2 Hours")
- Include purpose (e.g., "Focus Music", "Study Mix", "Deep Work")
- Make it searchable but not clickbaity
- Max 100 characters

Good titles:
- "Deep Berlin Techno Mix For a Serious Grind | COOLIOMUSIC"
- "Minimal House Study Session | COOLIOMUSIC"
- "Dark Ambient Music to Stay Locked In | COOLIOMUSIC"

Bad titles:
- "BEST MUSIC EVER!!!" (clickbait)
- "Mix 001" (not searchable)
- "Techno" (too vague)

DESCRIPTION STRUCTURE:
1. Opening hook (what this mix is for)
2. Tracklist with timestamps (use placeholder format: 0:00:00 - Track Name)
3. Call to action (subscribe, like, comment)
4. Hashtags at the end

TAGS:
- Include genre tags (techno, house, lofi, etc.)
- Include purpose tags (study music, focus, concentration, etc.)
- Include mood tags (chill, dark, minimal, etc.)
- Include YouTube-specific tags (study with me, work music, etc.)
- 15-20 tags is ideal
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

