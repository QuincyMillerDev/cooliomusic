"""Utilities to turn a short clip into a seamless forward-only loop.

We intentionally avoid model-side end-frame control (image_tail) because it tends
to reduce motion. Instead we:
1) Generate a natural 10s clip.
2) Find an internal cycle cut (A..B) where frames match well.
3) Apply a very short seam crossfade (forward-only) to remove single-frame pops.
"""

from __future__ import annotations
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


class VideoLoopError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoopSelection:
    fps: int
    start_frame: int
    end_frame: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    score: float


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise VideoLoopError("ffmpeg not found on PATH (required for `coolio clip`).")
    if not shutil.which("ffprobe"):
        raise VideoLoopError("ffprobe not found on PATH (required for `coolio clip`).")


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise VideoLoopError(
            "Command failed:\n"
            f"  {' '.join(cmd)}\n\n"
            f"stdout:\n{proc.stdout[-2000:]}\n\n"
            f"stderr:\n{proc.stderr[-2000:]}\n"
        )


def _dhash64(img: Image.Image) -> int:
    """Compute a 64-bit difference hash."""
    # 9x8 grayscale; compare adjacent columns.
    g = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    # Pillow typing: `getdata()` returns ImagingCore which isn't typed as Iterable.
    # Convert using Pillow's native method.
    px = g.getdata().tolist()
    h = 0
    bit = 0
    for y in range(8):
        row = px[y * 9 : (y + 1) * 9]
        for x in range(8):
            if row[x] > row[x + 1]:
                h |= 1 << bit
            bit += 1
    return h


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _extract_hashes(
    video_path: Path,
    *,
    fps: int,
    max_dimension: int = 320,
) -> list[int]:
    """Extract perceptual hashes for frames at a given FPS."""
    _require_ffmpeg()
    with tempfile.TemporaryDirectory(prefix="coolio_frames_") as d:
        frames_dir = Path(d)
        out_pattern = str(frames_dir / "frame_%05d.jpg")
        # Keep decoding cheap: low-res frames are sufficient for matching.
        vf = f"fps={fps},scale='min({max_dimension},iw)':'min({max_dimension},ih)':force_original_aspect_ratio=decrease"
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vf",
                vf,
                "-q:v",
                "3",
                out_pattern,
            ]
        )

        files = sorted(frames_dir.glob("frame_*.jpg"))
        if not files:
            raise VideoLoopError("No frames extracted from video; is the video readable?")

        hashes: list[int] = []
        for f in files:
            with Image.open(f) as img:
                hashes.append(_dhash64(img))
        return hashes


def select_best_loop(
    video_path: Path,
    *,
    fps: int = 15,
    loop_min_seconds: float = 4.0,
    loop_max_seconds: float = 9.0,
    continuity_window_frames: int = 3,
) -> LoopSelection:
    """Pick a (start_frame, end_frame) pair that yields a natural loop."""
    hashes = _extract_hashes(video_path, fps=fps)

    n = len(hashes)
    if n < fps * 2:
        raise VideoLoopError("Video too short to find a stable loop.")

    min_gap = max(2, int(loop_min_seconds * fps))
    max_gap = max(min_gap + 1, int(loop_max_seconds * fps))

    best_score = float("inf")
    best: tuple[int, int] | None = None

    # Precompute “typical” per-frame change so we can avoid picking seams that pop.
    step_diffs = [_hamming(hashes[i], hashes[i + 1]) for i in range(n - 1)]
    typical_step = sorted(step_diffs)[len(step_diffs) // 2] if step_diffs else 0
    typical_step = max(1, typical_step)

    for start in range(0, n - min_gap - 1):
        end_lo = start + min_gap
        end_hi = min(n - 1, start + max_gap)
        for end in range(end_lo, end_hi + 1):
            # Seam is end -> start.
            d0 = _hamming(hashes[start], hashes[end])

            # Local continuity check around the seam.
            # Compare (start+k) against (end-k) so we don't require frames beyond end.
            cont = 0
            kmax = min(continuity_window_frames, start, end - start - 1)
            for k in range(1, kmax + 1):
                cont += _hamming(hashes[start + k], hashes[end - k])

            # Normalize scores. Favor seams that are not wildly larger than typical motion.
            seam_norm = d0 / typical_step
            cont_norm = (cont / max(1, kmax)) / typical_step if kmax > 0 else seam_norm

            # Small bias toward longer loops within range.
            gap = end - start
            duration = gap / fps
            length_bias = 1.0 - min(0.25, (duration - loop_min_seconds) / max(0.001, loop_max_seconds - loop_min_seconds) * 0.25)

            score = (seam_norm * 0.75 + cont_norm * 0.25) * length_bias

            if score < best_score:
                best_score = score
                best = (start, end)

    if not best:
        raise VideoLoopError("Failed to find a loop candidate.")

    start, end = best
    start_s = start / fps
    end_s = end / fps
    return LoopSelection(
        fps=fps,
        start_frame=start,
        end_frame=end,
        start_seconds=start_s,
        end_seconds=end_s,
        duration_seconds=end_s - start_s,
        score=best_score,
    )


def render_forward_only_loop(
    *,
    input_video_path: Path,
    output_video_path: Path,
    selection: LoopSelection,
    seam_seconds: float = 0.2,
    crf: int = 18,
    preset: str = "veryfast",
) -> None:
    """Cut the selected segment and apply a tiny end→start crossfade (forward-only)."""
    _require_ffmpeg()

    start_s = max(0.0, selection.start_seconds)
    end_s = max(start_s + 0.05, selection.end_seconds)
    seg_dur = max(0.1, end_s - start_s)
    seam = min(max(0.05, seam_seconds), max(0.05, seg_dur / 2.5))

    with tempfile.TemporaryDirectory(prefix="coolio_loop_") as d:
        tmp_dir = Path(d)
        segment = tmp_dir / "segment.mp4"

        # Cut segment.
        _run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{start_s:.3f}",
                "-to",
                f"{end_s:.3f}",
                "-i",
                str(input_video_path),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                str(segment),
            ]
        )

        # Seam smoothing: xfade across the segment boundary, then trim back to seg_dur.
        # Use two inputs of the same segment; offset is where the fade starts.
        offset = max(0.0, seg_dur - seam)
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(segment),
                "-i",
                str(segment),
                "-filter_complex",
                (
                    "[0:v]setpts=PTS-STARTPTS[v0];"
                    "[1:v]setpts=PTS-STARTPTS[v1];"
                    f"[v0][v1]xfade=transition=fade:duration={seam:.3f}:offset={offset:.3f},"
                    f"trim=duration={seg_dur:.3f},setpts=PTS-STARTPTS[v]"
                ),
                "-map",
                "[v]",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output_video_path),
            ]
        )

