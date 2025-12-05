"""Base protocol and types for music generation providers."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class ProviderCapabilities:
    """Capabilities of a music generation provider.
    
    This information is exposed to the AI agent to help it make
    informed decisions about which provider to use for each track.
    """

    name: str
    max_duration_ms: int
    min_duration_ms: int
    # Cost model: either flat per track or per millisecond
    cost_per_track: float | None  # Flat cost (e.g., Stable Audio)
    cost_per_ms: float | None  # Variable cost (e.g., ElevenLabs)
    supports_composition_plan: bool
    strengths: list[str]  # What this provider is good at


@dataclass
class GeneratedTrack:
    """Result of generating a single track from any provider."""

    order: int
    title: str  # Human-readable track name
    role: str
    prompt: str
    duration_ms: int
    audio_path: Path
    metadata_path: Path
    provider: str
    bpm: int
    energy: int


@runtime_checkable
class MusicProvider(Protocol):
    """Protocol that all music generation providers must implement."""

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return the capabilities of this provider."""
        ...

    def generate(
        self,
        prompt: str,
        duration_ms: int,
        output_dir: Path,
        filename_base: str,
        order: int = 1,
        title: str = "Untitled",
        role: str = "track",
        bpm: int = 120,
        energy: int = 5,
    ) -> GeneratedTrack:
        """Generate a track from a prompt.

        Args:
            prompt: The text prompt describing the music to generate.
            duration_ms: Target duration in milliseconds.
            output_dir: Directory to save the generated audio and metadata.
            filename_base: Base name for output files (without extension).
            order: Track order number for metadata.
            title: Human-readable track name.
            role: Track role for metadata (intro, build, peak, etc.).
            bpm: Target BPM for the track.
            energy: Energy level 1-10.

        Returns:
            GeneratedTrack with paths to saved audio and metadata files.
        """
        ...


def estimate_cost(capabilities: ProviderCapabilities, duration_ms: int) -> float:
    """Estimate the cost of generating a track with given duration.
    
    Args:
        capabilities: Provider capabilities with cost info.
        duration_ms: Duration of the track in milliseconds.
        
    Returns:
        Estimated cost in USD.
    """
    if capabilities.cost_per_track is not None:
        return capabilities.cost_per_track
    if capabilities.cost_per_ms is not None:
        return capabilities.cost_per_ms * duration_ms
    return 0.0

