"""Flux image generation for YouTube thumbnails.

Generates 1920x1080 images via fal.ai's Flux model.
"""

import hashlib
import logging
import tempfile
import time
import urllib.request
from pathlib import Path

from coolio.config import get_settings

logger = logging.getLogger(__name__)

try:
    import fal_client
except ImportError:
    fal_client = None  # type: ignore[assignment]


class VisualGenerator:
    """Generates thumbnail images using Flux via fal.ai."""

    def __init__(
        self,
        model: str = "fal-ai/flux/dev",
        width: int = 1920,
        height: int = 1080,
    ):
        """Initialize the visual generator.

        Args:
            model: Flux model variant (dev, schnell, pro).
            width: Output image width.
            height: Output image height.
        """
        if fal_client is None:
            raise ImportError(
                "fal-client not installed. Run: pip install fal-client"
            )

        self.model = model
        self.width = width
        self.height = height

    def _get_deterministic_seed(self, session_id: str) -> int:
        """Generate a deterministic seed from session ID.

        This ensures the same session always produces the same image
        (assuming the same prompt).

        Args:
            session_id: The session identifier.

        Returns:
            Integer seed derived from session ID.
        """
        hash_bytes = hashlib.sha256(session_id.encode()).digest()
        # Use first 4 bytes as seed (mod to keep in reasonable range)
        seed = int.from_bytes(hash_bytes[:4], "big") % (2**31)
        return seed

    def generate(
        self,
        prompt: str,
        session_id: str,
        output_dir: Path | None = None,
    ) -> Path:
        """Generate a thumbnail image.

        Args:
            prompt: Flux prompt for image generation.
            session_id: Session ID for deterministic seeding and filename.
            output_dir: Directory to save the image (defaults to temp).

        Returns:
            Path to the generated image file.
        """
        s = get_settings()
        api_key = s.fal_api_key
        if not api_key:
            raise ValueError("FAL_KEY environment variable not set")

        # Set API key in environment for fal_client
        import os
        os.environ["FAL_KEY"] = api_key

        seed = self._get_deterministic_seed(session_id)

        logger.info(f"Generating thumbnail with {self.model}...")
        logger.info(f"  Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
        logger.info(f"  Size: {self.width}x{self.height}")
        logger.info(f"  Seed: {seed}")

        start_time = time.time()

        # Build request arguments
        arguments = {
            "prompt": prompt,
            "image_size": {
                "width": self.width,
                "height": self.height,
            },
            "num_images": 1,
            "seed": seed,
            "enable_safety_checker": False,
        }

        # Submit and wait for result
        result = fal_client.subscribe(
            self.model,
            arguments=arguments,
            with_logs=False,
        )

        elapsed = time.time() - start_time
        logger.info(f"Generation complete in {elapsed:.1f}s")

        # Extract image URL
        if "images" not in result or len(result["images"]) == 0:
            raise ValueError(f"Unexpected Flux response format: {result}")

        image_url = result["images"][0]["url"]

        # Determine output path
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{session_id}_thumbnail.png"
        else:
            # Use temp directory
            temp_dir = Path(tempfile.gettempdir()) / "coolio_visuals"
            temp_dir.mkdir(parents=True, exist_ok=True)
            output_path = temp_dir / f"{session_id}_thumbnail.png"

        # Download image
        logger.info(f"Downloading to {output_path}...")
        urllib.request.urlretrieve(image_url, output_path)

        logger.info(f"Thumbnail saved: {output_path}")
        return output_path

