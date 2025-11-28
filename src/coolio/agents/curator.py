"""Curator agent for planning sessions with library reuse.

Acts as a DJ that can select existing tracks from the library or request
new generation to fill gaps. This is the first agent in the pipeline -
it always runs before the Generator agent.
"""

import json
import logging

from openai import OpenAI

from coolio.core.config import get_settings
from coolio.library.metadata import TrackMetadata
from coolio.models import SessionPlan, TrackSlot

logger = logging.getLogger(__name__)


# Keep old names as aliases for backwards compatibility during migration
CurationSlot = TrackSlot
CurationPlan = SessionPlan


SYSTEM_PROMPT = """CONTEXT:
You are an expert DJ and Music Curator building playlists for a **productivity YouTube channel**.

YOUR AUDIENCE:
- Students studying, writing papers, doing problem sets
- Remote workers in deep work sessions
- Anyone seeking flow state through music

YOUR PURPOSE:
Create hour-long background music sets that help people focus. The music should be 
cohesive, non-distracting, and support sustained concentration. Videos are published 
to YouTube as 1-2+ hour continuous mixes.

You have access to a library of existing tracks and can request new generation to fill gaps.

YOUR TASK:
1. Analyze the user's concept (genre, vibe).
2. Look at the PROVIDED CANDIDATE TRACKS from the library.
3. Build a tracklist that mixes EXISTING tracks (if they fit well) with NEW GENERATION requests (to fill gaps).
4. Ensure perfect flow: consistent BPM (±5), matching energy arc, and strict genre adherence.

DECISION LOGIC (The "Fit" Score):
- REUSE a track if:
  - Genre matches EXACTLY.
  - BPM is within ±3 of target.
  - Energy fits the current slot's role (e.g., low energy for intro, high for peak).
  - Vibe/Title matches the concept.
- GENERATE a new track if:
  - No existing track fits the slot perfectly.
  - You need a specific bridge or transition not present in the library.

TRACK NAMING (for new generation):
Each track MUST have a unique, evocative title - like a real song name you'd see on a tracklist.
Good titles are abstract, poetic, or emotionally resonant. Think of names like:
- "These Things Will Come To Be"
- "Can We Still Be Friends?"
- "Porco Rosso"
- "All About U"
- "Sufriendo"

Bad titles are generic or too literal:
- "Deep Focus Beat 1" (too generic)
- "Intro Track" (describes role, not a name)
- "Neon Drift" (overused AI aesthetic)

PROMPT CRAFTING (for new generation):
Each track's prompt must layer multiple descriptors together. Combine:
- Genre + BPM
- Specific instruments/sounds
- Mood/atmosphere
- What to include AND exclude

EXAMPLE PROMPTS:
- GOOD: "Minimal techno at 128 BPM with a deep kick drum, filtered synth stabs, sparse hi-hats,
  and rumbling sub-bass. Hypnotic and driving atmosphere, perfect for late-night focus sessions.
  No vocals, no melodic hooks, no sudden changes."
- BAD: "Techno music for studying" (too vague, no layered descriptors)

OUTPUT SCHEMA (JSON ONLY):
{
  "bpm_range": [124, 130],
  "slots": [
    {
      "order": 1,
      "role": "intro",
      "duration_ms": 180000,
      "bpm_target": 124,
      "energy": 3,
      "source": "library",
      "track_id": "abc123", 
      "title": "Existing Track Title"
    },
    {
      "order": 2,
      "role": "build",
      "duration_ms": 180000,
      "bpm_target": 126,
      "energy": 5,
      "source": "generate",
      "title": "Echoes of Tomorrow",
      "provider": "stable_audio",
      "prompt": "Detailed generation prompt for a building minimal techno track..."
    }
  ]
}

PROVIDER SELECTION FOR NEW GENERATION:
- stable_audio: $0.20/track FLAT RATE. Duration: 120-190s. Prefer this for cost efficiency.
- elevenlabs: $0.006/sec (~$0.30/min). Duration: 120-300s. Use if you need a longer track.

Default to stable_audio for most new tracks, but elevenlabs is fine if a longer piece genuinely 
serves the set (e.g., an extended peak section). Library tracks are FREE to reuse regardless 
of their original provider.

ELEVENLABS PROMPT RULES:
For elevenlabs tracks, prompts MUST NOT contain:
- Brand names: Moog, Roland, Juno, Jupiter, Prophet, Oberheim, Korg, Yamaha, Fender, Rhodes
- Artist/band names or direct style references to specific musicians
- Cultural decade references like "80s-inspired" or "90s style"

Use generic descriptors instead:
- NOT "Moog bass" → USE "warm analog synthesizer bass"
- NOT "Rhodes piano" → USE "electric piano with warm tremolo"  
- NOT "TR-808 drums" → USE "punchy drum machine with deep kick"

TRACK DURATION GUIDANCE:
- Target 2-4 minutes per track (120-240 seconds)
- stable_audio tracks MUST be 120-190s (hard provider limit)
- elevenlabs can go up to 300s if needed
- DO NOT create 5+ minute tracks unless there's a good reason

TOTAL SET FLEXIBILITY (PRIMARY GOAL):
- Target duration is the PRIMARY constraint (usually ~60 minutes)
- Track count is FLEXIBLE based on library availability and duration needs
- If the library has 8 good tracks, you might only need 7-10 new ones
- If the library is empty, generate 15-18 tracks
- Total can be 55:30 or 1:01:22 - exact timing is flexible

CONSTRAINTS:
- JSON only. No preamble.
- Duration target is primary; track count is guidance, not a hard requirement.
- Prefer stable_audio for new generation to minimize cost.
"""


