"""OpenRouter image generation helper (OpenAI-compatible).

This module is intentionally small and defensive. OpenRouter serves many models
behind an OpenAI-compatible Chat Completions API, but image responses can vary
in shape between providers/models. We therefore:

- Send a multimodal user message containing the reference image + text prompt.
- Try multiple known response shapes to extract image bytes.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from openai import OpenAI

from coolio.config import get_settings


_DATA_URL_RE = re.compile(r"^data:(image/[^;]+);base64,(.+)$", re.DOTALL)


@dataclass(frozen=True)
class GeneratedImage:
    """Result of generating an image."""

    image_bytes: bytes
    mime_type: str
    model_used: str
    prompt: str
    raw_response: dict[str, Any]


def _create_client() -> OpenAI:
    s = get_settings()
    return OpenAI(
        base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key,
    )


def _encode_image_data_url(image_path: Path) -> str:
    data = image_path.read_bytes()
    # We only use this for reference images, so PNG/JPG are expected.
    suffix = image_path.suffix.lower().lstrip(".")
    mime = "image/png" if suffix == "png" else "image/jpeg"
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _decode_data_url(url: str) -> tuple[bytes, str]:
    m = _DATA_URL_RE.match(url.strip())
    if not m:
        raise ValueError("Not a data URL")
    mime_type = m.group(1)
    b64 = m.group(2)
    return base64.b64decode(b64), mime_type


def _extract_image_from_message_content(content: Any) -> tuple[bytes, str] | None:
    """Try to extract image bytes from known OpenAI-style message content shapes."""
    # Content can be:
    # - string (possibly a data URL)
    # - list[dict] (multimodal parts)
    if isinstance(content, str):
        s = content.strip()
        if s.startswith("data:image/"):
            b, mime = _decode_data_url(s)
            return b, mime
        return None

    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue

            # OpenAI-style: { "type": "image_url", "image_url": {"url": "data:image/png;base64,..."} }
            if part.get("type") == "image_url" and isinstance(part.get("image_url"), dict):
                url = part["image_url"].get("url")
                if isinstance(url, str) and url.startswith("data:image/"):
                    b, mime = _decode_data_url(url)
                    return b, mime

            # Some providers may emit: { "type": "output_image", "image": {"url": "..."} }
            if part.get("type") in {"output_image", "image"}:
                image_obj = part.get("image") if isinstance(part.get("image"), dict) else None
                url = image_obj.get("url") if image_obj else None
                if isinstance(url, str) and url.startswith("data:image/"):
                    b, mime = _decode_data_url(url)
                    return b, mime

    return None


def _extract_image_bytes(response: Any) -> tuple[bytes, str]:
    """Extract image bytes + mime from a response, handling multiple shapes."""
    # Prefer accessing response via model_dump() to avoid SDK version differences.
    raw: dict[str, Any]
    if hasattr(response, "model_dump"):
        raw = response.model_dump()
    elif isinstance(response, dict):
        raw = response
    else:
        raw = {}

    # 1) OpenAI Chat Completions: choices[0].message.content may be multimodal parts.
    try:
        choices = raw.get("choices") or []
        if choices and isinstance(choices, list):
            msg = (choices[0] or {}).get("message") or {}
            content = msg.get("content")
            extracted = _extract_image_from_message_content(content)
            if extracted:
                return extracted

            # Some models may put images under message["images"].
            images = msg.get("images")
            if isinstance(images, list) and images:
                first = images[0]
                if isinstance(first, dict):
                    # Expected OpenRouter shape:
                    # {"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}
                    if first.get("type") == "image_url" and isinstance(first.get("image_url"), dict):
                        url = first["image_url"].get("url")
                        if isinstance(url, str) and url.startswith("data:image/"):
                            b, mime = _decode_data_url(url)
                            return b, mime

                    # Fallback: some providers may use {"url": "..."} directly
                    url = first.get("url")
                    if isinstance(url, str) and url.startswith("data:image/"):
                        b, mime = _decode_data_url(url)
                        return b, mime
    except Exception:
        # Continue to other strategies
        pass

    # 2) Top-level "data" array (OpenAI Images-like).
    data = raw.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            b64 = first.get("b64_json")
            if isinstance(b64, str):
                return base64.b64decode(b64), "image/png"
            url = first.get("url")
            if isinstance(url, str) and url.startswith("data:image/"):
                return _decode_data_url(url)

    raise RuntimeError(
        "Could not extract image bytes from model response. "
        "Response did not contain a recognized image payload."
    )


def generate_image_from_reference(
    *,
    reference_image_path: Path,
    prompt: str,
    image_model: str,
    temperature: float = 0.6,
) -> GeneratedImage:
    """Generate an image using a reference image to anchor composition."""
    if not reference_image_path.exists():
        raise FileNotFoundError(f"Reference image not found: {reference_image_path}")

    client = _create_client()
    data_url = _encode_image_data_url(reference_image_path)

    system_prompt = (
        "You are generating a single still image.\n"
        "The user provides a reference image.\n"
        "Hard constraints:\n"
        "- Preserve the foreground subject, pose, outfit, goggles, and DJ gear.\n"
        "- Add modern over-ear DJ headphones to the subject.\n"
        "- Preserve camera framing, perspective, and overall composition.\n"
        "- ONLY change the background/setting behind and around the DJ.\n"
        "- Do not add text, watermarks, logos, UI, or captions.\n"
        "- Keep photorealistic lighting and coherent shadows.\n"
    )

    user_content: list[dict[str, Any]] = [
        {"type": "image_url", "image_url": {"url": data_url}},
        {"type": "text", "text": prompt},
    ]

    # NOTE: OpenRouter multimodal payloads are compatible at runtime, but the
    # OpenAI SDK's strict message typing doesn't model all provider variants.
    # Keep this cast narrowly scoped to avoid changing runtime behavior.
    resp = client.chat.completions.create(
        model=image_model,
        messages=cast(Any, [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]),
        temperature=temperature,
    )

    raw: dict[str, Any] = resp.model_dump() if hasattr(resp, "model_dump") else {}
    img_bytes, mime = _extract_image_bytes(resp)
    return GeneratedImage(
        image_bytes=img_bytes,
        mime_type=mime,
        model_used=image_model,
        prompt=prompt,
        raw_response=raw,
    )

