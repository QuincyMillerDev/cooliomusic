"""AI agent for generating track plans from a video concept."""

import json
from dataclasses import dataclass

from openai import OpenAI

from coolio.core.config import get_settings


@dataclass
class TrackPlan:
    """A plan for a single track in the video."""

    order: int
    role: str  # e.g., "intro", "build", "peak", "cooldown", "outro"
    prompt: str  # The prompt for ElevenLabs
    duration_ms: int
    notes: str  # AI's reasoning for this track


@dataclass
class SessionPlan:
    """Complete plan for all tracks in a video session."""

    concept: str  # Original user concept
    total_tracks: int
    tracks: list[TrackPlan]
    model_used: str


SYSTEM_PROMPT = """You are a music director planning tracks for a multi-hour YouTube study/productivity music video.

Given a video concept (genre, vibe, mood, purpose), you will generate a list of track specifications that together create a cohesive listening experience.

Each track should:
- Have a clear role in the overall flow (intro, build, peak, cooldown, outro, etc.)
- Be described with a detailed prompt suitable for AI music generation
- Vary slightly to maintain interest while staying cohesive
- Be 2-5 minutes in duration (specify in milliseconds)

Your prompts should be detailed and specific, including:
- Genre and subgenre
- Tempo/BPM range
- Instruments and sounds
- Mood and energy level
- Any specific production techniques

Output ONLY valid JSON in this exact format:
{
  "tracks": [
    {
      "order": 1,
      "role": "intro",
      "prompt": "Detailed prompt for music generation...",
      "duration_ms": 180000,
      "notes": "Why this track works here..."
    }
  ]
}"""


def create_agent_client() -> OpenAI:
    """Create an OpenAI client configured for OpenRouter."""
    s = get_settings()
    return OpenAI(
        base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key,
    )


def generate_session_plan(
    concept: str,
    track_count: int = 5,
    model: str | None = None,
) -> SessionPlan:
    """
    Generate a complete session plan from a video concept.

    Args:
        concept: High-level description of the video (genre, vibe, purpose)
        track_count: Number of tracks to generate plans for
        model: OpenRouter model to use (defaults to settings)

    Returns:
        SessionPlan with all track specifications
    """
    client = create_agent_client()
    s = get_settings()
    model = model or s.openrouter_model

    user_prompt = f"""Create a plan for {track_count} tracks for this video concept:

"{concept}"

The tracks should flow together naturally for a study/productivity session. 
Each track should be between {s.min_track_duration_ms}ms and {s.max_track_duration_ms}ms.
Default to around {s.default_track_duration_ms}ms (3 minutes) unless the flow calls for something different.

Remember: Output ONLY valid JSON, no markdown, no explanation."""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    if not content:
        raise ValueError("AI model returned empty response")
    data = json.loads(content)

    tracks = [
        TrackPlan(
            order=t["order"],
            role=t["role"],
            prompt=t["prompt"],
            duration_ms=t["duration_ms"],
            notes=t.get("notes", ""),
        )
        for t in data["tracks"]
    ]

    return SessionPlan(
        concept=concept,
        total_tracks=len(tracks),
        tracks=tracks,
        model_used=model,
    )

