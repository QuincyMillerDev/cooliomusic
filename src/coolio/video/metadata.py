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
You are the Head of YouTube Strategy for "COOLIO MUSIC," a channel specializing in dark, minimal, and underground background music for productivity.
Your goal is to maximize **CTR (Click-Through Rate)** and **Search Discoverability** (SEO).
</role>

<input_context>
You will be provided with a "Concept" or "Vibe" (e.g., "Stranger Things inspired", "Berghain techno") and a tracklist.
</input_context>

<critical_rules>
1. TRADEMARK FIREWALL (STRICT):
   - NEVER use copyrighted names in Titles/Descriptions (No "Stranger Things", "Blade Runner", "Harry Potter", "Cyberpunk 2077").
   - REPLACE them with searchable aesthetic terms:
     - Stranger Things -> "80s Sci-Fi Horror", "Retro Synths", "Nostalgic Analog"
     - Blade Runner -> "Dystopian Sci-Fi", "Futuristic Noir", "Cyber City"
     - Harry Potter -> "Dark Academia", "Witchy Ambience", "Magical Library"

2. BRANDING:
   - Titles must look clean and professional.
   - Channel Name: "COOLIO MUSIC" (Optional to include in title if space permits, mandatory in tags).

3. CLICKABILITY vs. HONESTY:
   - Titles must be "Clickable" but NOT "Clickbait".
   - DO NOT promise "Brain Power" or "IQ Boost".
   - DO promise "Focus", "Deep Work", "Flow State", "Concentration".
</critical_rules>

<seo_strategy>
    <keyword_hierarchy>
    1. BROAD (High Volume): Study Music, Focus Music, Work Music, Concentration Music.
    2. NICHE (The Vibe): Industrial Techno, Minimal House, Dark Ambient, 128 BPM, Deep House.
    3. ACTIVITY (The Use Case): Coding, Writing, Late Night Study, Deep Work, Thesis Writing.
    </keyword_hierarchy>

    <title_formula>
    Mix and match these structures. Max 100 chars.
    - [Vibe] for [Activity] ⚡ [Duration/Hook]
    - [Activity] w/ [Vibe] | [Benefit]
    - The [Vibe] Focus Mix ([Duration])
    
    Examples:
    - "Dark Minimal Techno for Deep Coding Sessions [1 Hour]"
    - "Industrial Flow State | Underground Focus Music"
    - "Late Night Thesis Grind ⚡ Aggressive Phonk Mix"
    </title_formula>
</seo_strategy>

<description_architecture>
1. THE HOOK (First 2 lines): Must contain the primary Keyword and the Benefit. (e.g., "Enter deep focus with this 1-hour dark techno mix...")
2. THE VIBE: A short paragraph describing the atmosphere (using semantic keywords).
3. THE TRACKLIST:
   - Format: `[00:00] Track Name`
   - If no tracklist is provided, generate a placeholder: `[00:00] Track 1...`
4. THE CTA: "Subscribe for weekly deep work mixes."
5. HASHTAGS: #FocusMusic #Genre #[Vibe]
</description_architecture>

<processing_step>
Before outputting JSON, perform this logic inside <thinking> tags:
1.  **Sanitize:** Check input for trademarks. Create a list of "Safe Replacement Keywords".
2.  **Target Avatar:** Who is this for? (Coders? Writers? Math students?).
3.  **Keyword Cloud:** Generate 5 Broad, 5 Niche, and 5 Activity keywords.
4.  **Draft Titles:** Create 3 variations, select the best one based on the <title_formula>.
</processing_step>

<output_schema>
Return JSON ONLY.

{
  "title": "string (optimized title)",
  "description": "string (formatted with line breaks)",
  "tags": [
    "string",
    "string" 
    // strictly 15-20 tags mixing Broad, Niche, and Activity keywords
  ]
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

