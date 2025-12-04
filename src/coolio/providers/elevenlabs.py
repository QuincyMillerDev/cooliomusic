"""ElevenLabs music generation provider."""

import json
import logging
from pathlib import Path
from typing import Any

import httpx
from elevenlabs.client import ElevenLabs

from coolio.config import get_settings
from coolio.providers.base import (
    GeneratedTrack,
    MusicProvider,
    ProviderCapabilities,
)

logger = logging.getLogger(__name__)

# ElevenLabs API endpoint
ELEVENLABS_MUSIC_URL = "https://api.elevenlabs.io/v1/music"
ELEVENLABS_MODEL_ID = "music_v1"

# Timeout for music generation (seconds) - generation can take several minutes
GENERATION_TIMEOUT = 600  # 10 minutes


class ElevenLabsProvider:
    """Music generation using ElevenLabs API.
    
    ElevenLabs excels at structured compositions with clear sections.
    It supports composition plans for more control over the output.
    
    Pricing: ~$0.30/minute (~$0.005/second or $0.000005/ms)
    Max duration: 5 minutes (300,000 ms)
    """

    def __init__(self) -> None:
        s = get_settings()
        self._api_key = s.elevenlabs_api_key
        # SDK client used only for composition plan creation (fast, no streaming)
        self._client = ElevenLabs(api_key=self._api_key)
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

    def _generate_audio(
        self,
        prompt: str,
        duration_ms: int,
        use_composition_plan: bool,
    ) -> tuple[bytes, dict[str, Any] | None]:
        """Generate music via direct ElevenLabs HTTP request.

        Args:
            prompt: Text prompt describing the music.
            duration_ms: Target duration in milliseconds.
            use_composition_plan: If True, generate composition plan first.

        Returns:
            Tuple of (audio_bytes, composition_plan_dict).

        Raises:
            RuntimeError: If generation fails.
        """
        composition_plan_dict: dict[str, Any] | None = None

        if use_composition_plan:
            print("  Creating composition plan...")
            plan_obj = self.create_composition_plan(prompt, duration_ms)
            composition_plan_dict = plan_obj.model_dump()
            body: dict[str, Any] = {"composition_plan": composition_plan_dict}
        else:
            body = {
                "prompt": prompt,
                "music_length_ms": duration_ms,
            }

        body["model_id"] = ELEVENLABS_MODEL_ID

        print("  Generating audio via ElevenLabs API...")
        print(f"  Duration: {duration_ms}ms ({duration_ms/1000:.0f}s)")

        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
        }

        try:
            response = httpx.post(
                ELEVENLABS_MUSIC_URL,
                headers=headers,
                json=body,
                timeout=httpx.Timeout(
                    connect=30.0,
                    read=GENERATION_TIMEOUT,
                    write=30.0,
                    pool=60.0,
                ),
            )

            if response.status_code != 200:
                logger.error(
                    "ElevenLabs HTTP error: %s %s",
                    response.status_code,
                    response.text[:500],
                )

            response.raise_for_status()
            return response.content, composition_plan_dict

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            logger.error(
                "ElevenLabs API error %s: %s",
                status,
                e.response.text[:500],
            )
            raise RuntimeError(
                f"ElevenLabs API error {status}: {e.response.text[:200]}"
            ) from e

        except httpx.HTTPError as e:
            logger.error(f"ElevenLabs network error: {e}")
            raise RuntimeError(f"ElevenLabs network error: {e}") from e

        except Exception as e:  # pragma: no cover - defensive catch
            logger.exception("Unexpected ElevenLabs error")
            raise RuntimeError(
                "Unexpected ElevenLabs error during music generation"
            ) from e

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

        # Generate music (single request, no retry to avoid burning credits)
        audio_bytes, composition_plan_dict = self._generate_audio(
            prompt=prompt,
            duration_ms=duration_ms,
            use_composition_plan=use_composition_plan,
        )

        # Save audio file
        audio_path = output_dir / f"{filename_base}.mp3"
        metadata_path = output_dir / f"{filename_base}.json"

        with open(audio_path, "wb") as f:
            f.write(audio_bytes)

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
            "model": ELEVENLABS_MODEL_ID,
            "composition_plan": composition_plan_dict,
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
            song_metadata=None,
        )


# Type assertion to verify protocol compliance
def _check_protocol() -> MusicProvider:
    return ElevenLabsProvider()

