"""Compose the final YouTube upload bundle for a session.

`coolio compose <session_dir>` is the final offline step before uploading:
- Renders a full-length video by looping `session_clip.mp4` over `final_mix.mp3`
  with a short fade-in.
- Generates YouTube metadata files:
  - youtube_metadata.json
  - youtube_metadata.txt

Uploading is explicitly out of scope.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

from coolio.config import get_settings


class ComposeError(RuntimeError):
    pass


BUY_ME_A_COFFEE_URL = "https://buymeacoffee.com/cooliomusic"
# Keep verbatim (user-provided). We append this ourselves to guarantee inclusion exactly once.
APOLOGY_LINE = "Apologies the loop is not perfect, im working to make these videos fun and better every day"

# Keep these intentionally fixed; no CLI flags unless we later discover it is necessary.
DEFAULT_AUDIO_FADE_IN_SECONDS = 1.5
DEFAULT_VIDEO_FADE_IN_SECONDS = 0.75


@dataclass(frozen=True)
class Chapter:
    timestamp: str
    title: str


@dataclass(frozen=True)
class YoutubeMetadata:
    title: str
    description: str
    tags: list[str]
    hashtags: list[str]
    chapters: list[Chapter]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "hashtags": self.hashtags,
            "chapters": [{"timestamp": c.timestamp, "title": c.title} for c in self.chapters],
        }


@dataclass(frozen=True)
class ComposeResult:
    session_dir: Path
    final_video_path: Path
    youtube_metadata_json_path: Path
    youtube_metadata_txt_path: Path


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise ComposeError("ffmpeg not found on PATH (required for `coolio compose`).")
    if not shutil.which("ffprobe"):
        raise ComposeError("ffprobe not found on PATH (required for `coolio compose`).")


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise ComposeError(
            "Command failed:\n"
            f"  {' '.join(cmd)}\n\n"
            f"stdout:\n{proc.stdout[-2000:]}\n\n"
            f"stderr:\n{proc.stderr[-2000:]}\n"
        )


def _probe_duration_seconds(media_path: Path) -> float:
    _require_ffmpeg()
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise ComposeError(f"ffprobe failed for {media_path}:\n{proc.stderr[-2000:]}")
    raw = (proc.stdout or "").strip()
    try:
        duration = float(raw)
    except ValueError as e:
        raise ComposeError(f"Could not parse duration from ffprobe output: {raw!r}") from e
    if duration <= 0:
        raise ComposeError(f"Non-positive duration for {media_path}: {duration}")
    return duration


_TRACKLIST_LINE_RE = re.compile(r"^\s*(\d{1,}:\d{2}(?::\d{2})?)\s*-\s*(.+?)\s*$")


def _parse_hms_to_seconds(ts: str) -> int:
    parts = ts.split(":")
    if len(parts) == 2:
        mm, ss = parts
        return int(mm) * 60 + int(ss)
    if len(parts) == 3:
        hh, mm, ss = parts
        return int(hh) * 3600 + int(mm) * 60 + int(ss)
    raise ComposeError(f"Invalid timestamp format: {ts!r}")


def _format_youtube_timestamp(total_seconds: int) -> str:
    if total_seconds < 0:
        total_seconds = 0
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def parse_tracklist_for_youtube(tracklist_path: Path) -> list[Chapter]:
    """Parse mixer-generated tracklist.txt into YouTube chapters.

    The mixer currently outputs timestamps as MM:SS even past 1h (minutes can exceed 59).
    YouTube chapter parsing is more reliable with HH:MM:SS for videos >= 1h, so we
    normalize long timestamps accordingly.
    """
    raw = tracklist_path.read_text()
    chapters: list[Chapter] = []
    for line in raw.splitlines():
        m = _TRACKLIST_LINE_RE.match(line)
        if not m:
            continue
        ts_raw = m.group(1)
        title = m.group(2).strip()
        seconds = _parse_hms_to_seconds(ts_raw)
        ts = _format_youtube_timestamp(seconds)
        chapters.append(Chapter(timestamp=ts, title=title))
    if not chapters:
        raise ComposeError(f"No chapters found in tracklist: {tracklist_path}")
    return chapters


def render_final_youtube_video(
    *,
    session_clip_path: Path,
    final_mix_path: Path,
    output_path: Path,
) -> None:
    """Render a full-length MP4 by looping the short clip over the final mix."""
    _require_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # We use `-shortest` so the output ends exactly when the audio ends
    # (video is looped infinitely).
    vf = f"fade=t=in:st=0:d={DEFAULT_VIDEO_FADE_IN_SECONDS:.3f}"
    af = f"afade=t=in:st=0:d={DEFAULT_AUDIO_FADE_IN_SECONDS:.3f}"

    cmd = [
        "ffmpeg",
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(session_clip_path),
        "-i",
        str(final_mix_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-vf",
        vf,
        "-af",
        af,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output_path),
    ]
    _run(cmd)


def _create_openrouter_client() -> OpenAI:
    s = get_settings()
    return OpenAI(base_url=s.openrouter_base_url, api_key=s.openrouter_api_key)


def _normalize_hashtags(hashtags: list[str]) -> list[str]:
    cleaned: list[str] = []
    for h in hashtags:
        t = str(h).strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = f"#{t}"
        cleaned.append(t)
    # preserve order, de-dupe
    out: list[str] = []
    seen: set[str] = set()
    for h in cleaned:
        if h.lower() in seen:
            continue
        seen.add(h.lower())
        out.append(h)
    return out


def _normalize_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in tags:
        s = str(t).strip()
        if not s:
            continue
        if "http://" in s.lower() or "https://" in s.lower():
            # YouTube tags should not include URLs.
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _sanitize_description_intro(intro: str) -> str:
    """Remove common failure modes from the LLM intro.

    We assemble the final description ourselves (support link + tracklist + hashtags),
    so the intro should *not* contain links or tracklist content.
    """
    lines: list[str] = []
    for raw in (intro or "").splitlines():
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        if BUY_ME_A_COFFEE_URL in line:
            continue
        if _TRACKLIST_LINE_RE.match(line):
            continue
        if "tracklist" in line.lower():
            continue
        if "apologies the loop is not perfect" in line.lower():
            # We append the apology line ourselves to avoid duplicates.
            continue
        if "http://" in line.lower() or "https://" in line.lower():
            continue
        lines.append(line)

    # Collapse repeated blank lines and trim.
    compact: list[str] = []
    prev_blank = True
    for line in lines:
        blank = line.strip() == ""
        if blank and prev_blank:
            continue
        compact.append("" if blank else line)
        prev_blank = blank
    return "\n".join(compact).strip()


_TITLE_HOOK_BANNED = {
    "ambient",
    "techno",
    "house",
    "deep",
    "minimal",
    "berlin",
    "playlist",
    "mix",
    "dj",
    "set",
    "focus",
    "study",
    "work",
}


def _build_title_right_side(genre: str) -> str:
    """Build the descriptor portion after the `//`."""
    g = (genre or "").strip()
    if not g:
        g = "ambient techno"

    # Avoid overly-long genre blobs from the planner; keep it YouTube-friendly.
    # Examples: "deep minimal club-focused electronic" -> "deep minimal techno"
    lowered = g.lower()
    if "techno" not in lowered and "house" not in lowered and "ambient" not in lowered:
        # best-effort default
        g = f"{g} techno"

    # Prefer "playlist" language unless the descriptor already implies mix.
    if "mix" in lowered or "dj" in lowered:
        return f"{g} mix"
    return f"{g} playlist"


def _pick_fallback_title_hook(seed: str) -> str:
    """Pick a deterministic abstract hook (no genre words)."""
    hooks = [
        "time stopped about three hours ago.",
        "flow is a state of mind.",
        "escape the matrix.",
        "somewhere between signal and silence.",
        "let the room disappear.",
        "midnight without a clock.",
        "no thoughts, just motion.",
        "the city hums in slow motion.",
        "keep going—quietly.",
        "background pressure, foreground calm.",
    ]
    h = hashlib.sha256(seed.encode("utf-8")).digest()
    idx = int.from_bytes(h[:2], "big") % len(hooks)
    return hooks[idx]


def _sanitize_title(title: str, *, seed: str, genre: str) -> str:
    """Ensure title format: `<abstract hook> // <descriptor>`."""
    raw = (title or "").strip()
    if not raw:
        raw = ""

    # Normalize common separators to `//`.
    for sep in [" | ", " - ", " · ", " • ", " — ", " – "]:
        if sep in raw and "//" not in raw:
            raw = raw.replace(sep, " // ", 1)
            break

    if "//" in raw:
        left, right = [p.strip() for p in raw.split("//", 1)]
    else:
        left, right = "", raw

    # Validate left: must be an abstract hook, not just genre words.
    left_words = re.findall(r"[a-zA-Z']+", left.lower())
    left_is_bad = (not left) or all(w in _TITLE_HOOK_BANNED for w in left_words)
    if left_is_bad:
        left = _pick_fallback_title_hook(seed)

    # If right side is empty or unhelpful, rebuild from genre.
    if not right or right.lower() in {"playlist", "mix"}:
        right = _build_title_right_side(genre)
    else:
        # Ensure `//` side is descriptive (and not another abstract phrase).
        # If it doesn't mention playlist/mix at all, append playlist.
        rlow = right.lower()
        if "playlist" not in rlow and "mix" not in rlow:
            right = f"{right} playlist"

    return f"{left} // {right}"


def generate_youtube_metadata(
    *,
    session_meta: dict[str, Any],
    chapters: list[Chapter],
) -> YoutubeMetadata:
    """Generate title/description/tags while keeping timestamps exact."""
    s = get_settings()
    model = s.openrouter_model

    concept = str(session_meta.get("concept", "")).strip()
    genre = str(session_meta.get("genre", "")).strip()
    session_id = str(session_meta.get("session_id", "")).strip()

    chapter_lines = "\n".join(f"{c.timestamp} - {c.title}" for c in chapters)

    system = (
        "You are writing YouTube metadata for a music mix video.\n"
        "Write in a human creator voice. Avoid cringe. Avoid overclaiming.\n"
        "No lying: do not invent track titles, timestamps, or links.\n"
        "The tracklist timestamps are provided and must be used EXACTLY.\n"
        "Return ONLY valid JSON.\n"
    )

    user = (
        "Create YouTube metadata JSON with this schema:\n"
        "{\n"
        '  \"title\": \"string\",\n'
        '  \"description_intro\": \"string (1-2 short paragraphs max; NO links; NO tracklist; NO timestamps)\",\n'
        '  \"hashtags\": [\"#Tag1\", \"#Tag2\", ...],\n'
        '  \"tags\": [\"tag\", \"tag\", ...]\n'
        "}\n\n"
        "Constraints:\n"
        "- Title MUST use this format exactly: <abstract hook> // <descriptor>\n"
        "- Use `//` (double slash). Do NOT use hyphens or pipes as the main separator.\n"
        "- The abstract hook must NOT be just the genre words. Make it a short, punchy, abstract phrase.\n"
        "- Examples:\n"
        "  - time stopped about three hours ago. // ambient deep techno playlist\n"
        "  - flow is a state of mind. // ambient techno playlist\n"
        "  - escape the matrix. // ambient deep techno mix\n"
        f"- Buy Me a Coffee link must be used exactly: {BUY_ME_A_COFFEE_URL}\n"
        f"- This exact sentence must appear in the final description (we will append it verbatim): {APOLOGY_LINE}\n"
        "- description_intro must NOT include any URLs, promo links, or the tracklist.\n"
        "- description_intro must NOT include the apology sentence.\n"
        "- Do NOT add other promo links.\n"
        "- Do NOT mention views, dates, or fake stats.\n"
        "- Keep the title concise and compelling.\n\n"
        f"Session:\n- session_id: {session_id}\n- genre: {genre}\n- concept: {concept}\n\n"
        "Exact tracklist (MUST be preserved verbatim in the final description we assemble):\n"
        f"{chapter_lines}\n"
    )

    client = _create_openrouter_client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    content = resp.choices[0].message.content
    if not content:
        raise ComposeError("Empty response from metadata generator.")
    raw = content.strip()
    if raw.startswith("```"):
        first_newline = raw.find("\n")
        if first_newline != -1:
            raw = raw[first_newline + 1 :]
        if raw.endswith("```"):
            raw = raw[:-3].strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ComposeError(f"Invalid JSON from metadata generator: {e}") from e

    title_seed = f"{session_id}|{concept}|{genre}"
    title = _sanitize_title(str(data.get("title", "")).strip(), seed=title_seed, genre=genre)
    intro = _sanitize_description_intro(str(data.get("description_intro", "")).strip())
    hashtags = _normalize_hashtags(list(data.get("hashtags") or []))
    tags = _normalize_tags(list(data.get("tags") or []))

    if not title:
        raise ComposeError("Metadata generator returned empty title.")
    if not intro:
        raise ComposeError("Metadata generator returned empty description_intro.")

    description = "\n\n".join(
        [
            intro,
            APOLOGY_LINE,
            f"► Support Cooliomusic: {BUY_ME_A_COFFEE_URL}",
            "// Tracklist",
            chapter_lines,
            " ".join(hashtags) if hashtags else "",
        ]
    ).strip() + "\n"

    return YoutubeMetadata(
        title=title,
        description=description,
        tags=tags,
        hashtags=hashtags,
        chapters=chapters,
    )


def load_session_json(session_dir: Path) -> dict[str, Any]:
    session_json_path = Path(session_dir) / "session.json"
    if not session_json_path.exists():
        raise ComposeError(f"Missing session.json in: {session_dir}")
    return json.loads(session_json_path.read_text())


def compose_session(session_dir: Path) -> ComposeResult:
    """Main entrypoint used by the CLI."""
    session_dir = Path(session_dir)
    if not session_dir.exists():
        raise ComposeError(f"Session directory not found: {session_dir}")

    final_mix = session_dir / "final_mix.mp3"
    tracklist = session_dir / "tracklist.txt"
    clip = session_dir / "session_clip.mp4"
    if not final_mix.exists():
        raise ComposeError(f"Missing final mix: {final_mix} (run `coolio mix` first)")
    if not tracklist.exists():
        raise ComposeError(f"Missing tracklist: {tracklist} (run `coolio mix` first)")
    if not clip.exists():
        raise ComposeError(f"Missing session clip: {clip} (run `coolio clip` first)")

    # Probe mix duration early so errors appear before long ffmpeg work.
    _probe_duration_seconds(final_mix)

    out_video = session_dir / "final_youtube.mp4"
    out_json = session_dir / "youtube_metadata.json"
    out_txt = session_dir / "youtube_metadata.txt"

    # 1) Render final video
    render_final_youtube_video(
        session_clip_path=clip,
        final_mix_path=final_mix,
        output_path=out_video,
    )

    # 2) Generate metadata
    session_meta = load_session_json(session_dir)
    chapters = parse_tracklist_for_youtube(tracklist)
    yt = generate_youtube_metadata(session_meta=session_meta, chapters=chapters)

    payload: dict[str, Any] = {
        **yt.to_dict(),
        "buy_me_a_coffee_url": BUY_ME_A_COFFEE_URL,
        "session_dir": str(session_dir),
        "final_video_path": str(out_video),
        "final_mix_path": str(final_mix),
        "session_clip_path": str(clip),
        "tracklist_path": str(tracklist),
        "session_id": str(session_meta.get("session_id", "")),
        "genre": str(session_meta.get("genre", "")),
        "concept": str(session_meta.get("concept", "")),
        "model_used": get_settings().openrouter_model,
    }

    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    # Copy/paste file
    out_txt.write_text(
        "\n".join(
            [
                f"Title: {yt.title}",
                "",
                "Description:",
                yt.description.rstrip(),
                "",
                "Tags:",
                ", ".join(yt.tags),
                "",
            ]
        )
        + "\n"
    )

    return ComposeResult(
        session_dir=session_dir,
        final_video_path=out_video,
        youtube_metadata_json_path=out_json,
        youtube_metadata_txt_path=out_txt,
    )

