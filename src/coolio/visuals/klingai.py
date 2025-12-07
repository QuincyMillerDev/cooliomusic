"""Kling AI image-to-video generation for seamless looping clips.

Generates 10-second looping video clips from session thumbnail images using
Kling AI's image-to-video API with ping-pong loop technique for
natural motion that loops perfectly.

Ping-pong technique:
1. Generate 5-second video with natural motion (no image_tail constraint)
2. Reverse the video with FFmpeg
3. Concatenate: forward + reverse = seamless 10-second loop
"""

import base64
import hashlib
import hmac
import logging
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from coolio.config import get_settings

logger = logging.getLogger(__name__)

# JWT token expiration (30 minutes)
JWT_EXPIRATION_SECONDS = 1800


@dataclass
class VideoGenerationResult:
    """Result of video generation."""

    output_path: Path
    task_id: str
    duration_seconds: int
    model: str


class KlingAIVideoGenerator:
    """Generates looping video clips using Kling AI image-to-video.

    Uses ping-pong loop technique: generate 5s forward, reverse it,
    concatenate for seamless 10s loop with natural motion.
    """

    # API endpoints
    CREATE_TASK_PATH = "/v1/videos/image2video"

    # Polling configuration
    POLL_INTERVAL_SECONDS = 5
    MAX_POLL_ATTEMPTS = 120  # 10 minutes max wait

    def __init__(
        self,
        model: str | None = None,
        mode: str = "pro",
        duration: str = "5",  # Generate 5s, then ping-pong to 10s
    ):
        """Initialize the Kling AI video generator.

        Args:
            model: Kling AI model to use (defaults to settings).
            mode: Generation mode - 'pro' for higher quality.
            duration: Base video duration ('5' recommended for ping-pong).
        """
        s = get_settings()
        self.access_key = s.kling_ai_access_key
        self.secret_key = s.kling_ai_secret_key
        self.base_url = s.klingai_base_url
        self.model = model or s.klingai_model
        self.mode = mode
        self.duration = duration

    def _generate_jwt_token(self) -> str:
        """Generate a JWT token for Kling AI authentication.

        Uses HS256 algorithm with access_key as issuer and secret_key for signing.

        Returns:
            JWT token string.
        """
        import json

        # JWT Header
        header = {"alg": "HS256", "typ": "JWT"}

        # JWT Payload
        now = int(time.time())
        payload = {
            "iss": self.access_key,
            "exp": now + JWT_EXPIRATION_SECONDS,
            "nbf": now - 5,  # Allow 5 seconds clock skew
        }

        # Base64url encode header and payload
        def b64url_encode(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")

        header_b64 = b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        payload_b64 = b64url_encode(json.dumps(payload, separators=(",", ":")).encode())

        # Create signature
        message = f"{header_b64}.{payload_b64}"
        signature = hmac.new(
            self.secret_key.encode(),
            message.encode(),
            hashlib.sha256,
        ).digest()
        signature_b64 = b64url_encode(signature)

        return f"{header_b64}.{payload_b64}.{signature_b64}"

    def _get_headers(self) -> dict:
        """Get HTTP headers for API requests."""
        token = self._generate_jwt_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _encode_image(self, image_path: Path) -> str:
        """Encode image file as base64 string.

        Args:
            image_path: Path to image file.

        Returns:
            Base64-encoded string (no data URL prefix).
        """
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def generate(
        self,
        image_path: Path,
        prompt: str,
        session_id: str,
        output_dir: Path,
    ) -> VideoGenerationResult:
        """Generate a looping video clip from an image using ping-pong technique.

        Creates natural motion that loops perfectly:
        1. Generate 5-second video with motion (no end-frame constraint)
        2. Reverse it with FFmpeg
        3. Concatenate forward + reverse = 10-second seamless loop

        Args:
            image_path: Path to source image (PNG/JPG).
            prompt: Motion prompt describing the desired animation.
            session_id: Session ID for filename.
            output_dir: Directory to save the output video.

        Returns:
            VideoGenerationResult with output path and metadata.

        Raises:
            FileNotFoundError: If image doesn't exist.
            RuntimeError: If generation fails.
        """
        if not image_path.exists():
            raise FileNotFoundError(f"Source image not found: {image_path}")

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{session_id}_clip.mp4"

        logger.info(f"Generating video clip with Kling AI ({self.model})...")
        logger.info(f"  Mode: {self.mode}, Duration: {self.duration}s (will ping-pong to {int(self.duration) * 2}s)")
        logger.info(f"  Prompt: {prompt[:60]}{'...' if len(prompt) > 60 else ''}")

        # Encode image as base64
        image_b64 = self._encode_image(image_path)

        # Create generation task
        task_id = self._create_task(image_b64, prompt)
        logger.info(f"  Task created: {task_id}")

        # Poll for completion
        video_url = self._poll_for_completion(task_id)
        logger.info("  Generation complete, downloading...")

        # Download the raw video to a temp file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            raw_video_path = Path(tmp.name)

        self._download_video(video_url, raw_video_path)
        logger.info("  Creating ping-pong loop with FFmpeg...")

        # Create ping-pong loop: forward + reverse
        self._create_pingpong_loop(raw_video_path, output_path)

        # Clean up temp file
        raw_video_path.unlink(missing_ok=True)

        logger.info(f"  Video saved: {output_path}")

        return VideoGenerationResult(
            output_path=output_path,
            task_id=task_id,
            duration_seconds=int(self.duration) * 2,  # Ping-pong doubles duration
            model=self.model,
        )

    def _create_pingpong_loop(self, input_path: Path, output_path: Path) -> None:
        """Create a ping-pong loop from a video using FFmpeg.

        Concatenates the video with its reverse for seamless looping.

        Args:
            input_path: Path to input video.
            output_path: Path to save the looped video.

        Raises:
            RuntimeError: If FFmpeg fails.
        """
        # FFmpeg filter: concat original with reversed version
        # -filter_complex "[0:v]reverse[r];[0:v][r]concat=n=2:v=1[out]"
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", str(input_path),
            "-filter_complex",
            "[0:v]split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1[out]",
            "-map", "[out]",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg error: {e.stderr}")
            raise RuntimeError(f"FFmpeg ping-pong loop failed: {e.stderr}")

    def _create_task(self, image_b64: str, prompt: str) -> str:
        """Create a video generation task.

        Args:
            image_b64: Base64-encoded source image.
            prompt: Motion prompt.

        Returns:
            Task ID for polling.

        Raises:
            RuntimeError: If task creation fails.
        """
        url = f"{self.base_url}{self.CREATE_TASK_PATH}"

        # Build payload - NO image_tail so the model generates natural motion
        # We create the seamless loop via ping-pong (forward + reverse) in post
        payload = {
            "model_name": self.model,
            "mode": self.mode,
            "duration": self.duration,
            "image": image_b64,
            "prompt": prompt,
        }

        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                url,
                headers=self._get_headers(),
                json=payload,
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"Kling AI task creation failed: {response.status_code} - {response.text}"
            )

        data = response.json()

        if data.get("code") != 0:
            raise RuntimeError(
                f"Kling AI error: {data.get('message', 'Unknown error')}"
            )

        task_id = data.get("data", {}).get("task_id")
        if not task_id:
            raise RuntimeError("No task_id in Kling AI response")

        return task_id

    def _poll_for_completion(self, task_id: str) -> str:
        """Poll for task completion and return the video URL.

        Args:
            task_id: Task ID to poll.

        Returns:
            URL to download the generated video.

        Raises:
            RuntimeError: If task fails or times out.
        """
        url = f"{self.base_url}{self.CREATE_TASK_PATH}/{task_id}"

        for attempt in range(self.MAX_POLL_ATTEMPTS):
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, headers=self._get_headers())

            if response.status_code != 200:
                raise RuntimeError(
                    f"Kling AI poll failed: {response.status_code} - {response.text}"
                )

            data = response.json()

            if data.get("code") != 0:
                raise RuntimeError(
                    f"Kling AI error: {data.get('message', 'Unknown error')}"
                )

            task_data = data.get("data", {})
            status = task_data.get("task_status")

            if status == "succeed":
                # Extract video URL from result
                videos = task_data.get("task_result", {}).get("videos", [])
                if not videos:
                    raise RuntimeError("No videos in Kling AI result")
                return videos[0].get("url")

            if status == "failed":
                msg = task_data.get("task_status_msg", "Unknown failure")
                raise RuntimeError(f"Kling AI generation failed: {msg}")

            # Still processing, wait and retry
            logger.info(f"  Status: {status} (attempt {attempt + 1})")
            time.sleep(self.POLL_INTERVAL_SECONDS)

        raise RuntimeError(
            f"Kling AI task timed out after {self.MAX_POLL_ATTEMPTS * self.POLL_INTERVAL_SECONDS}s"
        )

    def _download_video(self, video_url: str, output_path: Path) -> None:
        """Download video from URL to local file.

        Args:
            video_url: URL of the video to download.
            output_path: Local path to save the video.
        """
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            response = client.get(video_url)

        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to download video: {response.status_code}"
            )

        with open(output_path, "wb") as f:
            f.write(response.content)

