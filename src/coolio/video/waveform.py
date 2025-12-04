"""Waveform visualization generation using FFmpeg.

Creates an audio-reactive waveform overlay video that syncs with the mixed audio.
"""

import logging
import subprocess
import tempfile
from pathlib import Path

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


def generate_waveform_video(
    audio_path: Path,
    output_path: Path,
    width: int = 1920,
    height: int = 1080,
    waveform_height: int = 100,
    waveform_color: str = "white@0.6",
    position_from_bottom: int = 360,
) -> Path:
    """Generate a transparent waveform video from audio.

    Creates a video with a horizontal waveform bar positioned at a specific
    height from the bottom. The waveform is synced to the audio amplitude.

    Args:
        audio_path: Path to the audio file (MP3).
        output_path: Path for the output video file.
        width: Video width in pixels.
        height: Video height in pixels.
        waveform_height: Height of the waveform bar in pixels.
        waveform_color: Color of the waveform (FFmpeg color format).
        position_from_bottom: Distance from bottom of frame in pixels.

    Returns:
        Path to the generated waveform video.
    """
    if not check_ffmpeg():
        raise RuntimeError("FFmpeg not found. Please install FFmpeg.")

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Calculate y position (from top, since FFmpeg uses top-left origin)
    y_position = height - position_from_bottom - waveform_height

    logger.info(f"Generating waveform video from {audio_path}...")
    logger.info(f"  Size: {width}x{height}")
    logger.info(f"  Waveform: {waveform_height}px tall, {position_from_bottom}px from bottom")

    # FFmpeg filter to create waveform visualization
    # showwaves: Creates waveform from audio
    # - s: size of the waveform output
    # - mode: cline = centered line, p2p = point to point
    # - colors: waveform color with alpha
    # - scale: sqrt gives better visual dynamics
    filter_complex = (
        f"[0:a]showwaves=s={width}x{waveform_height}:mode=cline:"
        f"colors={waveform_color}:scale=sqrt:draw=full[wave]"
    )

    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output
        "-i", str(audio_path),
        "-filter_complex", filter_complex,
        "-map", "[wave]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]

    logger.info("  Running FFmpeg...")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error(f"FFmpeg error: {result.stderr}")
        raise RuntimeError(f"FFmpeg waveform generation failed: {result.stderr[-500:]}")

    logger.info(f"  Waveform video saved: {output_path}")
    return output_path


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

