"""AI agent for generating track plans from a video concept.

This module provides backwards-compatible access to session planning.
It delegates to the Curator agent with an empty library, which handles
all the prompt crafting and track planning.

For the full curation flow (with library reuse), use the Curator agent directly.
"""

from coolio.agents.curator import generate_curation_plan
from coolio.models import SessionPlan, TrackSlot

# Backwards compatibility aliases
TrackPlan = TrackSlot


def estimate_session_cost(slots: list[TrackSlot]) -> float:
    """Calculate estimated cost for a session plan.

    Args:
        slots: List of track slots.

    Returns:
        Total estimated cost in USD.
    """
    return sum(slot.estimated_cost() for slot in slots)


def generate_session_plan(
    concept: str,
    track_count: int = 15,
    target_duration_minutes: int = 60,
    budget: float = 5.00,
    model: str | None = None,
    genre: str = "electronic",
) -> SessionPlan:
    """Generate a complete session plan from a video concept.

    This function creates a session plan without checking the library.
    All tracks will be marked for generation. For plans that reuse
    library tracks, use the Curator agent directly.

    Args:
        concept: High-level description (genre, vibe, mood, purpose).
        track_count: Target number of tracks (flexible, duration is primary).
        target_duration_minutes: Target total duration in minutes (primary constraint).
        budget: Maximum cost in USD (informational, not enforced).
        model: OpenRouter model to use (defaults to settings).
        genre: Genre for organization (extracted from concept if not specified).

    Returns:
        SessionPlan with all slots marked as source="generate".
    """
    # Delegate to Curator with empty candidates (no library reuse)
    return generate_curation_plan(
        concept=concept,
        genre=genre,
        candidates=[],  # Empty = generate everything
        track_count=track_count,
        target_duration_minutes=target_duration_minutes,
        model=model,
    )
