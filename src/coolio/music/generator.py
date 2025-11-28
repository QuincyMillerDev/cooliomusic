"""Music generation orchestrator using provider abstraction.

This module orchestrates the execution of SessionPlans, handling both
library track reuse and new generation through the provider system.
"""

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from coolio.core.config import get_settings
from coolio.library.metadata import TrackMetadata
from coolio.library.storage import R2Storage
from coolio.models import SessionPlan, TrackSlot
from coolio.music.providers.base import GeneratedTrack, MusicProvider
from coolio.music.providers.elevenlabs import ElevenLabsProvider
from coolio.music.providers.stable_audio import StableAudioProvider

logger = logging.getLogger(__name__)


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
    - Uploading new tracks to R2
    - Tracking costs and session metadata
    """

    def __init__(self, upload_to_r2: bool = True) -> None:
        s = get_settings()
        self.output_dir = s.output_dir
        self._upload_to_r2 = upload_to_r2
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

    def _generate_track(
        self,
        slot: TrackSlot,
        session_dir: Path,
    ) -> GeneratedTrack:
        """Generate a single track using the provider specified in the slot.

        Args:
            slot: The track slot with generation parameters.
            session_dir: Directory to save output.

        Returns:
            GeneratedTrack with file paths and metadata.
        """
        provider_name = slot.provider or "stable_audio"
        provider = self.get_provider(provider_name)
        filename_base = f"track_{slot.order:02d}_{slot.role}"

        # Route to the appropriate provider
        if provider_name == "elevenlabs":
            from coolio.music.providers.elevenlabs import ElevenLabsProvider
            elevenlabs_provider = provider
            assert isinstance(elevenlabs_provider, ElevenLabsProvider)
            return elevenlabs_provider.generate(
                prompt=slot.prompt or f"{slot.role} track",
                duration_ms=slot.duration_ms,
                output_dir=session_dir,
                filename_base=filename_base,
                order=slot.order,
                title=slot.title or f"Track {slot.order}",
                role=slot.role,
                bpm=slot.bpm_target,
                energy=slot.energy,
                use_composition_plan=True,
            )
        else:
            return provider.generate(
                prompt=slot.prompt or f"{slot.role} track",
                duration_ms=slot.duration_ms,
                output_dir=session_dir,
                filename_base=filename_base,
                order=slot.order,
                title=slot.title or f"Track {slot.order}",
                role=slot.role,
                bpm=slot.bpm_target,
                energy=slot.energy,
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
                bpm=track.bpm,
                duration_ms=track.duration_ms,
                energy=track.energy,
                role=track.role,
                provider=track.provider,
                prompt=slot.prompt or "",
                session_id=session_id,
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
        genre: str,
    ) -> GeneratedTrack | None:
        """Download a library track and update its usage metadata.

        Args:
            slot: Track slot with source="library" and track_id set.
            session_dir: Local directory to save the downloaded track.
            genre: Genre folder in R2.

        Returns:
            GeneratedTrack wrapping the downloaded file, or None on failure.
        """
        if not slot.track_id:
            logger.error(f"Slot {slot.order} marked for reuse but missing track_id")
            return None

        r2 = self._get_r2()
        track_key = f"library/tracks/{genre}/{slot.track_id}.mp3"
        metadata_key = f"library/tracks/{genre}/{slot.track_id}.json"

        filename_base = f"track_{slot.order:02d}_{slot.role}_reused"
        local_audio_path = session_dir / f"{filename_base}.mp3"
        local_metadata_path = session_dir / f"{filename_base}.json"

        try:
            # 1. Check track exists
            if not r2.exists(track_key):
                logger.error(f"Reused track not found in R2: {track_key}")
                return None

            # 2. Download audio
            r2.download_file(track_key, local_audio_path)

            # 3. Read and update usage metadata in R2
            data = r2.read_json(metadata_key)
            meta = TrackMetadata.from_dict(data)
            meta.mark_used()
            r2.upload_json(meta.to_dict(), metadata_key)
            logger.info(f"Updated usage stats for track {slot.track_id}")

            # 4. Save a local copy of metadata for session records
            with open(local_metadata_path, "w") as f:
                json.dump(meta.to_dict(), f, indent=2)

            # 5. Return GeneratedTrack wrapper
            return GeneratedTrack(
                order=slot.order,
                title=meta.title,
                role=slot.role,
                prompt=meta.prompt_hash,  # Original prompt not stored, use hash
                duration_ms=meta.duration_ms,
                audio_path=local_audio_path,
                metadata_path=local_metadata_path,
                provider=meta.provider,
                bpm=meta.bpm,
                energy=meta.energy,
            )

        except Exception as e:
            logger.error(f"Failed to process library track {slot.track_id}: {e}")
            return None

    def execute_plan(
        self,
        plan: SessionPlan,
    ) -> GenerationSession:
        """Execute a session plan (the unified entry point).

        This method handles both library reuse and new generation based on
        each slot's source field. It replaces the old generate_session()
        and execute_curation_plan() methods.

        Args:
            plan: Complete session plan from Curator agent.

        Returns:
            GenerationSession with all processed tracks.
        """
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        session_dir = self._ensure_session_dir(session_id)

        print(f"\nExecuting Session Plan: {len(plan.slots)} tracks")
        print(f"  Concept: {plan.concept}")
        print(f"  Genre: {plan.genre}")
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
            print(f"Track {slot.order}/{len(plan.slots)}: [{slot.role.upper()}] ", end="")

            try:
                if slot.source == "library":
                    # Reuse from library
                    print(f"REUSING '{slot.title}' ({slot.track_id})")
                    track = self._process_library_slot(slot, session_dir, plan.genre)
                    if track:
                        final_tracks.append(track)
                        reused_count += 1
                    else:
                        print("  FAILED to reuse track. Skipping slot.")

                elif slot.source == "generate":
                    # Generate new track
                    provider = slot.provider or "stable_audio"
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
                    print(f"Unknown source: {slot.source}")

            except Exception as e:
                print(f"  ERROR processing slot {slot.order}: {e}")
                logger.exception("Slot processing error")

        # Save session metadata
        session_metadata = {
            "session_id": session_id,
            "concept": plan.concept,
            "genre": plan.genre,
            "model_used": plan.model_used,
            "target_duration_minutes": plan.target_duration_minutes,
            "bpm_range": list(plan.bpm_range),
            "total_slots": len(plan.slots),
            "final_track_count": len(final_tracks),
            "reused_count": reused_count,
            "generated_count": generated_count,
            "uploaded_to_r2": len(uploaded_metadata),
            "estimated_cost": plan.estimated_cost,
            "actual_cost": round(actual_cost, 2),
            "created_at": datetime.now().isoformat(),
            "slots": [asdict(s) for s in plan.slots],
            "library_tracks": [m.track_id for m in uploaded_metadata],
        }

        session_metadata_path = session_dir / "session.json"
        with open(session_metadata_path, "w") as f:
            json.dump(session_metadata, f, indent=2)

        print(f"\nSession complete!")
        print(f"  Reused: {reused_count}, Generated: {generated_count}")
        print(f"  Uploaded to R2: {len(uploaded_metadata)} new tracks")
        print(f"  Actual cost: ${actual_cost:.2f}")
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

    # Backwards compatibility aliases
    def generate_session(self, session_plan: SessionPlan, genre: str = "unknown") -> GenerationSession:
        """Backwards-compatible alias for execute_plan.

        Deprecated: Use execute_plan() instead.
        """
        # Override genre if provided (old API allowed this)
        if genre != "unknown":
            # Create a modified plan with the specified genre
            from dataclasses import replace
            session_plan = replace(session_plan, genre=genre)
        return self.execute_plan(session_plan)

    def execute_curation_plan(self, plan: SessionPlan, genre: str) -> GenerationSession:
        """Backwards-compatible alias for execute_plan.

        Deprecated: Use execute_plan() instead.
        """
        from dataclasses import replace
        plan = replace(plan, genre=genre)
        return self.execute_plan(plan)
