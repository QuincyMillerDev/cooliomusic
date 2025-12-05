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
        waveform_height: int = 120,
        waveform_color: str = "white@0.9",
        fade_in_duration: float = 5.0,
    ):
        """Initialize the video composer.

        Args:
            width: Video width in pixels.
            height: Video height in pixels.
            waveform_height: Height of the waveform bar.
            waveform_color: Waveform core color in FFmpeg format.
            fade_in_duration: Duration of fade-in from black/silence in seconds.
        """
        if not check_ffmpeg():
            raise RuntimeError("FFmpeg not found. Please install FFmpeg.")

        self.width = width
        self.height = height
        self.waveform_height = waveform_height
        self.waveform_color = waveform_color
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
        # 3. Generate glow waveform (50% width, transparent)
        # 4. Generate core waveform (50% width, opaque)
        # 5. Overlay waveforms on thumbnail (centered)
        # 6. Mux with audio

        # Calculate waveform dimensions and position (50% width, centered)
        wave_width = int(self.width * 0.5)
        wave_height = self.waveform_height
        x_pos = int((self.width - wave_width) / 2)
        y_pos = int((self.height - wave_height) / 2)

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
            # Generate waveform glow (Layer 1) - Broader, transparent, blurred
            f"[1:a]showwaves=s={wave_width}x{wave_height}:"
            f"mode=cline:colors=white@0.15:scale=sqrt:draw=full,gblur=sigma=5[glow];"
            # Generate waveform core (Layer 2) - Sharp, opaque, slightly rounded
            f"[1:a]showwaves=s={wave_width}x{wave_height}:"
            f"mode=cline:colors={self.waveform_color}:scale=sqrt:draw=full,gblur=sigma=1[core];"
            # Overlay waveforms on background (centered)
            f"[bg][glow]overlay={x_pos}:{y_pos}:shortest=1[tmp];"
            f"[tmp][core]overlay={x_pos}:{y_pos}:shortest=1[out]"
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

        # Compose the video
        result = self.compose(thumbnail_path, audio_path, output_path)

        # Check thumbnail size for YouTube upload (must be < 2MB)
        # We do this AFTER video composition so the video uses the high-quality source,
        # but we ensure a compliant file exists for upload.
        self._ensure_thumbnail_upload_ready(thumbnail_path)

        return result

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

