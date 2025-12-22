"""Session planner for creating tracklists with library reuse.

Acts as a DJ that can select existing tracks from the library or request
new generation to fill gaps. This runs before the Generator to produce
a SessionPlan.
"""

import json
import logging
import re

from openai import OpenAI

from coolio.config import get_settings
from coolio.library.metadata import TrackMetadata
from coolio.models import SessionPlan, TrackSlot

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_TEMPLATE = """
<curator_identity>
You are a music curator building playlists for a productivity music channel. Your goal is to create varied, high-quality playlists that maintain listener engagement through natural variety in mood and intensity.

PRIORITIES (in order):
1. Hit duration target (±5 min)
2. Maintain playlist coherence and genre fit (do NOT stretch reuse)
3. Create natural variety - vary mood and intensity across tracks
4. Minimize cost (library reuse is free, but optional)
</curator_identity>

<library_reuse>
Library reuse is OPTIONAL and must never compromise fit.

Rules:
- Only reuse a library track if it clearly fits the session vibe and sequence.
- It is OK to reuse 0 tracks (prefer generating new tracks over forcing reuse).
- Document decisions in "reasoning.library_analysis" for any library candidates you considered.
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

<playlist_variety>
Create natural variety across the playlist. Vary mood, intensity, and texture naturally:
- Mix driving tracks with atmospheric ones
- Balance tension with release
- Use the full palette of the genre without explicit "roles"
- Trust your instincts on what makes a compelling sequence
</playlist_variety>

<prompting_format>
Write prompts like a human producer, not a checklist.

Make each prompt descriptive but NOT over-specified. Avoid rigid templates, BPM math,
and detailed drum programming unless the concept explicitly calls for it.

Aim for:
- 1–2 sentences: mood/style + genre + use-case context
- 0–2 optional lines: Include: ... / Exclude: ...
- 2–4 instruments/textures MAX (don’t force drums into every prompt)

HIGH-LEVERAGE RULE (read carefully):
- Describe the FEEL and MOTION (tension/release, energy curve, texture, space) more than the instruments.
- Do NOT name specific drum elements (kick, hats, snare, clap, 909/808, rimshot, ghost notes)
  unless the user's concept explicitly requests percussion-forward music.
- If rhythm is relevant, describe it as a feel: "subtle propulsion", "steady pulse", "gentle groove",
  "hypnotic forward motion" — not as a drum list.

Default percussion behavior:
- If the concept does not explicitly ask for percussion-forward music, keep drums
  subtle/supportive or omit them entirely. Prefer texture, harmony, and gentle movement.
</prompting_format>

<audio_vocabulary>
Use natural production terminology, but only when it helps.

PREFERRED (texture/mix-first):
- Space: room/plate reverb, long tails, delay washes, distant ambience
- Warmth: tape saturation, gentle compression, soft clipping (avoid harshness)
- Motion: slow filter movement, tremolo, subtle modulation, evolving pads
- Harmony/tones: electric piano, soft synth pads, mellow stabs, airy plucks
- Energy/arc: restrained build, slow bloom, gliding transitions, tension then soft release
- Feel words: weightless, grounded, elastic, hazy, clean, intimate, wide, submerged

OPTIONAL (rhythm, only if relevant):
- Rhythm feel (preferred): subtle propulsion, steady pulse, gentle groove, patient momentum
- Percussion (only if explicitly requested): soft percussion, minimal groove

BE AS DESCRIPTIVE AS POSSIBLE. You are a music producer who excels at describing music, not a checklist.

Avoid heavy transient-forward drums unless explicitly requested.
</audio_vocabulary>

<output_schema>
Return valid JSON with reasoning fields to show your work:

{{
  "reasoning": {{
    "library_analysis": [
      {{"track_id": "abc123", "decision": "KEEP", "placement": "track 3", "rationale": "Fits the mood, good variety"}},
      {{"track_id": "def456", "decision": "REJECT", "rationale": "Genre mismatch - ambient doesn't fit synthfunk"}}
    ],
    "duration_math": "60 min target - 8.5 min library = 51.5 min to generate = ~17 new tracks",
    "name_audit": "Checked all titles against banned words - clear"
  }},
  "genre": "string",
  "slots": [
    {{
      "order": 1,
      "duration_ms": 145000,
      "source": "library",
      "track_id": "abc123",
      "track_genre": "techno",
      "title": "Existing Track Title"
    }},
    {{
      "order": 2,
      "duration_ms": 165000,
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
- Shorter tracks: good for transitions or interludes (120-150s)
- Longer tracks: can build more atmosphere (180-240s)
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


_GENRE_INFERENCE_SYSTEM_PROMPT = """You infer a single canonical genre slug for a music session.

