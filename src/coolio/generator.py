"""Music generation orchestrator using provider abstraction.

This module orchestrates the execution of SessionPlans, handling both
library track reuse and new generation through the provider system.
"""

import json
import logging
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, TypeVar

from coolio.config import get_settings
from coolio.library.metadata import TrackMetadata
from coolio.library.storage import R2Storage
from coolio.models import SessionPlan, TrackSlot
from coolio.providers.base import GeneratedTrack, MusicProvider
from coolio.providers.elevenlabs import ElevenLabsProvider
from coolio.providers.stable_audio import StableAudioProvider

logger = logging.getLogger(__name__)

T = TypeVar("T")


class SessionAbortError(Exception):
    """Raised when a session must abort due to a track failure.

    Carries context about what failed and what was already completed,
    allowing callers to understand the state of the session.
    """

    def __init__(
        self,
        message: str,
        failed_slot: int,
        total_slots: int,
        completed_tracks: int = 0,
        cost_spent: float = 0.0,
    ) -> None:
        super().__init__(message)
        self.failed_slot = failed_slot
        self.total_slots = total_slots
        self.completed_tracks = completed_tracks
        self.cost_spent = cost_spent

    def __str__(self) -> str:
        return (
            f"{self.args[0]} "
            f"(slot {self.failed_slot}/{self.total_slots}, "
            f"{self.completed_tracks} completed, ${self.cost_spent:.2f} spent)"
        )

# ElevenLabs Music API hard limit: 10000ms to 300000ms (10s to 5min)
# https://elevenlabs.io/docs/api-reference/music-generation
ELEVENLABS_MAX_DURATION_MS = 300_000
TEST_TRACK_DURATION_MS = 150_000


class GenerationSession:
    """Result of executing a session plan."""

    def __init__(
        self,
        session_id: str,
        concept: str,
        session_dir: Path,
        tracks: list[GeneratedTrack],
        model_used: str,
        created_at: datetime,
        estimated_cost: float,
        reused_count: int = 0,
        generated_count: int = 0,
    ) -> None:
        self.session_id = session_id
        self.concept = concept
        self.session_dir = session_dir
        self.tracks = tracks
        self.model_used = model_used
        self.created_at = created_at
        self.estimated_cost = estimated_cost
        self.reused_count = reused_count
        self.generated_count = generated_count