def create_agent_client() -> OpenAI:
    """Create an OpenAI client configured for OpenRouter."""
    s = get_settings()
    return OpenAI(
        base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key,
    )


def generate_curation_plan(
    concept: str,
    genre: str,
    candidates: list[TrackMetadata],
    track_count: int = 15,
    target_duration_minutes: int = 60,
    model: str | None = None,
) -> SessionPlan:
    """Generate a session plan mixing library tracks and new generation.

    This is the main entry point for the Curator agent. It analyzes the
    user's concept, reviews available library tracks, and creates a plan
    that optimally mixes reuse with new generation.

    Args:
        concept: User's video concept/vibe.
        genre: Target genre for the session.
        candidates: List of available tracks from the library (pre-filtered).
        track_count: Target number of tracks (flexible based on library availability).
        target_duration_minutes: Target total duration (primary constraint).
        model: LLM model to use.

    Returns:
        SessionPlan containing the complete tracklist with sources.
    """
    client = create_agent_client()
    s = get_settings()
    model = model or s.openrouter_model

    # Format candidates for the prompt
    if candidates:
        candidates_json = json.dumps([
            {
                "id": t.track_id,
                "title": t.title,
                "genre": t.genre,
                "bpm": t.bpm,
                "energy": t.energy,
                "role": t.role,
                "duration_ms": t.duration_ms,
                "last_used": t.last_used_at.isoformat() if t.last_used_at else "never"
            }
            for t in candidates
        ], indent=2)
    else:
        candidates_json = "[]  # Library is empty - generate all tracks"

    user_prompt = f"""CONCEPT: "{concept}"
GENRE: {genre}
TARGET DURATION: ~{target_duration_minutes} minutes (aim for {track_count} tracks, but flexible based on library)

CANDIDATE LIBRARY TRACKS (FREE to reuse):
{candidates_json}

Create a curation plan. Prioritize reusing library tracks that fit well. For each slot, specify 
'source': 'library' or 'generate'. Use stable_audio for most new generation.
"""

    logger.info(f"Curator Agent planning '{concept}' with {len(candidates)} candidates...")

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
        raise ValueError("Empty response from Curator Agent")

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
        slots_data = data.get("slots", [])
        bpm_range = data.get("bpm_range", [120, 130])
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from Curator: {e}")

    slots = []
    for s_data in slots_data:
        slot = TrackSlot(
            order=s_data["order"],
            role=s_data["role"],
            duration_ms=s_data["duration_ms"],
            bpm_target=s_data["bpm_target"],
            energy=s_data["energy"],
            source=s_data["source"],
            track_id=s_data.get("track_id"),
            title=s_data.get("title"),
            prompt=s_data.get("prompt"),
            provider=s_data.get("provider"),
        )
        slots.append(slot)

    return SessionPlan(
        concept=concept,
        genre=genre,
        target_duration_minutes=target_duration_minutes,
        bpm_range=tuple(bpm_range),  # type: ignore[arg-type]
        slots=slots,
        model_used=model,
    )
