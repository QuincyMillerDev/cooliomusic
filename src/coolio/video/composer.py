"""Video composition for YouTube uploads.

Loops a video clip for the duration of the audio track
to create a final YouTube-ready MP4 video.
"""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def check_ffmpeg() -> bool:
    """Check if FFmpeg is available."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_audio_duration(audio_path: Path) -> float:
    """Get duration of an audio file in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


@dataclass
class CompositionResult:
    """Result of video composition."""

    output_path: Path
    duration_seconds: float
    file_size_mb: float


class VideoComposer:
    """Composes final video from session assets.

    Loops a video clip for the duration of the mixed audio track.
    """

    def __init__(
        self,
        width: int = 1920,
        height: int = 1080,
    ):
        """Initialize the video composer.

        Args:
            width: Video width in pixels.
            height: Video height in pixels.
        """
        if not check_ffmpeg():
            raise RuntimeError("FFmpeg not found. Please install FFmpeg.")

        self.width = width
        self.height = height

    def compose(
        self,
        clip_path: Path,
        audio_path: Path,
        output_path: Path,
    ) -> CompositionResult:
        """Compose final video by looping a video clip for the audio duration.

        Args:
            clip_path: Path to video clip to loop (MP4).
            audio_path: Path to mixed audio file (MP3).
            output_path: Path for output video file.

        Returns:
            CompositionResult with output path and metadata.
        """
        if not clip_path.exists():
            raise FileNotFoundError(f"Video clip not found: {clip_path}")
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio not found: {audio_path}")

        # Get audio duration
        duration = get_audio_duration(audio_path)
        logger.info(f"Composing video: {duration:.1f}s duration")
        logger.info(f"  Clip: {clip_path}")
        logger.info(f"  Audio: {audio_path}")

        # FFmpeg filter: scale/pad video to target dimensions with high-quality lanczos
        filter_complex = (
            f"[0:v]scale={self.width}:{self.height}:"
            f"force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:black[out]"
        )

        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-stream_loop", "-1",  # Loop input video indefinitely
            "-i", str(clip_path),  # Input 0: video clip
            "-i", str(audio_path),  # Input 1: audio
            "-filter_complex", filter_complex,
            "-map", "[out]",  # Video from filter
            "-map", "1:a",  # Audio from input 1
            "-c:v", "libx264",
            "-preset", "slow",  # Higher quality encoding
            "-crf", "15",  # Very high quality (lower = better, 15 is excellent)
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "320k",  # Higher audio bitrate
            "-movflags", "+faststart",  # Web optimization
            "-t", str(duration),  # Trim to exact audio duration
            str(output_path),
        ]

        logger.info("  Running FFmpeg composition (high quality)...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            raise RuntimeError(
                f"Video composition failed: {result.stderr[-1000:]}"
            )

        # Get output file size
        file_size_mb = output_path.stat().st_size / (1024 * 1024)

        logger.info(f"  Video saved: {output_path}")
        logger.info(f"  Size: {file_size_mb:.1f} MB")

        return CompositionResult(
            output_path=output_path,
            duration_seconds=duration,
            file_size_mb=file_size_mb,
        )

    def compose_session(
        self,
        session_dir: Path,
        output_filename: str = "final_video.mp4",
    ) -> CompositionResult:
        """Compose video from a session directory.

        Looks for:
        - {session_id}_clip.mp4 in session_dir
        - final_mix.mp3 in session_dir

        Args:
            session_dir: Path to session directory.
            output_filename: Name for output video file.

        Returns:
            CompositionResult with output path and metadata.
        """
        # Find video clip
        clip_path = self._find_clip(session_dir)
        if not clip_path:
            raise FileNotFoundError(
                f"No video clip found in {session_dir}. "
                f"Expected: {session_dir.name}_clip.mp4"
            )

        # Find audio
        audio_path = session_dir / "final_mix.mp3"
        if not audio_path.exists():
            raise FileNotFoundError(
                f"No final_mix.mp3 found in {session_dir}. "
                "Run `coolio mix` first."
            )

        output_path = session_dir / output_filename

        # Compose the video
        result = self.compose(clip_path, audio_path, output_path)

        # Check thumbnail size for YouTube upload (must be < 2MB)
        # This is separate from video composition but ensures upload compliance.
        thumbnail_path = self._find_thumbnail(session_dir)
        if thumbnail_path:
            self._ensure_thumbnail_upload_ready(thumbnail_path)

        return result

    def _find_clip(self, session_dir: Path) -> Optional[Path]:
        """Find video clip in session directory.

        Looks for {session_id}_clip.mp4 pattern.

        Args:
            session_dir: Path to session directory.

        Returns:
            Path to video clip, or None if not found.
        """
        session_id = session_dir.name
        clip_path = session_dir / f"{session_id}_clip.mp4"
        if clip_path.exists():
            return clip_path
        return None

    def _ensure_thumbnail_upload_ready(self, thumbnail_path: Path) -> None:
        """Ensure a version of the thumbnail exists that is < 2MB for YouTube upload."""
        if not thumbnail_path.exists():
            return

        size_mb = thumbnail_path.stat().st_size / (1024 * 1024)
        if size_mb <= 2.0:
            logger.info(f"Thumbnail size OK for upload: {size_mb:.1f} MB")
            return

        logger.info(f"Thumbnail > 2MB ({size_mb:.1f} MB), creating optimized version for upload...")

        # Create a compressed version
        optimized_path = thumbnail_path.parent / f"{thumbnail_path.stem}_upload_ready.jpg"

        try:
            # Use FFmpeg to compress (convert to JPG quality 15)
            # -q:v 15 usually results in <500KB for 1080p images
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(thumbnail_path),
                    "-q:v", "15", str(optimized_path)
                ],
                capture_output=True,
                check=True
            )
            logger.info(f"Created optimized thumbnail: {optimized_path.name}")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to compress thumbnail: {e}")

    def _find_thumbnail(self, session_dir: Path) -> Optional[Path]:
        """Find thumbnail image in session directory.

        Looks for common thumbnail patterns.

        Args:
            session_dir: Path to session directory.

        Returns:
            Path to thumbnail, or None if not found.
        """
        # Check common patterns
        patterns = [
            "thumbnail.png",
            "thumbnail.jpg",
            "*_thumbnail.png",
            "*_thumbnail.jpg",
        ]

        for pattern in patterns:
            matches = list(session_dir.glob(pattern))
            if matches:
                return matches[0]

        return None