class MusicGenerator:
    """Orchestrate music generation and library reuse.

    This is the single entry point for executing SessionPlans. It handles:
    - Downloading and reusing library tracks
    - Generating new tracks via providers
    - Uploading new tracks and sessions to R2
    - Auto-cleanup of local temp files after R2 upload
    - Tracking costs and session metadata
    """

    def __init__(
        self,
        upload_to_r2: bool = True,
        auto_cleanup: bool = True,
        provider_override: str | None = None,
    ) -> None:
        s = get_settings()
        self.output_dir = s.output_dir
        self._upload_to_r2 = upload_to_r2
        self._auto_cleanup = auto_cleanup
        self._provider_override = provider_override
        self._r2: R2Storage | None = None

        # Initialize provider registry
        self._providers: dict[str, MusicProvider] = {
            "elevenlabs": ElevenLabsProvider(),
            "stable_audio": StableAudioProvider(),
        }

    def _get_r2(self) -> R2Storage:
        """Lazy-load R2 storage client."""
        if self._r2 is None:
            self._r2 = R2Storage()
        return self._r2

    def _with_retry(
        self,
        fn: Callable[[], T],
        max_retries: int = 3,
        base_delay: float = 2.0,
        operation: str = "operation",
    ) -> T:
        """Execute a function with exponential backoff retry.

        Args:
            fn: Function to execute.
            max_retries: Maximum number of attempts.
            base_delay: Base delay in seconds (doubles each retry).
            operation: Description for logging.

        Returns:
            Result of the function.

        Raises:
            Exception: The last exception if all retries fail.
        """
        last_exception: Exception | None = None

        for attempt in range(max_retries):
            try:
                return fn()
            except Exception as e:
                last_exception = e
                if attempt == max_retries - 1:
                    logger.error(f"{operation} failed after {max_retries} attempts: {e}")
                    raise

                wait_time = base_delay * (2 ** attempt)
                logger.warning(
                    f"{operation} attempt {attempt + 1}/{max_retries} failed: {e}. "
                    f"Retrying in {wait_time:.1f}s..."
                )
                print(f"  Retry {attempt + 1}/{max_retries} in {wait_time:.0f}s...")
                time.sleep(wait_time)

        # Should never reach here, but satisfy type checker
        raise last_exception or RuntimeError("Unexpected retry failure")

    def _ensure_session_dir(self, session_id: str) -> Path:
        """Create and return the session output directory."""
        session_dir = self.output_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def get_provider(self, name: str) -> MusicProvider:
        """Get a provider by name."""
        if name not in self._providers:
            available = ", ".join(self._providers.keys())
            raise ValueError(f"Unknown provider '{name}'. Available: {available}")
        return self._providers[name]

    def generate_test_track(self, concept: str) -> GeneratedTrack:
        """Generate a single local-only test track.

        This generates a *planner-style* prompt (via OpenRouter) and then uses
        the selected provider to render a single track locally. It writes a
        flat mp3/json pair into `output/test/` (relative to the configured
        output directory) and never uploads to R2.

        Args:
            concept: Free-form concept describing genre/vibe/purpose.

        Returns:
            GeneratedTrack for the generated file.
        """
        provider_name = self._provider_override or "elevenlabs"
        provider = self.get_provider(provider_name)

        # Default output_dir is output/audio -> test output becomes output/test
        test_dir = self.output_dir.parent / "test"
        test_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = f"test_track_{ts}"
        title = f"Test Track {ts}"

        # Use the session planner to generate a realistic, production-quality prompt.
        # We do not include any library candidates for test tracks.
        from coolio.djcoolio import generate_session_plan

        target_minutes = max(2, round(TEST_TRACK_DURATION_MS / 60000))
        plan = generate_session_plan(
            concept=concept,
            candidates=[],
            target_duration_minutes=target_minutes,
            model=None,
            provider=provider_name,
        )

        generation_slots = [s for s in plan.slots if s.source == "generate" and s.prompt]
        if not generation_slots:
            raise ValueError("Planner returned no generation slots for test track prompt")

        # Pick the slot closest to our test duration (planner may propose 2–5 min slots).
        best_slot = min(
            generation_slots,
            key=lambda s: abs(int(s.duration_ms) - TEST_TRACK_DURATION_MS),
        )

        prompt = best_slot.prompt or concept
        if best_slot.title:
            title = best_slot.title

        return provider.generate(
            prompt=prompt,
            duration_ms=TEST_TRACK_DURATION_MS,
            output_dir=test_dir,
            filename_base=filename_base,
            order=1,
            title=title,
        )

    def _generate_track(
        self,
        slot: TrackSlot,
        session_dir: Path,
    ) -> GeneratedTrack:
        """Generate a single track using the provider specified in the slot.

        Uses automatic retry with exponential backoff for transient failures.
        If a provider_override is set on the generator, it takes precedence.

        Args:
            slot: The track slot with generation parameters.
            session_dir: Directory to save output.

        Returns:
            GeneratedTrack with file paths and metadata.
        """
        # Use provider override if set, otherwise fall back to slot's provider
        provider_name = self._provider_override or slot.provider or "elevenlabs"

        # Update slot to reflect the actual provider being used
        slot.provider = provider_name

        if (
            provider_name == "elevenlabs"
            and slot.duration_ms > ELEVENLABS_MAX_DURATION_MS
        ):
            print(
                f"  ElevenLabs max is {ELEVENLABS_MAX_DURATION_MS/1000:.0f}s; "
                "using Stable Audio instead."
            )
            provider_name = "stable_audio"
            slot.provider = "stable_audio"

        provider = self.get_provider(provider_name)
        filename_base = f"track_{slot.order:02d}"

        # ElevenLabs: no retry (burns credits on each attempt)
        # Stable Audio: retry OK (flat rate per track)
        if provider_name == "elevenlabs":
            return provider.generate(
                prompt=slot.prompt or "Music track",
                duration_ms=slot.duration_ms,
                output_dir=session_dir,
                filename_base=filename_base,
                order=slot.order,
                title=slot.title or f"Track {slot.order}",
            )
        else:
            # Stable Audio can retry safely
            def do_generate() -> GeneratedTrack:
                return provider.generate(
                    prompt=slot.prompt or "Music track",
                    duration_ms=slot.duration_ms,
                    output_dir=session_dir,
                    filename_base=filename_base,
                    order=slot.order,
                    title=slot.title or f"Track {slot.order}",
                )

            return self._with_retry(
                do_generate,
                max_retries=3,
                base_delay=2.0,
                operation=f"Generate track {slot.order} via {provider_name}",
            )

    def _upload_track_to_r2(
        self,
        track: GeneratedTrack,
        slot: TrackSlot,
        session_id: str,
        genre: str,
    ) -> TrackMetadata | None:
        """Upload a generated track to R2 library.

        Args:
            track: The generated track with local file paths.
            slot: The track slot with generation parameters.
            session_id: Session ID for provenance.
            genre: Genre for library organization.

        Returns:
            TrackMetadata if upload succeeded, None otherwise.
        """
        if not self._upload_to_r2:
            return None

        try:
            r2 = self._get_r2()

            # Create metadata
            metadata = TrackMetadata.create(
                title=track.title,
                genre=genre,
                duration_ms=track.duration_ms,
                provider=track.provider,
                prompt=slot.prompt or "",
                session_id=session_id,
                bpm=track.bpm,
            )

            # Upload audio and metadata
            audio_key = metadata.r2_audio_key()
            metadata_key = metadata.r2_metadata_key()

            r2.upload_file(track.audio_path, audio_key)
            metadata.audio_key = audio_key
            metadata.metadata_key = metadata_key
            r2.upload_json(metadata.to_dict(), metadata_key)

            print(f"  Uploaded to R2: {audio_key}")
            return metadata

        except Exception as e:
            logger.warning(f"Failed to upload track to R2: {e}")
            print(f"  Warning: R2 upload failed: {e}")
            return None

    def _process_library_slot(
        self,
        slot: TrackSlot,
        session_dir: Path,
        fallback_genre: str,
    ) -> GeneratedTrack:
        """Download a library track and update its usage metadata.

        Args:
            slot: Track slot with source="library" and track_id set.
            session_dir: Local directory to save the downloaded track.
            fallback_genre: Genre folder to use if slot.track_genre is not set.

        Returns:
            GeneratedTrack wrapping the downloaded file.

        Raises:
            ValueError: If track_id is missing or track not found in R2.
        """
        if not slot.track_id:
            raise ValueError(
                f"Slot {slot.order} marked for reuse but missing track_id"
            )

        # Use the track's stored genre if provided, otherwise fall back to session genre
        genre = slot.track_genre or fallback_genre

        r2 = self._get_r2()
        track_key = f"library/tracks/{genre}/{slot.track_id}.mp3"
        metadata_key = f"library/tracks/{genre}/{slot.track_id}.json"

        # Avoid relying on non-existent/optional slot attributes (keep filenames stable).
        filename_base = f"track_{slot.order:02d}_reused"
        local_audio_path = session_dir / f"{filename_base}.mp3"
        local_metadata_path = session_dir / f"{filename_base}.json"

        # 1. Check track exists
        if not r2.exists(track_key):
            raise ValueError(
                f"Library track not found in R2: {track_key} "
                f"(track_id={slot.track_id}, genre={genre})"
            )

        # 2. Download audio
        r2.download_file(track_key, local_audio_path)

        # 3. Read and update usage metadata in R2
        data = r2.read_json(metadata_key)
        meta = TrackMetadata.from_dict(data)
        prev_last_used_at = meta.last_used_at
        prev_usage_count = meta.usage_count
        meta.mark_used()
        r2.upload_json(meta.to_dict(), metadata_key)
        logger.info(
            "Updated usage stats for track %s (last_used_at: %s -> %s, usage_count: %s -> %s)",
            slot.track_id,
            prev_last_used_at.isoformat() if prev_last_used_at else "never",
            meta.last_used_at.isoformat() if meta.last_used_at else "unknown",
            prev_usage_count,
            meta.usage_count,
        )

        # 4. Save a local copy of metadata for session records
        with open(local_metadata_path, "w") as f:
            json.dump(meta.to_dict(), f, indent=2)

        # 5. Return GeneratedTrack wrapper
        return GeneratedTrack(
            order=slot.order,
            title=meta.title,
            prompt=meta.prompt_hash,  # Original prompt not stored, use hash
            duration_ms=meta.duration_ms,
            audio_path=local_audio_path,
            metadata_path=local_metadata_path,
            provider=meta.provider,
            bpm=meta.bpm,
        )

    def execute_plan(
        self,
        plan: SessionPlan,
    ) -> GenerationSession:
        """Execute a session plan (the unified entry point).

        This method handles both library reuse and new generation based on
        each slot's source field.

        Args:
            plan: Complete session plan from planner.

        Returns:
            GenerationSession with all processed tracks.
        """
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        session_dir = self._ensure_session_dir(session_id)

        print(f"\nExecuting Session Plan: {len(plan.slots)} tracks")
        print(f"  Concept: {plan.concept}")
        print(f"  Genre: {plan.genre}")
        print(f"  Provider: {self._provider_override or 'per-slot'}")
        print(f"  Library reuse: {len(plan.library_tracks)} tracks")
        print(f"  New generation: {len(plan.generation_tracks)} tracks")
        print(f"  Estimated cost: ${plan.estimated_cost:.2f}")
        print(f"  Output: {session_dir}\n")

        final_tracks: list[GeneratedTrack] = []
        uploaded_metadata: list[TrackMetadata] = []
        reused_count = 0
        generated_count = 0
        actual_cost = 0.0

        for slot in plan.slots:
            print(f"Track {slot.order}/{len(plan.slots)}: ", end="")

            try:
                if slot.source == "library":
                    # Reuse from library
                    print(f"REUSING '{slot.title}' ({slot.track_id})")
                    track = self._process_library_slot(slot, session_dir, plan.genre)
                    final_tracks.append(track)
                    reused_count += 1

                elif slot.source == "generate":
                    # Generate new track
                    provider = self._provider_override or slot.provider or "elevenlabs"
                    print(f"GENERATING '{slot.title}' via {provider}...")
                    track = self._generate_track(slot, session_dir)
                    final_tracks.append(track)
                    generated_count += 1

                    # Track cost
                    actual_cost += slot.estimated_cost()

                    # Upload to library
                    meta = self._upload_track_to_r2(track, slot, session_id, plan.genre)
                    if meta:
                        uploaded_metadata.append(meta)

                else:
                    raise ValueError(f"Unknown source: {slot.source}")

            except Exception as e:
                # Hard fail: abort the entire session
                print(f"\n  FATAL: {e}")
                logger.exception("Session aborted due to track failure")
                raise SessionAbortError(
                    message=str(e),
                    failed_slot=slot.order,
                    total_slots=len(plan.slots),
                    completed_tracks=len(final_tracks),
                    cost_spent=actual_cost,
                )

        # Build session metadata with track references (not copies)
        track_references = []
        for meta in uploaded_metadata:
            track_references.append({
                "track_id": meta.track_id,
                "title": meta.title,
                "genre": meta.genre,
                "duration_ms": meta.duration_ms,
                "provider": meta.provider,
            })

        session_metadata = {
            "session_id": session_id,
            "concept": plan.concept,
            "genre": plan.genre,
            "model_used": plan.model_used,
            "target_duration_minutes": plan.target_duration_minutes,
            "total_slots": len(plan.slots),
            "final_track_count": len(final_tracks),
            "reused_count": reused_count,
            "generated_count": generated_count,
            "uploaded_to_r2": len(uploaded_metadata),
            "estimated_cost": plan.estimated_cost,
            "actual_cost": round(actual_cost, 2),
            "created_at": datetime.now().isoformat(),
            "slots": [asdict(s) for s in plan.slots],
            "track_references": track_references,
        }

        # Save session metadata locally first
        session_metadata_path = session_dir / "session.json"
        with open(session_metadata_path, "w") as f:
            json.dump(session_metadata, f, indent=2)

        # Upload session to R2
        session_uploaded = False
        if self._upload_to_r2:
            try:
                r2 = self._get_r2()
                r2.upload_session_metadata(session_metadata, session_id)
                session_uploaded = True
                print(f"  Session uploaded to R2: sessions/{session_id}/")
            except Exception as e:
                logger.warning(f"Failed to upload session to R2: {e}")
                print(f"  Warning: Session R2 upload failed: {e}")

        print(f"\nSession complete!")
        print(f"  Reused: {reused_count}, Generated: {generated_count}")
        print(f"  Uploaded to R2: {len(uploaded_metadata)} new tracks")
        print(f"  Actual cost: ${actual_cost:.2f}")

        # Auto-cleanup local files if R2 upload succeeded
        if self._auto_cleanup and session_uploaded and self._upload_to_r2:
            if R2Storage.delete_local_session(session_dir):
                print(f"  Local temp files cleaned up")
            else:
                print(f"  Session metadata: {session_metadata_path}")
        else:
            print(f"  Session metadata: {session_metadata_path}")

        return GenerationSession(
            session_id=session_id,
            concept=plan.concept,
            session_dir=session_dir,
            tracks=final_tracks,
            model_used=plan.model_used,
            created_at=datetime.now(),
            estimated_cost=actual_cost,
            reused_count=reused_count,
            generated_count=generated_count,
        )

    def repair_session(
        self,
        session_id: str,
        slot_numbers: list[int],
        local_dir: Path | None = None,
    ) -> dict:
        """Repair a session by regenerating specific failed slots.

        Downloads session metadata from R2, regenerates the specified slots,
        uploads the new tracks, and updates the session metadata.

        Args:
            session_id: Session ID to repair (e.g., "session_20231125_123456").
            slot_numbers: List of slot order numbers to regenerate (1-indexed).
            local_dir: Optional local directory to save tracks. If None,
                       creates a temp directory.

        Returns:
            Dict with repair results including succeeded/failed counts.
        """
        r2 = self._get_r2()

        # 1. Load session metadata from R2
        print(f"\nRepairing session: {session_id}")
        print(f"  Slots to regenerate: {slot_numbers}")

        session_meta = r2.get_session_metadata(session_id)
        if not session_meta:
            raise ValueError(f"Session not found in R2: {session_id}")

        genre = session_meta.get("genre", "electronic")
        concept = session_meta.get("concept", "")
        slots_data = session_meta.get("slots", [])

        if not slots_data:
            raise ValueError(f"Session has no slots data: {session_id}")

        # 2. Find the slots to repair
        slots_to_repair: list[TrackSlot] = []
        for slot_data in slots_data:
            order = slot_data.get("order", 0)
            if order in slot_numbers:
                slot = TrackSlot(
                    order=order,
                    source="generate",  # Force regeneration
                    duration_ms=slot_data.get("duration_ms", 180000),
                    prompt=slot_data.get("prompt"),
                    provider=self._provider_override or slot_data.get("provider", "elevenlabs"),
                    title=slot_data.get("title"),
                )
                slots_to_repair.append(slot)

        if not slots_to_repair:
            raise ValueError(f"None of the specified slots found: {slot_numbers}")

        print(f"  Found {len(slots_to_repair)} slots to repair")

        # 3. Setup local directory
        if local_dir is None:
            local_dir = self.output_dir / f"{session_id}_repair"
        local_dir.mkdir(parents=True, exist_ok=True)

        # 4. Regenerate each slot
        results = {
            "session_id": session_id,
            "slots_requested": slot_numbers,
            "succeeded": [],
            "failed": [],
            "new_tracks": [],
            "cost": 0.0,
        }

        new_track_refs: list[dict] = []

        for slot in slots_to_repair:
            print(f"\nSlot {slot.order}: Regenerating '{slot.title}' via {slot.provider}...")

            try:
                track = self._generate_track(slot, local_dir)
                print(f"  Generated: {track.audio_path.name}")

                # Upload to library
                meta = self._upload_track_to_r2(track, slot, session_id, genre)
                if meta:
                    new_track_refs.append({
                        "track_id": meta.track_id,
                        "title": meta.title,
                        "genre": meta.genre,
                        "duration_ms": meta.duration_ms,
                        "provider": meta.provider,
                    })

                results["succeeded"].append(slot.order)
                results["cost"] += slot.estimated_cost()
                results["new_tracks"].append({
                    "order": slot.order,
                    "title": slot.title,
                    "provider": slot.provider,
                })

            except Exception as e:
                print(f"  FAILED: {e}")
                logger.exception(f"Failed to repair slot {slot.order}")
                results["failed"].append({"order": slot.order, "error": str(e)})

        # 5. Update session metadata in R2
        if results["succeeded"]:
            existing_refs = session_meta.get("track_references", [])
            existing_refs.extend(new_track_refs)
            session_meta["track_references"] = existing_refs
            session_meta["repaired_at"] = datetime.now().isoformat()
            session_meta["repaired_slots"] = results["succeeded"]

            # Update counts
            session_meta["final_track_count"] = session_meta.get("final_track_count", 0) + len(results["succeeded"])
            session_meta["generated_count"] = session_meta.get("generated_count", 0) + len(results["succeeded"])
            session_meta["actual_cost"] = round(
                session_meta.get("actual_cost", 0) + results["cost"], 2
            )

            try:
                r2.upload_session_metadata(session_meta, session_id)
                print(f"\n  Session metadata updated in R2")
            except Exception as e:
                print(f"\n  Warning: Failed to update session metadata: {e}")

        # Summary
        print(f"\nRepair complete!")
        print(f"  Succeeded: {len(results['succeeded'])} slots")
        print(f"  Failed: {len(results['failed'])} slots")
        print(f"  Cost: ${results['cost']:.2f}")

        return results

