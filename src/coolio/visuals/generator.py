"""Nano Banana Pro image generation for YouTube thumbnails.

Transforms a reference DJ venue photo via OpenRouter's Nano Banana Pro model
(google/gemini-3-pro-image-preview). The model removes people from the reference
image and applies hue/atmosphere modifications while preserving the exact
venue composition.
"""

import base64
import logging
import tempfile
import time
from pathlib import Path

from openai import OpenAI

from coolio.config import get_settings

logger = logging.getLogger(__name__)

# Reference image path (bundled in codebase)
REFERENCE_IMAGE_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "src"
    / "coolio"
    / "assets"
    / "images"
    / "cooliomusicreferencephoto.jpg"
)


def _load_reference_image() -> str:
    """Load and encode the reference image as base64.

    Returns:
        Base64-encoded PNG data.

    Raises:
        FileNotFoundError: If reference image is missing.
    """
    # Handle both installed package and dev paths
    paths_to_try = [
        REFERENCE_IMAGE_PATH,
        Path(__file__).parent.parent / "assets" / "images" / "cooliomusicreferencephoto.jpg",
    ]

    for path in paths_to_try:
        if path.exists():
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")

    raise FileNotFoundError(
        f"Reference image not found. Tried: {[str(p) for p in paths_to_try]}"
    )


class VisualGenerator:
    """Generates thumbnail images using Nano Banana Pro via OpenRouter."""

    MODEL = "google/gemini-3-pro-image-preview"

    def __init__(
        self,
        width: int = 1920,
        height: int = 1080,
    ):
        """Initialize the visual generator.

        Args:
            width: Output image width.
            height: Output image height.
        """
        self.width = width
        self.height = height
        self._reference_b64: str | None = None

    def _get_reference_image(self) -> str:
        """Get the reference image, loading lazily.

        Returns:
            Base64-encoded reference image.
        """
        if self._reference_b64 is None:
            self._reference_b64 = _load_reference_image()
        return self._reference_b64

    def generate(
        self,
        prompt: str,
        session_id: str,
        output_dir: Path | None = None,
    ) -> Path:
        """Generate a thumbnail image.

        Args:
            prompt: Image prompt describing the scene.
            session_id: Session ID for filename.
            output_dir: Directory to save the image (defaults to temp).

        Returns:
            Path to the generated image file.
        """
        s = get_settings()

        client = OpenAI(
            base_url=s.openrouter_base_url,
            api_key=s.openrouter_api_key,
        )

        ref_b64 = self._get_reference_image()

        logger.info(f"Generating thumbnail with {self.MODEL}...")
        logger.info(f"  Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
        logger.info(f"  Size: {self.width}x{self.height}")

        start_time = time.time()

        # Build multimodal message with reference image + prompt
        # We ask the model to TRANSFORM the reference image, not generate from scratch
        generation_prompt = f"""TRANSFORM this exact image with these modifications:

KEEP:
- The DJ equipment (Pioneer CDJs, mixer) position and setup on the wooden table
- The stage lights and fixtures on both sides
- The overall composition and camera angle (behind the DJ booth looking out)
- The atmospheric haze and depth

REMOVE:
- All people - the DJ silhouette in the foreground and the entire crowd
- Replace the crowd area with empty venue space (dark floor, continuing haze)
- The space should feel empty and liminal, like the venue before/after the show

MODIFY:
- {prompt}

CRITICAL: Output a photorealistic image that looks like THIS EXACT venue photographed when empty. Same camera position, same equipment, same architecture - just no people and with the color/atmosphere changes described above. Maintain 16:9 aspect ratio ({self.width}x{self.height})."""

        # IMPORTANT: modalities=["image", "text"] is REQUIRED for image generation
        response = client.chat.completions.create(
            model=self.MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{ref_b64}",
                            },
                        },
                        {
                            "type": "text",
                            "text": generation_prompt,
                        },
                    ],
                }
            ],
            extra_body={"modalities": ["image", "text"]},
        )

        elapsed = time.time() - start_time
        logger.info(f"Generation complete in {elapsed:.1f}s")

        # Extract image from response
        # Nano Banana Pro returns images in message.images array
        image_data = self._extract_image_from_response(response)

        # Determine output path
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{session_id}_thumbnail.png"
        else:
            # Use temp directory
            temp_dir = Path(tempfile.gettempdir()) / "coolio_visuals"
            temp_dir.mkdir(parents=True, exist_ok=True)
            output_path = temp_dir / f"{session_id}_thumbnail.png"

        # Save image
        with open(output_path, "wb") as f:
            f.write(image_data)

        logger.info(f"Thumbnail saved: {output_path}")
        return output_path

    def _extract_image_from_response(self, response) -> bytes:
        """Extract image data from Nano Banana Pro response.

        Args:
            response: OpenAI-format response from OpenRouter.

        Returns:
            Raw image bytes.

        Raises:
            ValueError: If no image found in response.
        """
        message = response.choices[0].message

        # Primary method: Check message.images (OpenRouter's documented format)
        # Images are returned as: message.images[].image_url.url = "data:image/...;base64,..."
        if hasattr(message, "images") and message.images:
            image_obj = message.images[0]
            # Handle both object and dict formats
            if hasattr(image_obj, "image_url"):
                url = image_obj.image_url.url
            elif isinstance(image_obj, dict):
                url = image_obj.get("image_url", {}).get("url", "")
            else:
                url = ""

            if url and url.startswith("data:image"):
                # Extract base64 data after the comma
                b64_data = url.split(",", 1)[1]
                return base64.b64decode(b64_data)

        # Fallback: Check for image in content parts (multimodal response)
        if hasattr(message, "content") and isinstance(message.content, list):
            for part in message.content:
                if isinstance(part, dict):
                    # Check for inline base64 image
                    if part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:image"):
                            b64_data = url.split(",", 1)[1]
                            return base64.b64decode(b64_data)
                    # Check for direct base64 field
                    if "image" in part:
                        return base64.b64decode(part["image"])

        # Fallback: Check if content is a string with base64 data
        content = message.content
        if isinstance(content, str) and content:
            # Look for base64 image pattern
            if "data:image" in content:
                import re
                match = re.search(r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)", content)
                if match:
                    return base64.b64decode(match.group(1))

        # Build detailed error message
        has_images = hasattr(message, "images") and message.images
        raise ValueError(
            f"Could not extract image from response. "
            f"Has images attr: {has_images}, "
            f"Content type: {type(content)}, "
            f"Content preview: {str(content)[:200] if content else 'None'}"
        )