Return ONLY valid JSON of the form:
{"genre": "<slug>"}

Rules for <slug>:
- lowercase
- 1-40 chars
- only letters, numbers, underscores, hyphens
- no spaces, no prose, no extra keys
"""


def _sanitize_genre_slug(value: str) -> str:
    v = (value or "").strip().lower()
    v = re.sub(r"\\s+", "_", v)
    v = re.sub(r"[^a-z0-9_-]", "", v)
    v = v.strip("_-")
    if not v:
        return "unknown"
    return v[:40]


def infer_genre(concept: str, *, model: str | None = None) -> str:
    """Infer a canonical genre slug from a free-form concept.

    This is used *before* querying the library so we can strictly filter reuse
    candidates by exact genre.
    """
    client = _create_client()
    s = get_settings()
    model = model or s.openrouter_model

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _GENRE_INFERENCE_SYSTEM_PROMPT},
                {"role": "user", "content": f'CONCEPT: "{concept}"'},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        logger.warning("Genre inference failed: %s", e)
        return "unknown"

    content = response.choices[0].message.content
    if not content:
        return "unknown"

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Occasionally models still emit markdown; try a minimal cleanup.
        cleaned = content.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.find("\\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1 :]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
        try:
            data = json.loads(cleaned)
        except Exception:
            return "unknown"

    genre = data.get("genre")
    if not isinstance(genre, str):
        return "unknown"
    return _sanitize_genre_slug(genre)


def generate_session_plan(
    concept: str,
    candidates: list[TrackMetadata],
    target_duration_minutes: int = 60,
    model: str | None = None,
    provider: str = "elevenlabs",
    fixed_genre: str | None = None,
) -> SessionPlan:
    """Generate a session plan mixing library tracks and new generation.

    This is the main entry point for session planning. It analyzes the
    user's concept, reviews available library tracks, and creates a plan
    that optimally mixes reuse with new generation.

    The LLM can infer the appropriate genre from the concept, but callers may
    also pin a fixed genre for strict library reuse.

    Args:
        concept: User's video concept/vibe (genre, mood, purpose).
        candidates: List of available tracks from the library.
        target_duration_minutes: Target total duration (primary constraint).
        model: LLM model to use.
        provider: Audio provider to use for all new tracks.
        fixed_genre: If provided, force the session genre to this value.

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
                "duration_ms": t.duration_ms,
                "last_used": t.last_used_at.isoformat() if t.last_used_at else "never"
            }
            for t in candidates
        ], indent=2)
    else:
        candidates_json = "[]  # Library is empty - generate all tracks"

    genre_line = f'SESSION GENRE (fixed): "{fixed_genre}"\\n' if fixed_genre else ""

    user_prompt = f"""CONCEPT: "{concept}"
{genre_line}TARGET DURATION: {target_duration_minutes} minutes
PROVIDER: {provider} (use ONLY this provider for all new tracks)

=== STEP 1: OPTIONAL LIBRARY REUSE (STRICT) ===
You have {len(candidates)} library tracks available. These are FREE. New generation costs {cost_info}.

Reuse is OPTIONAL. Prefer generating new tracks over forcing reuse.
If you reuse a library track, it must clearly fit the session vibe and sequence.
For each candidate you consider, document in "reasoning.library_analysis":
- KEEP: Where you'll place it and why it fits
- REJECT: Why it doesn't fit

LIBRARY CANDIDATES:
{candidates_json}

=== STEP 2: FILL THE GAPS ===
After placing library anchors, generate new tracks to fill remaining time.
- Provider: {provider}
- Cost: {cost_info}
- Max duration per track: {max_duration_sec} seconds

Create natural variety:
- Vary mood and intensity across tracks
- Mix driving tracks with atmospheric ones
- Balance tension with release
- Trust your instincts on what makes a compelling sequence

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
        model_genre = data.get("genre", "unknown")
        genre = _sanitize_genre_slug(fixed_genre) if fixed_genre else _sanitize_genre_slug(str(model_genre))
        slots_data = data.get("slots", [])
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from planner: {e}")

    slots = []
    for s_data in slots_data:
        slot = TrackSlot(
            order=s_data["order"],
            duration_ms=s_data["duration_ms"],
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
        slots=slots,
        model_used=model,
    )

