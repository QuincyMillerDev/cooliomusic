"""Video composition for YouTube uploads.

Combines thumbnail image, waveform visualization, and audio
into a final YouTube-ready MP4 video.
"""

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from coolio.video.waveform import check_ffmpeg, get_audio_duration

logger = logging.getLogger(__name__)


@dataclass
class CompositionResult:
    """Result of video composition."""

    output_path: Path
    duration_seconds: float
    file_size_mb: float


class VideoComposer:
    """Composes final video from session assets.

    Combines:
    - Static thumbnail image as background (1920x1080)
    - Audio-reactive waveform overlay
    - Mixed audio track
    """

    def __init__(
        self,
        width: int = 1920,
        height: int = 1080,
        waveform_height: int = 100,
        waveform_color: str = "white@0.5",
        waveform_position_from_bottom: int = 360,
        fade_in_duration: float = 5.0,
    ):
        """Initialize the video composer.

        Args:
            width: Video width in pixels.
            height: Video height in pixels.
            waveform_height: Height of the waveform bar.
            waveform_color: Waveform color in FFmpeg format.
            waveform_position_from_bottom: Distance from bottom of frame.
            fade_in_duration: Duration of fade-in from black/silence in seconds.
        """
        if not check_ffmpeg():
            raise RuntimeError("FFmpeg not found. Please install FFmpeg.")

        self.width = width
        self.height = height
        self.waveform_height = waveform_height
        self.waveform_color = waveform_color
        self.waveform_y = height - waveform_position_from_bottom - waveform_height
        self.fade_in_duration = fade_in_duration

    def compose(
        self,
        thumbnail_path: Path,
        audio_path: Path,
        output_path: Path,
    ) -> CompositionResult:
        """Compose final video from thumbnail and audio.

        Args:
            thumbnail_path: Path to thumbnail image (PNG/JPG).
            audio_path: Path to mixed audio file (MP3).
            output_path: Path for output video file.

        Returns:
            CompositionResult with output path and metadata.
        """
        if not thumbnail_path.exists():
            raise FileNotFoundError(f"Thumbnail not found: {thumbnail_path}")
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio not found: {audio_path}")

        # Get audio duration
        duration = get_audio_duration(audio_path)
        logger.info(f"Composing video: {duration:.1f}s duration")
        logger.info(f"  Thumbnail: {thumbnail_path}")
        logger.info(f"  Audio: {audio_path}")

        # Build FFmpeg filter graph:
        # 1. Scale thumbnail to exact dimensions
        # 2. Loop thumbnail for duration
        # 3. Generate waveform from audio
        # 4. Overlay waveform on thumbnail
        # 5. Mux with audio

        # Calculate waveform position
        waveform_y = self.waveform_y

        # FFmpeg filter complex:
        # [0:v] = thumbnail image
        # [1:a] = audio for waveform generation
        # [2:a] = audio for final output
        filter_complex = (
            # Scale, loop, and fade in thumbnail from black
            f"[0:v]scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
            f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"loop=loop=-1:size=1:start=0,trim=duration={duration},setpts=PTS-STARTPTS,"
            f"fade=t=in:st=0:d={self.fade_in_duration}[bg];"
            # Generate waveform from audio
            f"[1:a]showwaves=s={self.width}x{self.waveform_height}:"
            f"mode=cline:colors={self.waveform_color}:scale=sqrt:draw=full[wave];"
            # Overlay waveform on background
            f"[bg][wave]overlay=0:{waveform_y}:shortest=1[out]"
        )

        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-loop", "1",  # Loop image
            "-i", str(thumbnail_path),  # Input 0: thumbnail
            "-i", str(audio_path),  # Input 1: audio for waveform
            "-i", str(audio_path),  # Input 2: audio for final output
            "-filter_complex", filter_complex,
            "-map", "[out]",  # Video from filter
            "-map", "2:a",  # Audio from input 2
            "-af", f"afade=t=in:st=0:d={self.fade_in_duration}",  # Audio fade-in
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",  # Web optimization
            "-t", str(duration),  # Explicit duration
            str(output_path),
        ]

        logger.info("  Running FFmpeg composition...")
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
        - thumbnail.png or *_thumbnail.png in session_dir
        - final_mix.mp3 in session_dir

        Args:
            session_dir: Path to session directory.
            output_filename: Name for output video file.

        Returns:
            CompositionResult with output path and metadata.
        """
        # Find thumbnail
        thumbnail_path = self._find_thumbnail(session_dir)
        if not thumbnail_path:
            raise FileNotFoundError(
                f"No thumbnail found in {session_dir}. "
                "Run `coolio generate` with visual generation enabled."
            )

        # Find audio
        audio_path = session_dir / "final_mix.mp3"
        if not audio_path.exists():
            raise FileNotFoundError(
                f"No final_mix.mp3 found in {session_dir}. "
                "Run `coolio mix` first."
            )

        output_path = session_dir / output_filename

        return self.compose(thumbnail_path, audio_path, output_path)

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

