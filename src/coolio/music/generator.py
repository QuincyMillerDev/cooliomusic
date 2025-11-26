"""Music generation using ElevenLabs API."""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable, cast

from elevenlabs.client import ElevenLabs

from coolio.core.config import get_settings
from coolio.music.agent import TrackPlan, SessionPlan


JsonDict = dict[str, Any]


@runtime_checkable
class DetailedComposition(Protocol):
    """Subset of attributes returned by ElevenLabs compose_detailed."""

    json: JsonDict | None
    audio: bytes


@dataclass
class GeneratedTrack:
    """Result of generating a single track."""

    order: int
    role: str
    prompt: str
    duration_ms: int
    audio_path: Path
    metadata_path: Path
    composition_plan: dict | None
    song_metadata: dict | None


@dataclass
class GenerationSession:
    """Complete generation session with all tracks."""

    session_id: str
    concept: str
    session_dir: Path
    tracks: list[GeneratedTrack]
    model_used: str
    created_at: datetime


class MusicGenerator:
    """Generate music tracks using ElevenLabs API."""

    def __init__(self):
        s = get_settings()
        self.client = ElevenLabs(api_key=s.elevenlabs_api_key)
        self.output_dir = s.output_dir

    def _ensure_session_dir(self, session_id: str) -> Path:
        """Create and return the session output directory."""
        session_dir = self.output_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def create_composition_plan(self, prompt: str, duration_ms: int):
        """
        Generate a composition plan from a prompt.

        This doesn't use tokens - it's just planning.
        Returns the raw MusicPrompt object from ElevenLabs.
        """
        return self.client.music.composition_plan.create(
            prompt=prompt,
            music_length_ms=duration_ms,
        )

    def generate_track(
        self,
        track_plan: TrackPlan,
        session_dir: Path,
        use_composition_plan: bool = True,
    ) -> GeneratedTrack:
        """
        Generate a single track from a track plan.

        Args:
            track_plan: The plan for this track
            session_dir: Directory to save output
            use_composition_plan: If True, generate composition plan first

        Returns:
            GeneratedTrack with file paths and metadata
        """
        # Clamp duration to ElevenLabs limits
        s = get_settings()
        duration_ms = max(
            s.min_track_duration_ms,
            min(track_plan.duration_ms, s.max_track_duration_ms),
        )

        composition_plan_dict: dict | None = None
        song_metadata: dict | None = None

        # Generate music (with or without prior composition plan)
        if use_composition_plan:
            # Generate composition plan first (no token cost)
            print(f"  Creating composition plan...")
            plan_obj = self.create_composition_plan(track_plan.prompt, duration_ms)

            # Generate audio from composition plan
            print(f"  Generating audio from plan...")
            track_details_raw = self.client.music.compose_detailed(
                composition_plan=plan_obj,
            )
        else:
            # Generate directly from prompt
            print(f"  Generating audio from prompt...")
            track_details_raw = self.client.music.compose_detailed(
                prompt=track_plan.prompt,
                music_length_ms=duration_ms,
            )

        # Typing: the SDK returns an object with .json and .audio attributes.
        track_details = cast(DetailedComposition, track_details_raw)

        # Extract metadata from response for storage
        if track_details.json:
            if "composition_plan" in track_details.json:
                composition_plan_dict = track_details.json["composition_plan"]
            if "song_metadata" in track_details.json:
                song_metadata = track_details.json["song_metadata"]

        # Save audio file
        filename_base = f"track_{track_plan.order:02d}_{track_plan.role}"
        audio_path = session_dir / f"{filename_base}.mp3"
        metadata_path = session_dir / f"{filename_base}.json"

        # Write audio bytes
        with open(audio_path, "wb") as f:
            f.write(track_details.audio)

        # Write metadata
        metadata = {
            "order": track_plan.order,
            "role": track_plan.role,
            "prompt": track_plan.prompt,
            "duration_ms": duration_ms,
            "notes": track_plan.notes,
            "composition_plan": composition_plan_dict,
            "song_metadata": song_metadata,
        }
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        print(f"  Saved: {audio_path.name}")

        return GeneratedTrack(
            order=track_plan.order,
            role=track_plan.role,
            prompt=track_plan.prompt,
            duration_ms=duration_ms,
            audio_path=audio_path,
            metadata_path=metadata_path,
            composition_plan=composition_plan_dict,
            song_metadata=song_metadata,
        )

    def generate_session(
        self,
        session_plan: SessionPlan,
        use_composition_plan: bool = True,
    ) -> GenerationSession:
        """
        Generate all tracks for a session.

        Args:
            session_plan: Complete session plan from AI agent
            use_composition_plan: Whether to use composition plans

        Returns:
            GenerationSession with all generated tracks
        """
        # Create session directory with timestamp
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        session_dir = self._ensure_session_dir(session_id)

        print(f"\nGenerating {session_plan.total_tracks} tracks...")
        print(f"Output directory: {session_dir}\n")

        generated_tracks = []

        for i, track_plan in enumerate(session_plan.tracks, 1):
            print(f"Track {i}/{session_plan.total_tracks}: {track_plan.role}")

            try:
                track = self.generate_track(
                    track_plan,
                    session_dir,
                    use_composition_plan=use_composition_plan,
                )
                generated_tracks.append(track)
            except Exception as e:
                print(f"  ERROR: {e}")
                continue

            print()

        # Save session metadata
        session_metadata = {
            "session_id": session_id,
            "concept": session_plan.concept,
            "model_used": session_plan.model_used,
            "total_tracks": session_plan.total_tracks,
            "generated_tracks": len(generated_tracks),
            "created_at": datetime.now().isoformat(),
            "track_plans": [asdict(t) for t in session_plan.tracks],
        }

        session_metadata_path = session_dir / "session.json"
        with open(session_metadata_path, "w") as f:
            json.dump(session_metadata, f, indent=2)

        print(f"Session complete: {len(generated_tracks)}/{session_plan.total_tracks} tracks generated")
        print(f"Session metadata: {session_metadata_path}")

        return GenerationSession(
            session_id=session_id,
            concept=session_plan.concept,
            session_dir=session_dir,
            tracks=generated_tracks,
            model_used=session_plan.model_used,
            created_at=datetime.now(),
        )

