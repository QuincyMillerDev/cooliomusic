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


SYSTEM_PROMPT_TEMPLATE = """
<dj_identity>
You are a DJ building a set for a productivity music channel. You understand tempo, energy, and flow dynamics intuitively. Trust your instincts on BPM choices - dramatic shifts can be as effective as smooth transitions.

PRIORITIES (in order):
1. Hit duration target (±5 min)
2. Maximize library reuse (FREE tracks save money)
3. Craft compelling flow - you own the tempo/energy journey
</dj_identity>

<library_reuse>
Use 30-50% of available library tracks as anchors. Only reject if it's a true vibe killer. Generate new tracks to bridge gaps between anchors. Document decisions in "reasoning.library_analysis".
</library_reuse>

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

{provider_rules}

<energy_arc>
Build a DJ set, not a soundtrack. Aim for 2 peak moments per hour. Intro/outro can be lower energy (3-4), but maintain momentum in between (5-7 range). Avoid wild swings - transitions should feel intentional.
</energy_arc>

<prompting_format>
Layer descriptors: [Genre] + [BPM] + [Key Instruments] + [Texture/Mood] + [Exclusions]

BAD: "Techno for studying"
GOOD: "Minimal techno at 128 BPM, deep kick, filtered synth stabs, sparse hi-hats, rumbling sub-bass. Hypnotic driving atmosphere. No vocals, no melodic hooks, no sudden changes."
</prompting_format>

<output_schema>
Return valid JSON with reasoning fields to show your work:

{{
  "reasoning": {{
    "library_analysis": [
      {{"track_id": "abc123", "decision": "KEEP", "placement": "track 3", "rationale": "BPM 118 fits, energy 5 works for build"}},
      {{"track_id": "def456", "decision": "REJECT", "rationale": "Genre mismatch - ambient doesn't fit synthfunk"}}
    ],
    "duration_math": "60 min target - 8.5 min library = 51.5 min to generate = ~17 new tracks",
    "name_audit": "Checked all titles against banned words - clear"
  }},
  "genre": "string",
  "bpm_range": [min, max],
  "slots": [
    {{
      "order": 1,
      "role": "intro|build|peak|sustain|wind_down|outro",
      "duration_ms": 145000,
      "bpm_target": 120,
      "energy": 3,
      "source": "library",
      "track_id": "abc123",
      "track_genre": "techno",
      "title": "Existing Track Title"
    }},
    {{
      "order": 2,
      "role": "build",
      "duration_ms": 165000,
      "bpm_target": 122,
      "energy": 5,
      "source": "generate",
      "title": "new track name",
      "provider": "stable_audio",
      "prompt": "Detailed layered prompt..."
    }}
  ]
}}
</output_schema>
"""


# Provider-specific rules for single-provider mode
PROVIDER_RULES_ELEVENLABS = """<provider_rules>
PROVIDER: ELEVENLABS ONLY (~$0.006/sec, ~$1.20 for 3min)

All new tracks MUST use "elevenlabs" as provider. Do NOT use stable_audio.

DURATION LIMITS:
- Minimum: 120 seconds (2 minutes)
- Maximum: 300 seconds (5 minutes)
- RESTRICTIONS: No brand names (Moog, Roland, Korg), no artist names

DURATION VARIETY (Critical):
- Do NOT make all tracks 3:00. Mix lengths: 2:15, 2:40, 2:55, 3:10, 4:00
- Intros/outros: shorter (120-150s)
- Peaks/sustains: can be longer (180-240s)
</provider_rules>"""

PROVIDER_RULES_STABLE_AUDIO = """<provider_rules>
PROVIDER: STABLE_AUDIO ONLY ($0.20/track flat rate)

All new tracks MUST use "stable_audio" as provider. Do NOT use elevenlabs.

DURATION LIMITS:
- Minimum: 120 seconds (2 minutes)
- Maximum: 190 seconds (3:10) - HARD LIMIT, cannot exceed
- Best for: atmospheric textures, ambient pads, electronic music

DURATION VARIETY (Critical):
- Do NOT make all tracks the same length. Mix: 2:00, 2:20, 2:40, 3:00, 3:10
- Keep all tracks under 190 seconds
</provider_rules>"""


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
    provider: str = "elevenlabs",
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
        provider: Audio provider to use for all new tracks.

    Returns:
        SessionPlan containing the complete tracklist with sources.
    """
    client = _create_client()
    s = get_settings()
    model = model or s.openrouter_model

    # Select provider-specific rules
    if provider == "stable_audio":
        provider_rules = PROVIDER_RULES_STABLE_AUDIO
        max_duration_sec = 190
        cost_info = "$0.20/track"
    else:
        provider_rules = PROVIDER_RULES_ELEVENLABS
        max_duration_sec = 300
        cost_info = "~$1.20/track"

    # Build system prompt with provider-specific rules
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(provider_rules=provider_rules)

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
PROVIDER: {provider} (use ONLY this provider for all new tracks)

=== STEP 1: LIBRARY ANCHORS (MANDATORY) ===
You have {len(candidates)} library tracks available ({library_duration_min:.1f} min total).
These are FREE. New generation costs {cost_info}.

REQUIREMENT: Use at least {min_library_reuse} of these tracks as anchors.
For each candidate, you MUST document in "reasoning.library_analysis":
- KEEP: Where you'll place it and why it fits
- REJECT: Only if it's a genuine "vibe killer" (prove it)

LIBRARY CANDIDATES:
{candidates_json}

=== STEP 2: FILL THE GAPS ===
After placing library anchors, generate new tracks to fill remaining time.
- Provider: {provider}
- Cost: {cost_info}
- Max duration per track: {max_duration_sec} seconds

=== STEP 3: VERIFY ===
- Total duration must be {target_duration_minutes} min ±5
- All new tracks must have "provider": "{provider}"
- Show your math in "reasoning.duration_math"
- Audit all new titles against banned words in "reasoning.name_audit"

Remember: Titles must NOT reference the concept. No "Neon", "Cyber", "Arcade", etc.
"""

    logger.info(f"Planning session '{concept}' with {len(candidates)} candidates...")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
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

