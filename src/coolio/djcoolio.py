"""Session planner for creating tracklists with library reuse.

Acts as a DJ that can select existing tracks from the library or request
new generation to fill gaps. This runs before the Generator to produce
a SessionPlan.
"""

import json
import logging

from openai import OpenAI

from coolio.config import get_settings
from coolio.library.metadata import TrackMetadata
from coolio.models import SessionPlan, TrackSlot

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
<system_role>
You are the Lead Curator for a productivity music channel. Your directive is to build high-flow, cost-efficient playlists.
You operate on "Cost-First, Creative-Second" logic.
</system_role>

<priority_hierarchy>
1. HIT DURATION TARGET (±5 min) - Non-negotiable
2. MAXIMIZE LIBRARY REUSE (Save Money) - Library tracks are FREE
3. ENSURE FLOW (BPM ±5, Energy arc)
4. CREATIVE VIBE (Naming/Prompts) - Last priority
</priority_hierarchy>

<library_anchor_protocol>
You are NOT choosing WHETHER to use library tracks. You are determining WHERE to place them.

IF CANDIDATES EXIST:
1. Force-fit at least 30-50% of available candidates.
2. "Good Enough" Rule:
   - Genre: If it's electronic/instrumental, it probably fits.
   - BPM: ±10 BPM is acceptable (DJs pitch-shift all the time).
   - Energy: ±2 Energy is acceptable.
3. ONLY reject a candidate if it is a "Vibe Killer" (e.g., Heavy Metal in a Lofi set).
4. Treat accepted library tracks as ANCHORS. Generate new tracks to BRIDGE THE GAPS between them.

You MUST document your library decisions in the "reasoning" field.
</library_anchor_protocol>

<naming_firewall>
BANNED - These will get your output rejected:

1. CONCEPT LEAK (Dynamic):
   - If concept mentions "Stranger Things" → BAN: Hawkins, Eleven, Upside Down, Demogorgon, Byers, Lab, etc.
   - If concept mentions "arcade" or "retro" → BAN: Arcade, Retro, Gaming, Pixel, 8-bit
   - Rule: Words from the user's concept description should NOT appear in titles.

2. AI CLICHÉS (Always banned):
   Neon, Cyber, Synthwave, Vibes, Chill, Lofi, Beats, Pulse, Digital, Cosmic, 
   Electric, Midnight, Dream, Journey, Wave, Glow, Grid, Matrix, Chrome

3. FAMOUS SONG TITLES:
   Do not use titles of well-known songs (November Rain, Bohemian Rhapsody, etc.)

4. GENRE-IN-TITLE:
   No "Techno Pulse", "House Grooves", "Ambient Dreams"

