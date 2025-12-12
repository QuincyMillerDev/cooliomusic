"""Audio mixing module for combining session tracks into seamless mixes.

This module implements Phase 3 of the Coolio pipeline: taking individual
generated tracks and composing them into a continuous DJ-style mix with
crossfade transitions and level normalization.

Supports R2-first workflow:
- Download tracks from R2 library if not available locally
- Upload final mix to R2 after completion
- Auto-cleanup of local temp files
"""

import json
import logging
import re
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from pydub import AudioSegment
from pydub.silence import detect_leading_silence

from coolio.library.storage import R2Storage

logger = logging.getLogger(__name__)


@dataclass
class TrackInfo:
    """Metadata about a track in the mix."""

    order: int
    title: str
    role: str
    duration_ms: int
    audio_path: Path
    start_time_ms: int = 0  # Position in final mix


@dataclass
class MixResult:
    """Result of mixing a session."""

    output_path: Path
    tracklist_path: Path
    total_duration_ms: int
    track_count: int
    tracks: list[TrackInfo]
    r2_mix_key: str | None = None
    r2_tracklist_key: str | None = None


class MixComposer:
    """Compose individual tracks into a seamless mix.

    Handles:
    - Loading tracks from a session directory or R2 library
    - Applying crossfade transitions between tracks
    - Normalizing audio levels
    - Exporting the final mix as MP3
    - Uploading final mix to R2
    - Generating a tracklist with timestamps
    """

    DEFAULT_CROSSFADE_MS = 5000  # 5 seconds
    DEFAULT_TARGET_DBFS = -1.0  # Peak normalize to -1dB
    DEFAULT_BITRATE = "320k"
    # Many AI tracks have long fade-ins; this trims the first track so the mix
    # becomes audible quickly.
    DEFAULT_TRIM_LEADING_SILENCE_FIRST_TRACK = True
    DEFAULT_LEADING_SILENCE_THRESHOLD_DBFS = -33.0
    DEFAULT_LEADING_SILENCE_MAX_TRIM_MS = 30_000

    def __init__(
        self,
        crossfade_ms: int = DEFAULT_CROSSFADE_MS,
        normalize: bool = True,
        target_dbfs: float = DEFAULT_TARGET_DBFS,
        upload_to_r2: bool = True,
        auto_cleanup: bool = False,
        trim_leading_silence_first_track: bool = DEFAULT_TRIM_LEADING_SILENCE_FIRST_TRACK,
        leading_silence_threshold_dbfs: float = DEFAULT_LEADING_SILENCE_THRESHOLD_DBFS,
        leading_silence_max_trim_ms: int = DEFAULT_LEADING_SILENCE_MAX_TRIM_MS,
    ) -> None:
        """Initialize the mixer.

        Args:
            crossfade_ms: Duration of crossfade transitions in milliseconds.
            normalize: Whether to normalize audio levels.
            target_dbfs: Target peak level in dBFS (only if normalize=True).
            upload_to_r2: Whether to upload final mix to R2.
            auto_cleanup: Whether to delete local files after R2 upload.
            trim_leading_silence_first_track: Trim initial near-silence from the first
                track so the final mix starts audibly.
            leading_silence_threshold_dbfs: Anything below this is treated as silence
                for trimming purposes. Higher (e.g., -33) is more aggressive.
            leading_silence_max_trim_ms: Maximum amount of leading audio to remove.
        """
        self.crossfade_ms = crossfade_ms
        self.normalize = normalize
        self.target_dbfs = target_dbfs
        self.upload_to_r2 = upload_to_r2
        self.auto_cleanup = auto_cleanup
        self.trim_leading_silence_first_track = trim_leading_silence_first_track
        self.leading_silence_threshold_dbfs = leading_silence_threshold_dbfs
        self.leading_silence_max_trim_ms = leading_silence_max_trim_ms
        self._r2: R2Storage | None = None

    def _get_r2(self) -> R2Storage:
        """Lazy-load R2 storage client."""
        if self._r2 is None:
            self._r2 = R2Storage()
        return self._r2

    def _trim_leading_silence(
        self,
        audio: AudioSegment,
        *,
        silence_threshold_dbfs: float,
        max_trim_ms: int,
        chunk_size_ms: int = 10,
    ) -> tuple[AudioSegment, int]:
        """Trim leading near-silence from an audio segment.

        Returns:
            (trimmed_audio, trimmed_ms)
        """
        if len(audio) <= 0:
            return audio, 0

        max_trim_ms = max(0, min(int(max_trim_ms), len(audio)))
        if max_trim_ms == 0:
            return audio, 0

        # pydub returns the number of ms from start until audio rises above threshold.
        trimmed_ms = int(
            detect_leading_silence(
                audio[:max_trim_ms],
                silence_threshold=silence_threshold_dbfs,
                chunk_size=chunk_size_ms,
            )
        )

        # Clamp and guard against pathological cases.
        trimmed_ms = max(0, min(trimmed_ms, max_trim_ms))
        if trimmed_ms <= 0:
            return audio, 0
        return audio[trimmed_ms:], trimmed_ms

    def load_session_tracks(self, session_dir: Path) -> list[TrackInfo]:
        """Load track information from a session directory.

        Discovers tracks by finding MP3 files matching the pattern
        track_XX.mp3 or track_XX_*.mp3 and loads their metadata from companion JSON files.

        Args:
            session_dir: Path to the session directory.

        Returns:
            List of TrackInfo objects sorted by track order.

        Raises:
            ValueError: If no tracks are found in the session.
        """
        tracks: list[TrackInfo] = []

        # Find all track MP3 files.
        #
        # Historical sessions used filenames like `track_01.mp3`, while some
        # workflows may add a suffix: `track_01_some-title.mp3`.
        track_pattern = re.compile(r"track_(\d+)(?:_.*)?\.mp3$")

        for audio_path in sorted(session_dir.glob("track_*.mp3")):
            match = track_pattern.match(audio_path.name)
            if not match:
                continue

            order = int(match.group(1))

            # Try to load metadata from companion JSON
            metadata_path = audio_path.with_suffix(".json")
            if metadata_path.exists():
                with open(metadata_path) as f:
                    metadata = json.load(f)
                title = metadata.get("title", f"Track {order}")
                role = metadata.get("role", "track")
                duration_ms = metadata.get("duration_ms", 0)
            else:
                # Fall back to reading duration from audio file
                audio = AudioSegment.from_mp3(audio_path)
                title = f"Track {order}"
                role = "track"
                duration_ms = len(audio)

            tracks.append(TrackInfo(
                order=order,
                title=title,
                role=role,
                duration_ms=duration_ms,
                audio_path=audio_path,
            ))

        if not tracks:
            raise ValueError(f"No tracks found in session directory: {session_dir}")

        # Sort by order
        tracks.sort(key=lambda t: t.order)
        logger.info(f"Loaded {len(tracks)} tracks from {session_dir}")

        return tracks

    @staticmethod
    def _describe_track_orders(orders: list[int]) -> str:
        """Return a compact human-readable description of track orders."""
        if not orders:
            return "(none)"

        sorted_orders = sorted(set(orders))
        ranges: list[tuple[int, int]] = []
        start = prev = sorted_orders[0]
        for o in sorted_orders[1:]:
            if o == prev + 1:
                prev = o
                continue
            ranges.append((start, prev))
            start = prev = o
        ranges.append((start, prev))

        parts: list[str] = []
        for a, b in ranges:
            parts.append(str(a) if a == b else f"{a}-{b}")
        return ", ".join(parts)

    @staticmethod
    def _missing_orders(orders: list[int]) -> list[int]:
        if not orders:
            return []
        s = sorted(set(orders))
        missing: list[int] = []
        for o in range(s[0], s[-1] + 1):
            if o not in s:
                missing.append(o)
        return missing

    @staticmethod
    def _only_consecutive_from_one(tracks: list[TrackInfo]) -> list[TrackInfo]:
        """Return only consecutive tracks starting at order=1 until first gap."""
        if not tracks:
            return tracks
        by_order = {t.order: t for t in tracks}
        kept: list[TrackInfo] = []
        expected = 1
        while expected in by_order:
            kept.append(by_order[expected])
            expected += 1
        kept.sort(key=lambda t: t.order)
        return kept

    @staticmethod
    def _build_tracklist_text(tracks: list[TrackInfo]) -> str:
        """Build a tracklist text block from populated TrackInfo start times."""
        lines = ["TRACKLIST", "=" * 40, ""]

        for track in tracks:
            # Convert ms to MM:SS format
            td = timedelta(milliseconds=track.start_time_ms)
            total_seconds = int(td.total_seconds())
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            timestamp = f"{minutes:02d}:{seconds:02d}"

            lines.append(f"{timestamp} - {track.title}")

        lines.append("")
        lines.append("=" * 40)
        lines.append(f"Total tracks: {len(tracks)}")
        return "\n".join(lines)

    def _normalize_audio(self, audio: AudioSegment) -> AudioSegment:
        """Normalize audio to target peak level.

        Args:
            audio: Audio segment to normalize.

        Returns:
            Normalized audio segment.
        """
        change_in_dbfs = self.target_dbfs - audio.max_dBFS
        return audio.apply_gain(change_in_dbfs)

    def mix_tracks(
        self,
        tracks: list[TrackInfo],
        output_path: Path,
    ) -> AudioSegment:
        """Mix multiple tracks with crossfade transitions.

        Args:
            tracks: List of TrackInfo objects in order.
            output_path: Path for the output file (used for progress logging).

        Returns:
            Combined AudioSegment.
        """
        if not tracks:
            raise ValueError("No tracks to mix")

        print(f"Mixing {len(tracks)} tracks with {self.crossfade_ms}ms crossfades...")

        # Load first track
        print(f"  Loading: {tracks[0].title}")
        mixed = AudioSegment.from_mp3(tracks[0].audio_path)
        if self.trim_leading_silence_first_track:
            mixed, trimmed_ms = self._trim_leading_silence(
                mixed,
                silence_threshold_dbfs=self.leading_silence_threshold_dbfs,
                max_trim_ms=self.leading_silence_max_trim_ms,
            )
            if trimmed_ms > 0:
                print(
                    "  Trimmed leading audio from first track: "
                    f"{trimmed_ms}ms (threshold {self.leading_silence_threshold_dbfs} dBFS)"
                )
        tracks[0].start_time_ms = 0

        current_position_ms = len(mixed)

        # Append remaining tracks with crossfade
        for i, track in enumerate(tracks[1:], start=2):
            print(f"  Loading: {track.title}")
            next_audio = AudioSegment.from_mp3(track.audio_path)

            # Calculate start time (accounting for crossfade overlap)
            track.start_time_ms = current_position_ms - self.crossfade_ms

            # Apply crossfade
            mixed = mixed.append(next_audio, crossfade=self.crossfade_ms)

            # Update position (subtract crossfade since it overlaps)
            current_position_ms = len(mixed)

        # Normalize if requested
        if self.normalize:
            print(f"  Normalizing to {self.target_dbfs} dBFS...")
            mixed = self._normalize_audio(mixed)

        return mixed

    def generate_tracklist(
        self,
        tracks: list[TrackInfo],
        output_path: Path,
    ) -> Path:
        """Generate a tracklist file with timestamps.

        Args:
            tracks: List of TrackInfo with start_time_ms populated.
            output_path: Path for the tracklist file.

        Returns:
            Path to the generated tracklist file.
        """
        content = self._build_tracklist_text(tracks)
        output_path.write_text(content)

        return output_path

    def mix_session(
        self,
        session_dir: Path,
        session_id: str | None = None,
        output_filename: str = "final_mix.mp3",
        tracklist_filename: str = "tracklist.txt",
        only_consecutive: bool = False,
    ) -> MixResult:
        """Mix all tracks in a session directory.

        This is the main entry point for mixing a complete session.

        Args:
            session_dir: Path to the session directory containing tracks.
            session_id: Session ID for R2 upload (derived from dir name if None).
            output_filename: Name for the output MP3 file.
            tracklist_filename: Name for the tracklist file.

        Returns:
            MixResult with paths and metadata about the mix.
        """
        session_dir = Path(session_dir)
        output_path = session_dir / output_filename
        tracklist_path = session_dir / tracklist_filename

        # Derive session_id from directory name if not provided
        if session_id is None:
            session_id = session_dir.name

        # Load tracks
        tracks = self.load_session_tracks(session_dir)
        found_orders = [t.order for t in tracks]
        missing = self._missing_orders(found_orders)
        if missing:
            print(
                "Found track files with non-consecutive numbering: "
                f"{self._describe_track_orders(found_orders)} "
                f"(missing: {self._describe_track_orders(missing)})"
            )
            if only_consecutive:
                original_count = len(tracks)
                tracks = self._only_consecutive_from_one(tracks)
                print(
                    f"Mixing only consecutive tracks starting at 1: "
                    f"{len(tracks)}/{original_count} tracks kept "
                    f"({self._describe_track_orders([t.order for t in tracks])})"
                )
            else:
                print(
                    "Note: By default all existing track files are mixed. "
                    "If you deleted mid-session tracks and want to stop at the first gap, "
                    "rerun with only_consecutive=True."
                )

        # Mix them
        mixed_audio = self.mix_tracks(tracks, output_path)

        # Export
        print(f"  Exporting to {output_path.name}...")
        mixed_audio.export(
            output_path,
            format="mp3",
            bitrate=self.DEFAULT_BITRATE,
        )

        # Generate tracklist
        print(f"  Writing tracklist to {tracklist_filename}...")
        self.generate_tracklist(tracks, tracklist_path)
        print()
        print(self._build_tracklist_text(tracks))

        total_duration_ms = len(mixed_audio)
        total_minutes = total_duration_ms / 60000

        print(f"\nMix complete!")
        print(f"  Duration: {total_minutes:.1f} minutes")
        print(f"  Output: {output_path}")
        print(f"  Tracklist: {tracklist_path}")

        # Upload to R2 if enabled
        r2_mix_key = None
        r2_tracklist_key = None
        if self.upload_to_r2:
            try:
                r2 = self._get_r2()
                result = r2.upload_final_mix(output_path, tracklist_path, session_id)
                r2_mix_key = result.get("mix_key")
                r2_tracklist_key = result.get("tracklist_key")
                print(f"  Uploaded to R2: sessions/{session_id}/audio/")

                # Auto-cleanup if enabled
                if self.auto_cleanup:
                    output_path.unlink(missing_ok=True)
                    tracklist_path.unlink(missing_ok=True)
                    print(f"  Local mix files cleaned up")
            except Exception as e:
                logger.warning(f"Failed to upload mix to R2: {e}")
                print(f"  Warning: R2 upload failed: {e}")

        return MixResult(
            output_path=output_path,
            tracklist_path=tracklist_path,
            total_duration_ms=total_duration_ms,
            track_count=len(tracks),
            tracks=tracks,
            r2_mix_key=r2_mix_key,
            r2_tracklist_key=r2_tracklist_key,
        )

    def mix_from_r2(
        self,
        session_id: str,
        track_ids: list[str],
        genre: str,
        output_dir: Path | None = None,
    ) -> MixResult:
        """Mix tracks from R2 library into a final mix.

        Downloads tracks from R2, mixes them, uploads the result.

        Args:
            session_id: Session ID for organizing output.
            track_ids: List of track IDs to mix.
            genre: Genre folder in R2 library.
            output_dir: Local temp directory (uses system temp if None).

        Returns:
            MixResult with R2 keys for the uploaded mix.
        """
        # Use temp directory if not specified
        if output_dir is None:
            temp_dir = Path(tempfile.mkdtemp(prefix=f"coolio_mix_{session_id}_"))
        else:
            temp_dir = output_dir / session_id
            temp_dir.mkdir(parents=True, exist_ok=True)

        r2 = self._get_r2()

        print(f"Downloading {len(track_ids)} tracks from R2...")

        # Download tracks and build TrackInfo list
        tracks: list[TrackInfo] = []
        for i, track_id in enumerate(track_ids, start=1):
            audio_key = f"library/tracks/{genre}/{track_id}.mp3"
            metadata_key = f"library/tracks/{genre}/{track_id}.json"
            local_path = temp_dir / f"{track_id}.mp3"

            try:
                # Download audio
                r2.download_file(audio_key, local_path)

                # Get metadata
                metadata = r2.read_json(metadata_key)

                tracks.append(TrackInfo(
                    order=i,
                    title=metadata.get("title", f"Track {i}"),
                    role=metadata.get("role", "track"),
                    duration_ms=metadata.get("duration_ms", 0),
                    audio_path=local_path,
                ))
                print(f"  Downloaded: {metadata.get('title', track_id)}")
            except Exception as e:
                logger.error(f"Failed to download track {track_id}: {e}")
                print(f"  Failed: {track_id} - {e}")

        if not tracks:
            raise ValueError("No tracks could be downloaded from R2")

        # Mix the tracks
        output_path = temp_dir / "final_mix.mp3"
        tracklist_path = temp_dir / "tracklist.txt"

        mixed_audio = self.mix_tracks(tracks, output_path)

        # Export
        print(f"  Exporting to {output_path.name}...")
        mixed_audio.export(
            output_path,
            format="mp3",
            bitrate=self.DEFAULT_BITRATE,
        )

        # Generate tracklist
        self.generate_tracklist(tracks, tracklist_path)

        total_duration_ms = len(mixed_audio)
        total_minutes = total_duration_ms / 60000

        print(f"\nMix complete!")
        print(f"  Duration: {total_minutes:.1f} minutes")

        # Upload to R2
        r2_mix_key = None
        r2_tracklist_key = None
        if self.upload_to_r2:
            try:
                result = r2.upload_final_mix(output_path, tracklist_path, session_id)
                r2_mix_key = result.get("mix_key")
                r2_tracklist_key = result.get("tracklist_key")
                print(f"  Uploaded to R2: sessions/{session_id}/audio/")
            except Exception as e:
                logger.warning(f"Failed to upload mix to R2: {e}")
                print(f"  Warning: R2 upload failed: {e}")

        # Cleanup temp files if auto_cleanup enabled
        if self.auto_cleanup and output_dir is None:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            print(f"  Temp files cleaned up")

        return MixResult(
            output_path=output_path,
            tracklist_path=tracklist_path,
            total_duration_ms=total_duration_ms,
            track_count=len(tracks),
            tracks=tracks,
            r2_mix_key=r2_mix_key,
            r2_tracklist_key=r2_tracklist_key,
        )

