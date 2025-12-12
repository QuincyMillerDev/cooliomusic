"""Kling AI (image-to-video) provider.

Implements the Image-to-Video API described in docs/KLINGAI_IMAGE_TO_VIDEO_API.md.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hmac
import hashlib
import json
import time
from typing import Any

import httpx


@dataclass(frozen=True)
class KlingTask:
    task_id: str
    task_status: str
    task_status_msg: str | None
    raw: dict[str, Any]


class KlingError(RuntimeError):
    def __init__(self, message: str, *, raw: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.raw = raw or {}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _encode_jwt_token(*, access_key: str, secret_key: str, lifetime_s: int = 1800) -> str:
    """Generate Kling API_TOKEN per Kling docs (HS256 JWT with iss/exp/nbf)."""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": access_key,
        "exp": now + lifetime_s,
        "nbf": now - 5,
    }

    header_b64 = _b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    sig = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url(sig)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def _auth_headers(*, access_key: str, secret_key: str) -> dict[str, str]:
    token = _encode_jwt_token(access_key=access_key, secret_key=secret_key)
    return {
        # Kling docs specify Authorization: Bearer <token>
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _raise_for_kling_response(payload: dict[str, Any]) -> None:
    # Kling uses `code == 0` for success.
    code = payload.get("code")
    if code != 0:
        msg = payload.get("message") or "Kling API error"
        raise KlingError(f"{msg} (code={code})", raw=payload)


def create_image2video_task(
    *,
    access_key: str,
    secret_key: str,
    base_url: str,
    image_b64: str,
    prompt: str,
    negative_prompt: str | None,
    model_name: str,
    mode: str,
    duration: str = "10",
    timeout_s: float = 60.0,
) -> str:
    """Create a Kling image2video task and return task_id."""
    url = f"{base_url.rstrip('/')}/v1/videos/image2video"
    body: dict[str, Any] = {
        "model_name": model_name,
        "mode": mode,
        "duration": duration,
        "image": image_b64,
        "prompt": prompt,
    }
    if negative_prompt:
        body["negative_prompt"] = negative_prompt

    with httpx.Client(timeout=timeout_s) as client:
        resp = client.post(
            url,
            headers=_auth_headers(access_key=access_key, secret_key=secret_key),
            json=body,
        )

    if resp.status_code >= 400:
        raise KlingError(
            f"Kling create-task HTTP {resp.status_code}: {resp.text[:500]}",
            raw={"status_code": resp.status_code, "text": resp.text},
        )

    payload = resp.json()
    _raise_for_kling_response(payload)

    data = payload.get("data") or {}
    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise KlingError("Kling create-task returned no task_id", raw=payload)
    return task_id


def get_task(
    *,
    access_key: str,
    secret_key: str,
    base_url: str,
    task_id: str,
    timeout_s: float = 60.0,
) -> KlingTask:
    """Fetch a single task status."""
    url = f"{base_url.rstrip('/')}/v1/videos/image2video/{task_id}"
    with httpx.Client(timeout=timeout_s) as client:
        resp = client.get(
            url,
            headers=_auth_headers(access_key=access_key, secret_key=secret_key),
        )

    if resp.status_code >= 400:
        raise KlingError(
            f"Kling get-task HTTP {resp.status_code}: {resp.text[:500]}",
            raw={"status_code": resp.status_code, "text": resp.text},
        )

    payload = resp.json()
    _raise_for_kling_response(payload)
    data = payload.get("data") or {}

    status = data.get("task_status")
    if not isinstance(status, str) or not status:
        raise KlingError("Kling get-task returned no task_status", raw=payload)

    status_msg = data.get("task_status_msg")
    if status_msg is not None and not isinstance(status_msg, str):
        status_msg = str(status_msg)

    return KlingTask(
        task_id=task_id,
        task_status=status,
        task_status_msg=status_msg,
        raw=payload,
    )


def poll_task_until_complete(
    *,
    access_key: str,
    secret_key: str,
    base_url: str,
    task_id: str,
    timeout_s: float = 600.0,
    poll_interval_s: float = 3.0,
) -> dict[str, Any]:
    """Poll a task until succeed/failed and return the final task payload (data.task_result)."""
    import time

    deadline = time.time() + timeout_s
    last: KlingTask | None = None
    while time.time() < deadline:
        t = get_task(
            access_key=access_key,
            secret_key=secret_key,
            base_url=base_url,
            task_id=task_id,
        )
        last = t

        if t.task_status == "succeed":
            data = t.raw.get("data") or {}
            result = data.get("task_result")
            if not isinstance(result, dict):
                raise KlingError("Kling task succeeded but task_result missing", raw=t.raw)
            return result

        if t.task_status == "failed":
            msg = t.task_status_msg or "Kling task failed"
            raise KlingError(msg, raw=t.raw)

        time.sleep(poll_interval_s)

    msg = "Timed out waiting for Kling task"
    if last and last.task_status_msg:
        msg = f"{msg}: {last.task_status_msg}"
    raise KlingError(msg, raw=(last.raw if last else None))


def extract_video_url(task_result: dict[str, Any]) -> str:
    """Return the first video URL from task_result."""
    videos = task_result.get("videos")
    if not isinstance(videos, list) or not videos:
        raise KlingError("Kling task_result.videos missing/empty", raw={"task_result": task_result})

    first = videos[0]
    if not isinstance(first, dict):
        raise KlingError("Kling task_result.videos[0] is not an object", raw={"task_result": task_result})

    url = first.get("url")
    if not isinstance(url, str) or not url:
        raise KlingError("Kling task_result.videos[0].url missing", raw={"task_result": task_result})
    return url


def download_video_bytes(
    *,
    url: str,
    timeout_s: float = 180.0,
) -> bytes:
    """Download the generated mp4 from Kling's hosted URL."""
    with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
        resp = client.get(url)

    if resp.status_code >= 400:
        raise KlingError(
            f"Failed to download video HTTP {resp.status_code}: {resp.text[:500]}",
            raw={"status_code": resp.status_code, "text": resp.text, "url": url},
        )
    return resp.content

