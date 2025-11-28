"""Stable Audio music generation provider."""

import json
from pathlib import Path
from typing import Any

import httpx

from coolio.core.config import get_settings
from coolio.music.providers.base import (
    GeneratedTrack,
    MusicProvider,
    ProviderCapabilities,
)


class StableAudioProvider:
    """Music generation using Stability AI's Stable Audio API.
    
    Stable Audio excels at electronic textures, ambient soundscapes,
    and atmospheric music. It uses a flat pricing model per generation.
    
    Pricing: $0.20/track (20 credits at $0.01/credit)
    Max duration: 190 seconds (~3.1 minutes)
    
    API Reference: https://platform.stability.ai/docs/api-reference#tag/Text-to-Audio
    """

    API_URL = "https://api.stability.ai/v2beta/audio/stable-audio-2/text-to-audio"

    def __init__(self) -> None:
        s = get_settings()
        self._api_key = s.stability_api_key
        self._model = s.stable_audio_model
        self._capabilities = ProviderCapabilities(
            name="stable_audio",
            max_duration_ms=190_000,  # 190 seconds
            min_duration_ms=1_000,  # 1 second
            cost_per_track=0.20,  # Flat rate
            cost_per_ms=None,
            supports_composition_plan=False,
            strengths=[
                "electronic textures",
                "ambient soundscapes",
                "atmospheric backgrounds",
                "synthwave and retro sounds",
                "cost-effective for bulk generation",
            ],
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return provider capabilities."""
        return self._capabilities

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
        """Generate a track using Stable Audio API.

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

        Returns:
            GeneratedTrack with paths to saved files.
        """
        # Clamp duration to provider limits
        duration_ms = max(
            self._capabilities.min_duration_ms,
            min(duration_ms, self._capabilities.max_duration_ms),
        )
        duration_seconds = duration_ms / 1000.0

        print(f"  Generating audio with Stable Audio ({duration_seconds:.1f}s)...")

        # Prepare the form data
        form_data = {
            "prompt": prompt,
            "duration": str(int(duration_seconds)),  # Must be integer
            "model": self._model,
            "output_format": "mp3",
        }

        # Make the API request
        # Note: files={"none": ""} forces multipart/form-data encoding
        with httpx.Client(timeout=300.0) as client:
            response = client.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "audio/*",
                },
                data=form_data,
                files={"none": ("", "")},  # Force multipart encoding
            )

        # Handle errors
        if response.status_code != 200:
            error_detail = response.text
            raise RuntimeError(
                f"Stable Audio API error ({response.status_code}): {error_detail}\n"
                f"URL: {self.API_URL}"
            )

        # Save audio file
        audio_path = output_dir / f"{filename_base}.mp3"
        metadata_path = output_dir / f"{filename_base}.json"

        with open(audio_path, "wb") as f:
            f.write(response.content)

        # Save metadata
        metadata: dict[str, Any] = {
            "order": order,
            "title": title,
            "role": role,
            "prompt": prompt,
            "duration_ms": duration_ms,
            "bpm": bpm,
            "energy": energy,
            "provider": "stable_audio",
            "model": self._model,
            "composition_plan": None,
            "song_metadata": None,
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
            provider="stable_audio",
            bpm=bpm,
            energy=energy,
            composition_plan=None,
            song_metadata=None,
        )


# Type assertion to verify protocol compliance
def _check_protocol() -> MusicProvider:
    return StableAudioProvider()

