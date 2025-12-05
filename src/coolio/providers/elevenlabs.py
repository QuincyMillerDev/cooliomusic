"""ElevenLabs music generation provider using pure SDK."""

import json
import logging
import random
import time
from pathlib import Path
from typing import Any

from elevenlabs.client import ElevenLabs

from coolio.config import get_settings
from coolio.providers.base import (
    GeneratedTrack,
    MusicProvider,
    ProviderCapabilities,
)

# Transient error patterns that warrant retry
TRANSIENT_ERROR_PATTERNS = [
    "server disconnected",
    "connection reset",
    "connection refused", 
    "timeout",
    "temporarily unavailable",
    "service unavailable",
    "remote end closed connection",
    "broken pipe",
    "eof occurred",
    "502",
    "503",
    "504",
]

logger = logging.getLogger(__name__)


class ElevenLabsProvider:
    """Music generation using ElevenLabs SDK.
    
    Uses the official ElevenLabs Python SDK for reliable music generation.
    Handles bad_prompt errors by auto-retrying with suggested alternatives.
    Implements exponential backoff with jitter for transient network errors.
    
    Pricing: ~$0.30/minute (~$0.005/second or $0.000005/ms)
    Max duration: 5 minutes (300,000 ms)
    
    Rate Limits (per ElevenLabs docs):
    - Concurrency limits vary by tier (Free: 2, higher tiers: more)
    - Music generation is long-running and can timeout on unstable connections
    """

    # Cooldown between API calls to avoid hitting rate limits
    COOLDOWN_SECONDS = 5.0
    # Maximum retries for transient errors
    MAX_RETRIES = 3
    # Base delay for exponential backoff (seconds)
    BASE_DELAY = 10.0
    # Maximum delay between retries (seconds)  
    MAX_DELAY = 120.0

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = ElevenLabs(api_key=self._settings.elevenlabs_api_key)
        self._last_request_time: float = 0.0
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

    def _recreate_client(self) -> None:
        """Create a fresh HTTP client to avoid stale connection issues."""
        self._client = ElevenLabs(api_key=self._settings.elevenlabs_api_key)

    def _is_transient_error(self, error: Exception) -> bool:
        """Check if an error is transient and worth retrying."""
        error_str = str(error).lower()
        return any(pattern in error_str for pattern in TRANSIENT_ERROR_PATTERNS)

    def _wait_for_cooldown(self) -> None:
        """Wait if needed to respect cooldown between API calls."""
        if self._last_request_time > 0:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.COOLDOWN_SECONDS:
                wait_time = self.COOLDOWN_SECONDS - elapsed
                logger.debug(f"Cooldown: waiting {wait_time:.1f}s before next request")
                time.sleep(wait_time)

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return provider capabilities."""
        return self._capabilities

    def _generate_with_retry(
        self,
        prompt: str,
        duration_ms: int,
    ) -> tuple[bytes, str]:
        """Generate music via SDK with exponential backoff for transient errors.

        Implements retry logic with:
        - Exponential backoff with jitter for transient network errors
        - Fresh client creation between retries to avoid stale connections
        - Cooldown between requests to respect rate limits
        - Bad prompt error handling with suggested alternatives

        Args:
            prompt: Text prompt describing the music.
            duration_ms: Target duration in milliseconds.

        Returns:
            Tuple of (audio_bytes, final_prompt_used).

        Raises:
            RuntimeError: If generation fails after all retries.
        """
        print("  Generating audio via ElevenLabs SDK...")
        print(f"  Duration: {duration_ms}ms ({duration_ms/1000:.0f}s)")

        current_prompt = prompt
        last_error: Exception | None = None

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                # Wait for cooldown between requests
                self._wait_for_cooldown()

                # Record request time
                self._last_request_time = time.time()

                # SDK returns an iterator, collect all chunks into bytes
                audio_iter = self._client.music.compose(
                    prompt=current_prompt,
                    music_length_ms=duration_ms,
                )
                audio_bytes = b"".join(audio_iter)

                # Success - update timestamp and return
                self._last_request_time = time.time()
                return audio_bytes, current_prompt

            except Exception as e:
                last_error = e
                error_str = str(e)

                # Check for bad_prompt error with suggestion (don't count as retry)
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
                            current_prompt = suggested
                            # Don't count bad_prompt as an attempt, retry immediately
                            continue

                # Check if this is a transient error worth retrying
                if self._is_transient_error(e) and attempt < self.MAX_RETRIES:
                    # Calculate delay with exponential backoff + jitter
                    delay = min(
                        self.BASE_DELAY * (2 ** attempt) + random.uniform(0, 5),
                        self.MAX_DELAY
                    )
                    logger.warning(
                        f"Transient error on attempt {attempt + 1}/{self.MAX_RETRIES + 1}: {error_str}"
                    )
                    print(f"  ⚠️  Network error: {error_str[:60]}...")
                    print(f"  Retrying in {delay:.0f}s (attempt {attempt + 1}/{self.MAX_RETRIES + 1})...")
                    
                    time.sleep(delay)
                    
                    # Recreate client for fresh connection
                    logger.info("Recreating ElevenLabs client for fresh connection")
                    self._recreate_client()
                    continue

                # Non-retryable error or out of retries
                break

        # All retries exhausted
        error_msg = str(last_error) if last_error else "Unknown error"
        logger.error(f"ElevenLabs generation failed after {self.MAX_RETRIES + 1} attempts: {error_msg}")
        raise RuntimeError(f"ElevenLabs generation failed: {error_msg}") from last_error

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
