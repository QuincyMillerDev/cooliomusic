"""ElevenLabs music generation provider using pure SDK."""

import json
import logging
from pathlib import Path
from typing import Any

from elevenlabs.client import ElevenLabs

from coolio.config import get_settings
from coolio.providers.base import (
    GeneratedTrack,
    MusicProvider,
    ProviderCapabilities,
)

logger = logging.getLogger(__name__)


class ElevenLabsProvider:
    """Music generation using ElevenLabs SDK.
    
    Uses the official ElevenLabs Python SDK for reliable music generation.
    Handles bad_prompt errors by auto-retrying with suggested alternatives.
    
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
            supports_composition_plan=False,  # Simplified to prompt-only
            strengths=[
                "longer tracks (up to 5 min)",
                "structured compositions",
                "electronic and ambient genres",
            ],
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return provider capabilities."""
        return self._capabilities

    def _generate_with_retry(
        self,
        prompt: str,
        duration_ms: int,
    ) -> tuple[bytes, str]:
        """Generate music via SDK with bad_prompt error handling.

        Args:
            prompt: Text prompt describing the music.
            duration_ms: Target duration in milliseconds.

        Returns:
            Tuple of (audio_bytes, final_prompt_used).

        Raises:
            RuntimeError: If generation fails after retry.
        """
        print("  Generating audio via ElevenLabs SDK...")
        print(f"  Duration: {duration_ms}ms ({duration_ms/1000:.0f}s)")

        try:
            # SDK returns an iterator, collect all chunks into bytes
            audio_iter = self._client.music.compose(
                prompt=prompt,
                music_length_ms=duration_ms,
            )
            audio_bytes = b"".join(audio_iter)
            return audio_bytes, prompt

        except Exception as e:
            # Check for bad_prompt error with suggestion
            error_body: dict[str, Any] | None = getattr(e, "body", None)
            if error_body:
                detail = error_body.get("detail", {})
                if isinstance(detail, dict) and detail.get("status") == "bad_prompt":
                    data = detail.get("data", {})
                    suggested = data.get("prompt_suggestion")
                    if suggested:
                        logger.warning(
                            "Prompt rejected by ElevenLabs, retrying with suggestion"
                        )
                        print(f"  Prompt rejected (copyright?), retrying with suggestion...")
                        print(f"  New prompt: {suggested[:80]}...")
                        
                        # Retry with suggested prompt
                        audio_iter = self._client.music.compose(
                            prompt=suggested,
                            music_length_ms=duration_ms,
                        )
                        audio_bytes = b"".join(audio_iter)
                        return audio_bytes, suggested

            # Re-raise if not a bad_prompt error or no suggestion
            logger.error(f"ElevenLabs generation failed: {e}")
            raise RuntimeError(f"ElevenLabs generation failed: {e}") from e

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
        """Generate a track using ElevenLabs SDK.

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

        # Generate music with bad_prompt retry handling
        audio_bytes, final_prompt = self._generate_with_retry(
            prompt=prompt,
            duration_ms=duration_ms,
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
            "prompt": final_prompt,  # Use final prompt (may be suggested)
            "original_prompt": prompt if final_prompt != prompt else None,
            "duration_ms": duration_ms,
            "bpm": bpm,
            "energy": energy,
            "provider": "elevenlabs",
        }
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        print(f"  Saved: {audio_path.name}")

        return GeneratedTrack(
            order=order,
            title=title,
            role=role,
            prompt=final_prompt,
            duration_ms=duration_ms,
            audio_path=audio_path,
            metadata_path=metadata_path,
            provider="elevenlabs",
            bpm=bpm,
            energy=energy,
        )


# Type assertion to verify protocol compliance
def _check_protocol() -> MusicProvider:
    return ElevenLabsProvider()
