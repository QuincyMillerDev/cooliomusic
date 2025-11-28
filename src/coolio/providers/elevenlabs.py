"""ElevenLabs music generation provider."""

import json
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

from elevenlabs.client import ElevenLabs

from coolio.config import get_settings
from coolio.providers.base import (
    GeneratedTrack,
    MusicProvider,
    ProviderCapabilities,
)


@runtime_checkable
class DetailedComposition(Protocol):
    """Subset of attributes returned by ElevenLabs compose_detailed."""

    json: dict[str, Any] | None
    audio: bytes


class ElevenLabsProvider:
    """Music generation using ElevenLabs API.
    
    ElevenLabs excels at structured compositions with clear sections.
    It supports composition plans for more control over the output.
    
    Pricing: ~$0.30/minute (~$0.005/second or $0.000005/ms)
    Max duration: 5 minutes (300,000 ms)
    """

    def __init__(self) -> None:
        s = get_settings()
        self._client = ElevenLabs(api_key=s.elevenlabs_api_key)
        self._capabilities = ProviderCapabilities(
            name="elevenlabs",
            max_duration_ms=300_000,  # 5 minutes
            min_duration_ms=10_000,  # 10 seconds
            cost_per_track=None,
            cost_per_ms=0.000005,  # ~$0.30/min
            supports_composition_plan=True,
            strengths=[
                "structured compositions",
                "clear musical sections",
                "vocals and lyrics",
                "composition plans for control",
            ],
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return provider capabilities."""
        return self._capabilities

    def create_composition_plan(self, prompt: str, duration_ms: int) -> Any:
        """Generate a composition plan from a prompt.

        This doesn't consume significant credits - it's just planning.
        Returns the raw MusicPrompt object from ElevenLabs.
        """
        return self._client.music.composition_plan.create(
            prompt=prompt,
            music_length_ms=duration_ms,
        )

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
        use_composition_plan: bool = True,
    ) -> GeneratedTrack:
        """Generate a track using ElevenLabs API.

        Args:
            prompt: Text prompt describing the music.
            duration_ms: Target duration in milliseconds.
            output_dir: Directory to save output files.
            filename_base: Base name for files (without extension).
            order: Track order number.
            title: Human-readable track name.
            role: Track role (intro, build, peak, etc.).
            bpm: Target BPM for the track.
            energy: Energy level 1-10.
            use_composition_plan: If True, generate composition plan first.

        Returns:
            GeneratedTrack with paths to saved files.
        """
        # Clamp duration to provider limits
        duration_ms = max(
            self._capabilities.min_duration_ms,
            min(duration_ms, self._capabilities.max_duration_ms),
        )

        composition_plan_dict: dict[str, Any] | None = None
        song_metadata: dict[str, Any] | None = None

        # Generate music (with or without prior composition plan)
        if use_composition_plan:
            print("  Creating composition plan...")
            plan_obj = self.create_composition_plan(prompt, duration_ms)

            print("  Generating audio from plan...")
            track_details_raw = self._client.music.compose_detailed(
                composition_plan=plan_obj,
            )
        else:
            print("  Generating audio from prompt...")
            track_details_raw = self._client.music.compose_detailed(
                prompt=prompt,
                music_length_ms=duration_ms,
            )

        # Cast to our protocol for type safety
        track_details = cast(DetailedComposition, track_details_raw)

        # Extract metadata from response
        if track_details.json:
            if "composition_plan" in track_details.json:
                composition_plan_dict = track_details.json["composition_plan"]
            if "song_metadata" in track_details.json:
                song_metadata = track_details.json["song_metadata"]

        # Save audio file
        audio_path = output_dir / f"{filename_base}.mp3"
        metadata_path = output_dir / f"{filename_base}.json"

        with open(audio_path, "wb") as f:
            f.write(track_details.audio)

        # Save metadata
        metadata = {
            "order": order,
            "title": title,
            "role": role,
            "prompt": prompt,
            "duration_ms": duration_ms,
            "bpm": bpm,
            "energy": energy,
            "provider": "elevenlabs",
            "composition_plan": composition_plan_dict,
            "song_metadata": song_metadata,
        }
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        print(f"  Saved: {audio_path.name}")

        return GeneratedTrack(
            order=order,
            title=title,
            role=role,
            prompt=prompt,
            duration_ms=duration_ms,
            audio_path=audio_path,
            metadata_path=metadata_path,
            provider="elevenlabs",
            bpm=bpm,
            energy=energy,
            composition_plan=composition_plan_dict,
            song_metadata=song_metadata,
        )


# Type assertion to verify protocol compliance
def _check_protocol() -> MusicProvider:
    return ElevenLabsProvider()

