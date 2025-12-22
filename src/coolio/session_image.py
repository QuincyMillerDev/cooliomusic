"""Session image generation (single-step anchored image prompt).

This module is used by `coolio image <session_dir>`.

Design goals:
- Foreground remains anchored to the reference DJ image.
- Only the background changes per session based on the session concept/genre.
- Avoid overly-detailed "production set" prompts; keep prompts simple and vibe-led.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

_FOREGROUND_LOCK = [
    "foreground DJ subject identity/pose",
    "goggles",
    "jacket/outfit silhouette",
    "hands on mixer",
    "turntables+mixer layout",
    "camera framing/composition",
]


def load_session_json(session_dir: Path) -> dict[str, Any]:
    session_path = Path(session_dir)
    session_json_path = session_path / "session.json"
    if not session_json_path.exists():
        raise FileNotFoundError(f"Missing session.json in: {session_path}")
    return json.loads(session_json_path.read_text())


def build_image_prompt_from_concept(concept: str, genre: str) -> str:
    """Build a single, vibe-led image prompt from the session concept/genre.

    This intentionally avoids structured briefs and prop lists because those can
    push the model toward "staged production set" backgrounds.
    """
    c = (concept or "").strip()
    g = (genre or "").strip()
    constraints = "\n".join(f"- {x}" for x in _FOREGROUND_LOCK)

    return (
        "Edit/variant of the provided reference image.\n"
        "Keep the DJ foreground and all gear exactly the same.\n"
        "Add modern over-ear DJ headphones to the subject (natural fit, no distortion).\n"
        "ONLY change the background environment behind and around the DJ.\n"
        "Keep the change subtle and plausible: a real location/room, not a staged set.\n"
        "Avoid backgrounds that look like a fake production set or a movie set.\n"
        "Match the reference photo's realism: exposure, contrast, white balance, sharpness, and natural texture.\n"
        "Lighting must be ambient, dim, soft, low-key practical lighting; keep highlights controlled.\n"
        "No text/signage/logos. No watermarks. No UI. No captions. No people.\n"
        "No cinematic grading, no bloom, no haze/fog/volumetric light, no neon, no glossy/CGI look.\n"
        "Do not change camera framing, perspective, or composition.\n\n"
        f"MUSIC VIBE (use as subtle background inspiration, not literal objects):\n"
        f"- genre: {g}\n"
        f"- concept: {c}\n\n"
        "DO NOT CHANGE FOREGROUND:\n"
        f"{constraints}\n"
    )


def now_iso() -> str:
    return datetime.now().isoformat()