REQUIRED AESTHETIC:
- Authentic, varied naming that feels like a real artist's discography
- MIX these formats across the tracklist (don't use just one style):

  LOWERCASE PHRASES: "i remember", "not yet", "easy now", "so it goes"
  TITLE CASE: "Last Dance", "Paper Thin", "The Lobby", "Side B"  
  SINGLE WORDS: "Ceremony", "Transmission", "Polygon", "Sway"
  NUMBERS/TIMES: "505", "1979", "4am", "23:45", "Track 7"
  FOREIGN WORDS: "Diciembre", "Nach Berlin", "À Bientôt"
  MINIMAL/ABSTRACT: "Untitled 4", "Pt. 2", "VCR", "II"
  WITH PUNCTUATION: "Wait—", "So?", "(You)", "Mr. November"

- VARIETY IS MANDATORY: Use at least 3-4 different naming styles per tracklist
- Avoid: all_lowercase_underscore for every track (lazy AI pattern)
</naming_firewall>

<provider_rules>
ELEVENLABS (~$0.006/sec, ~$1.20 for 3min) - PRIMARY PROVIDER:
- Duration: 120-300 seconds
- Use for: 70% of new generation (all main tracks: build, peak, sustain)
- RESTRICTIONS: No brand names (Moog, Roland, Korg), no artist names

STABLE_AUDIO ($0.20/track flat) - TEXTURE ONLY:
- Duration: 120-190 seconds (HARD LIMIT - cannot exceed 190s)
- Use for: 30% of new generation (intros, outros, ambient transitions)
- Best for: atmospheric textures, ambient pads, transitional moments

DURATION VARIETY (Critical):
- Do NOT make all tracks 3:00. Mix lengths: 2:15, 2:40, 2:55, 3:10
- Intros/outros: shorter (120-150s) via stable_audio
- Peaks/sustains: can be longer (180-240s) via elevenlabs
</provider_rules>

<energy_protocol>
You are a REAL DJ building a set, not a soundtrack composer.

ENERGY RULES:
1. MAINTAIN FLOOR ENERGY: Keep energy relatively constant (range of 3-4 points max)
   - Bad: 3 → 7 → 2 → 6 → 1 (wild swings kill the vibe)
   - Good: 5 → 6 → 5 → 7 → 6 → 5 (controlled flow)

2. MINIMUM 2 PEAKS: Every 60-min set needs at least 2 peak moments
   - Peaks are energy 6-7, not necessarily the maximum possible
   - Peaks should be at ~25% and ~70% through the set

3. VALLEYS ARE SUBTLE: Wind-downs drop 1-2 energy points, not to zero
   - A "valley" is energy 4-5, not energy 1-2
   - Maintain momentum even during cool-down sections

4. INTRO/OUTRO EXCEPTION: Only intro (track 1) and outro (last 1-2 tracks) 
   can have lower energy (3-4). Everything else stays 5-7.

ENERGY ARC TEMPLATE for 60-min set:
- Tracks 1-2: Energy 4-5 (warm up)
- Tracks 3-8: Energy 5-6 (cruising)
- Tracks 9-11: Energy 6-7 (first peak)
- Tracks 12-15: Energy 5-6 (sustain)
- Tracks 16-18: Energy 6-7 (second peak)
- Tracks 19-20: Energy 5-4 (wind down)
- Track 21+: Energy 3-4 (outro)
</energy_protocol>

<prompting_format>
Layer descriptors: [Genre] + [BPM] + [Key Instruments] + [Texture/Mood] + [Exclusions]

BAD: "Techno for studying"
GOOD: "Minimal techno at 128 BPM, deep kick, filtered synth stabs, sparse hi-hats, rumbling sub-bass. Hypnotic driving atmosphere. No vocals, no melodic hooks, no sudden changes."
</prompting_format>

<output_schema>
Return valid JSON with reasoning fields to show your work:

{
  "reasoning": {
    "library_analysis": [
      {"track_id": "abc123", "decision": "KEEP", "placement": "track 3", "rationale": "BPM 118 fits, energy 5 works for build"},
      {"track_id": "def456", "decision": "REJECT", "rationale": "Genre mismatch - ambient doesn't fit synthfunk"}
    ],
    "duration_math": "60 min target - 8.5 min library = 51.5 min to generate = ~17 new tracks",
    "name_audit": "Checked all titles against banned words - clear"
  },
  "genre": "string",
  "bpm_range": [min, max],
  "slots": [
    {
      "order": 1,
      "role": "intro|build|peak|sustain|wind_down|outro",
      "duration_ms": 145000,
      "bpm_target": 120,
      "energy": 3,
      "source": "library",
      "track_id": "abc123",
      "track_genre": "techno",
      "title": "Existing Track Title"
    },
    {
      "order": 2,
      "role": "build",
      "duration_ms": 165000,
      "bpm_target": 122,
      "energy": 5,
      "source": "generate",
      "title": "new track name",
      "provider": "stable_audio",
      "prompt": "Detailed layered prompt..."
    }
  ]
}
</output_schema>
"""


def _create_client() -> OpenAI:
    """Create an OpenAI client configured for OpenRouter."""
    s = get_settings()
    return OpenAI(
        base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key,
    )


def generate_session_plan(
    concept: str,
    candidates: list[TrackMetadata],
    target_duration_minutes: int = 60,
    model: str | None = None,
) -> SessionPlan:
    """Generate a session plan mixing library tracks and new generation.

    This is the main entry point for session planning. It analyzes the
    user's concept, reviews available library tracks, and creates a plan
    that optimally mixes reuse with new generation.

    The LLM infers the appropriate genre from the concept.

    Args:
        concept: User's video concept/vibe (genre, mood, purpose).
        candidates: List of available tracks from the library.
        target_duration_minutes: Target total duration (primary constraint).
        model: LLM model to use.

    Returns:
        SessionPlan containing the complete tracklist with sources.
    """
    client = _create_client()
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

    # Calculate library duration if candidates exist
    library_duration_min = sum(t.duration_ms for t in candidates) / 60000 if candidates else 0
    min_library_reuse = max(1, len(candidates) // 3) if candidates else 0  # At least 30%

    user_prompt = f"""CONCEPT: "{concept}"
TARGET DURATION: {target_duration_minutes} minutes

=== STEP 1: LIBRARY ANCHORS (MANDATORY) ===
You have {len(candidates)} library tracks available ({library_duration_min:.1f} min total).
These are FREE. New generation costs $0.20-$1.20 per track.

REQUIREMENT: Use at least {min_library_reuse} of these tracks as anchors.
For each candidate, you MUST document in "reasoning.library_analysis":
- KEEP: Where you'll place it and why it fits
- REJECT: Only if it's a genuine "vibe killer" (prove it)

LIBRARY CANDIDATES:
{candidates_json}

=== STEP 2: FILL THE GAPS ===
After placing library anchors, generate new tracks to fill remaining time.
- elevenlabs: ~$1.20/track, up to 300s (use for 70% - all main tracks: build, peak, sustain)
- stable_audio: $0.20/track, max 190s (use for 30% - intros, outros, textures only)

=== STEP 3: VERIFY ===
- Total duration must be {target_duration_minutes} min ±5
- Show your math in "reasoning.duration_math"
- Audit all new titles against banned words in "reasoning.name_audit"

Remember: Titles must NOT reference the concept. No "Neon", "Cyber", "Arcade", etc.
"""

    logger.info(f"Planning session '{concept}' with {len(candidates)} candidates...")

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
        raise ValueError("Empty response from planner")

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
        genre = data.get("genre", "electronic")
        slots_data = data.get("slots", [])
        bpm_range = data.get("bpm_range", [120, 130])
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from planner: {e}")

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
            track_genre=s_data.get("track_genre"),
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

