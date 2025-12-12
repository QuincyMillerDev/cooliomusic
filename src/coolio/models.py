"""Shared data models for the Coolio music generation system.

This module contains dataclasses used across multiple components:
- TrackSlot: Unified model for track planning (used by both Curator and Generator agents)
- SessionPlan: Complete plan for a music session
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TrackSlot:
    """A single slot in a session plan.

    This unified model supports both library reuse and new generation
    in a single structure.

    Attributes:
        order: Position in the tracklist (1-indexed).
        duration_ms: Target duration in milliseconds.
        source: Whether to reuse from library or generate new.
        track_id: R2 track ID (required if source="library").
        track_genre: Original genre folder where track is stored (for library tracks).
        title: Human-readable track name.
        prompt: Generation prompt (required if source="generate").
        provider: Music provider ("elevenlabs" or "stable_audio").
    """

    order: int
    duration_ms: int
    source: Literal["library", "generate"]

    # For library tracks (source="library")
    track_id: str | None = None
    track_genre: str | None = None

    # For generation (source="generate") or library tracks with known title
    title: str | None = None
    prompt: str | None = None
    provider: str | None = None  # "elevenlabs" or "stable_audio"

    def estimated_cost(self) -> float:
        """Calculate estimated cost for this slot.

        Returns:
            Cost in USD. Library tracks are free, stable_audio is flat $0.20,
            elevenlabs is ~$0.30/min ($0.000005/ms).
        """
        if self.source == "library":
            return 0.0
        if self.provider == "stable_audio":
            return 0.20
        if self.provider == "elevenlabs":
            return self.duration_ms * 0.000005
        return 0.0


@dataclass
class SessionPlan:
    """Complete plan for a music session.

    Contains all track slots (both library reuse and generation requests)
    along with session-level metadata.
    """

    concept: str  # Original user concept/prompt
    genre: str  # Primary genre for the session
    target_duration_minutes: int
    slots: list[TrackSlot] = field(default_factory=list)
    model_used: str = ""

    @property
    def total_tracks(self) -> int:
        """Total number of tracks in the plan."""
        return len(self.slots)

    @property
    def library_tracks(self) -> list[TrackSlot]:
        """Tracks to be reused from library."""
        return [s for s in self.slots if s.source == "library"]

    @property
    def generation_tracks(self) -> list[TrackSlot]:
        """Tracks to be newly generated."""
        return [s for s in self.slots if s.source == "generate"]

    @property
    def estimated_cost(self) -> float:
        """Total estimated cost for generating new tracks."""
        return sum(slot.estimated_cost() for slot in self.slots)

    @property
    def estimated_duration_ms(self) -> int:
        """Total estimated duration in milliseconds."""
        return sum(slot.duration_ms for slot in self.slots)

    @property
    def estimated_duration_minutes(self) -> float:
        """Total estimated duration in minutes."""
        return self.estimated_duration_ms / 60000

