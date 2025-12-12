"""Session image generation (background brief + anchored image prompt).

This module is used by `coolio image <session_dir>`.

Design goals:
- Foreground remains anchored to the reference DJ image.
- Only background changes per session based on session metadata.
- Keep prompts compact and deterministic-ish for repeatability.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import OpenAI

from coolio.config import get_settings


BACKGROUND_BRIEF_SCHEMA = """Return valid JSON with this schema:
{
  "setting": "1-2 sentences describing only the environment behind/around the DJ; keep it subtle and plausible (background replacement, not a new fantasy scene)",
  "time_of_day": "e.g. night, golden hour, overcast morning",
  "lighting": "short phrase; MUST be ambient, dim, soft, low-key practical lighting; avoid harsh whites, overexposure, blown highlights, or hard flash; match the reference exposure/contrast/white balance; do not add cinematic effects; do not change lighting direction drastically",
  "color_palette": ["3-6 color words"],
  "props_background_only": ["2-5 items that appear in the BACKGROUND only that complement the music vibe; keep them realistic and understated"],
  "camera_style": "1 sentence; must remain consistent with reference image (same focal length/framing/perspective); documentary/photo-real",
  "do_not_change_foreground": [
    "foreground DJ subject identity/pose",
    "goggles",
    "jacket/outfit silhouette",
    "hands on mixer",
    "turntables+mixer layout",
    "camera framing/composition"
  ]
}
"""


FOREGROUND_LOCK = [
    "foreground DJ subject identity/pose",
    "goggles",
    "jacket/outfit silhouette",
    "hands on mixer",
    "turntables+mixer layout",
    "camera framing/composition",
]


@dataclass(frozen=True)
class BackgroundBrief:
    setting: str
    time_of_day: str
    lighting: str
    color_palette: list[str]
    props_background_only: list[str]
    camera_style: str
    do_not_change_foreground: list[str]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BackgroundBrief":
        return cls(
            setting=str(d.get("setting", "")).strip(),
            time_of_day=str(d.get("time_of_day", "")).strip(),
            lighting=str(d.get("lighting", "")).strip(),
            color_palette=[str(x).strip() for x in (d.get("color_palette") or []) if str(x).strip()],
            props_background_only=[str(x).strip() for x in (d.get("props_background_only") or []) if str(x).strip()],
            camera_style=str(d.get("camera_style", "")).strip(),
            do_not_change_foreground=[str(x).strip() for x in (d.get("do_not_change_foreground") or []) if str(x).strip()],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "setting": self.setting,
            "time_of_day": self.time_of_day,
            "lighting": self.lighting,
            "color_palette": self.color_palette,
            "props_background_only": self.props_background_only,
            "camera_style": self.camera_style,
            "do_not_change_foreground": self.do_not_change_foreground,
        }


def _create_client() -> OpenAI:
    s = get_settings()
    return OpenAI(
        base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key,
    )


def load_session_json(session_dir: Path) -> dict[str, Any]:
    session_path = Path(session_dir)
    session_json_path = session_path / "session.json"
    if not session_json_path.exists():
        raise FileNotFoundError(f"Missing session.json in: {session_path}")
    return json.loads(session_json_path.read_text())


def build_visual_seed(session_meta: dict[str, Any], *, max_tracks: int = 8) -> dict[str, Any]:
    concept = str(session_meta.get("concept", "")).strip()
    genre = str(session_meta.get("genre", "")).strip()
    slots = session_meta.get("slots") or []

    # Keep seed compact to avoid "literal scene generation" from detailed prompts.
    # We want the vibe, not a storyboarding of environments.
    examples: list[dict[str, str]] = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        if slot.get("source") != "generate":
            continue
        title = str(slot.get("title", "")).strip()
        prompt = str(slot.get("prompt", "")).strip()
        if not (title or prompt):
            continue
        examples.append({"title": title[:120]})
        if len(examples) >= max_tracks:
            break

    return {
        "concept": concept,
        "genre": genre,
        "track_examples": examples,
    }


def generate_background_brief(
    *,
    seed: dict[str, Any],
    model: str,
) -> BackgroundBrief:
    """Generate a background-only art direction brief from session metadata."""
    client = _create_client()

    system_prompt = (
        "You are a creative director generating ONLY a background environment brief.\n"
        "The foreground DJ subject and gear are locked to a reference image and must NOT change.\n"
        "Do not describe changes to the DJ, clothing, goggles, hands, turntables, mixer, framing, or camera angle.\n"
        "Focus exclusively on the set/room/environment behind and around the subject.\n"
        "Treat this as BACKGROUND REPLACEMENT inside the same photo, not a new scene.\n"
        "Photorealistic, understated, documentary look. Match the reference realism.\n"
        "Lighting style requirement: ambient, dim, soft, low-key practical lighting with controlled highlights.\n"
        "Hard bans (do not include in your brief): neon, bloom, haze/fog/volumetric light, cinematic grading, ultra glossy reflections, CGI look, high-key lighting, hard flash, harsh whites, overexposure/blown highlights.\n"
        "Keep changes subtle: think wall treatment + a few props + practical lighting, nothing dramatic.\n\n"
        f"{BACKGROUND_BRIEF_SCHEMA}"
    )

    user_prompt = (
        "Generate a background setting brief that matches the feeling of this music session.\n"
        "Constraints:\n"
        "- Foreground is locked; ONLY background changes.\n"
        "- Avoid text/signage/logos in the background.\n"
        "- Do not mention brand names.\n"
        "- Keep the vibe aligned with the music, but keep the background plausible and subtle.\n"
        "- Prefer \"home-studio / small room / understated set\" realism unless the seed strongly demands otherwise.\n\n"
        f"SESSION_SEED:\n{json.dumps(seed, indent=2)}\n"
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    content = resp.choices[0].message.content
    if not content:
        raise ValueError("Empty response from background brief generator")

    raw = content.strip()
    if raw.startswith("```"):
        first_newline = raw.find("\n")
        if first_newline != -1:
            raw = raw[first_newline + 1 :]
        if raw.endswith("```"):
            raw = raw[:-3].strip()

    data = json.loads(raw)
    brief = BackgroundBrief.from_dict(data)
    if not brief.do_not_change_foreground:
        brief = BackgroundBrief.from_dict({**brief.to_dict(), "do_not_change_foreground": FOREGROUND_LOCK})
    return brief


def build_image_prompt(brief: BackgroundBrief) -> str:
    """Build the final image-generation prompt, emphasizing background-only edits."""
    palette = ", ".join(brief.color_palette) if brief.color_palette else ""
    props = ", ".join(brief.props_background_only) if brief.props_background_only else ""

    constraints = "\n".join(f"- {c}" for c in (brief.do_not_change_foreground or FOREGROUND_LOCK))

    return (
        "Edit/variant of the provided reference image.\n"
        "Keep the DJ foreground and all gear exactly the same.\n"
        "Add modern over-ear DJ headphones to the subject (natural fit, no distortion).\n"
        "ONLY replace the background environment behind and around the DJ (subtle, realistic).\n"
        "Match the reference photo's realism: exposure, contrast, white balance, sharpness, and natural texture.\n"
        "Lighting must be ambient, dim, soft, low-key practical lighting; avoid harsh whites, overexposure, and blown highlights.\n"
        "No cinematic grading, no bloom, no haze/fog, no neon, no glossy/CGI look.\n\n"
        f"BACKGROUND SETTING:\n{brief.setting}\n\n"
        f"TIME OF DAY: {brief.time_of_day}\n"
        f"LIGHTING: {brief.lighting}\n"
        f"COLOR PALETTE: {palette}\n"
        f"BACKGROUND PROPS (background only): {props}\n"
        f"CAMERA STYLE: {brief.camera_style}\n\n"
        "DO NOT CHANGE FOREGROUND:\n"
        f"{constraints}\n\n"
        "NEGATIVE:\n"
        "- no text, no captions, no watermarks, no logos\n"
        "- no extra people, no extra limbs, no distorted hands\n"
        "- no harsh white lighting, no high-key lighting, no hard flash, no overexposure, no blown highlights, no washed-out whites\n"
        "- no bloom, no neon, no haze/fog/volumetric light, no cinematic grading\n"
        "- no ultra glossy reflections, no CGI, no plastic skin, no hyperreal look\n"
        "- no changes to the DJ face, goggles, clothing, pose, or equipment layout (except adding headphones)\n"
    )


def now_iso() -> str:
    return datetime.now().isoformat()

