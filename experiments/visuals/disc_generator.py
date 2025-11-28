"""Coolio disc artwork generator.

Generates a distinctive vinyl disc aesthetic:
- Black background
- White disc
- Single bold black graphic element (procedurally varied)
- Brutalist typography with asymmetric placement
- Center hole

The design intentionally differs from the gesus8 style:
- White disc (not solid color)
- Brutalist sans-serif (not gothic blackletter)
- Asymmetric text (not centered vertical stack)
- Bold graphic element (not plain)
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from elements import get_random_element, draw_element, diagonal_line


@dataclass
class DiscConfig:
    """Configuration for disc generation."""

    # Canvas
    canvas_size: int = 1080

    # Disc
    disc_radius: int = 420  # Leaves margin on 1080 canvas
    disc_color: str = "#FFFFFF"

    # Background
    bg_color: str = "#000000"

    # Center hole
    hole_radius: int = 30
    hole_color: str = "#000000"

    # Typography
    brand_text: str = "coolio"
    brand_font_size: int = 72
    date_font_size: int = 28

    # Colors for elements
    element_color: str = "#000000"
    text_color: str = "#000000"


def find_font(
    preferred: list[str], size: int, bold: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Find an available font from the preferred list.

    Args:
        preferred: List of font names to try in order.
        size: Font size in points.
        bold: Whether to prefer bold variants.

    Returns:
        A PIL font object.
    """
    # Common system font paths on macOS
    font_dirs = [
        Path("/System/Library/Fonts"),
        Path("/Library/Fonts"),
        Path.home() / "Library/Fonts",
        Path(__file__).parent / "fonts",  # Local fonts dir
    ]

    # Map of font names to possible file names
    font_files = {
        "Helvetica Neue": ["HelveticaNeue.ttc", "HelveticaNeue-Bold.ttf"],
        "Helvetica": ["Helvetica.ttc", "Helvetica-Bold.ttf"],
        "Arial": ["Arial.ttf", "Arial Bold.ttf", "Arial Black.ttf"],
        "SF Pro": ["SF-Pro-Display-Bold.otf", "SF-Pro.ttf"],
        "Futura": ["Futura.ttc", "Futura-Bold.ttf"],
        "Impact": ["Impact.ttf"],
    }

    for font_name in preferred:
        if font_name not in font_files:
            continue

        for font_dir in font_dirs:
            if not font_dir.exists():
                continue

            for filename in font_files[font_name]:
                font_path = font_dir / filename
                if font_path.exists():
                    try:
                        return ImageFont.truetype(str(font_path), size)
                    except OSError:
                        continue

    # Fallback to default font
    try:
        return ImageFont.truetype("Arial", size)
    except OSError:
        return ImageFont.load_default()


def generate_disc(
    seed: int,
    date_str: str | None = None,
    config: DiscConfig | None = None,
    element_type: str = "auto",
) -> Image.Image:
    """Generate a coolio disc artwork.

    Args:
        seed: Random seed for procedural element generation.
        date_str: Date string to display (e.g., "28.11.24"). If None, uses today.
        config: Disc configuration. Uses defaults if None.
        element_type: Type of element to use. "auto" for seed-based selection,
                     or "line", "arc", "wedge", "circle" for specific types.

    Returns:
        PIL Image with the generated disc artwork.
    """
    if config is None:
        config = DiscConfig()

    if date_str is None:
        date_str = datetime.now().strftime("%d.%m.%y")

    # Create canvas
    size = config.canvas_size
    img = Image.new("RGB", (size, size), config.bg_color)
    draw = ImageDraw.Draw(img)

    # Calculate disc position (centered)
    center = (size // 2, size // 2)
    disc_bbox = [
        (center[0] - config.disc_radius, center[1] - config.disc_radius),
        (center[0] + config.disc_radius, center[1] + config.disc_radius),
    ]

    # Draw white disc
    draw.ellipse(disc_bbox, fill=config.disc_color)

    # Generate and draw graphic element
    if element_type == "auto":
        element = get_random_element(seed, config.disc_radius, center)
    else:
        # Force specific element type
        from elements import diagonal_line, arc_sweep, wedge, offset_circle

        element_funcs = {
            "line": diagonal_line,
            "arc": arc_sweep,
            "wedge": wedge,
            "circle": offset_circle,
        }
        func = element_funcs.get(element_type, diagonal_line)
        element = func(seed, config.disc_radius, center)

    draw_element(draw, element, config.element_color)

    # Load fonts
    brand_font = find_font(
        ["Helvetica Neue", "Helvetica", "SF Pro", "Futura", "Arial"],
        config.brand_font_size,
        bold=True,
    )
    date_font = find_font(
        ["Helvetica Neue", "Helvetica", "SF Pro", "Arial"],
        config.date_font_size,
    )

    # Draw brand text - asymmetric position (lower-left area of disc)
    # Position relative to disc, not canvas
    brand_x = center[0] - config.disc_radius + 80
    brand_y = center[1] + config.disc_radius // 3

    # Get text bounding box for positioning
    brand_bbox = draw.textbbox((0, 0), config.brand_text, font=brand_font)
    brand_width = brand_bbox[2] - brand_bbox[0]
    brand_height = brand_bbox[3] - brand_bbox[1]

    # Ensure text stays within disc bounds
    max_brand_x = center[0] + config.disc_radius - brand_width - 40
    brand_x = min(brand_x, max_brand_x)

    draw.text(
        (brand_x, brand_y),
        config.brand_text,
        font=brand_font,
        fill=config.text_color,
    )

    # Draw date - bottom-right corner of disc area
    date_bbox = draw.textbbox((0, 0), date_str, font=date_font)
    date_width = date_bbox[2] - date_bbox[0]

    date_x = center[0] + config.disc_radius - date_width - 60
    date_y = center[1] + config.disc_radius - 80

    draw.text(
        (date_x, date_y),
        date_str,
        font=date_font,
        fill=config.text_color,
    )

    # Punch center hole (black)
    hole_bbox = [
        (center[0] - config.hole_radius, center[1] - config.hole_radius),
        (center[0] + config.hole_radius, center[1] + config.hole_radius),
    ]
    draw.ellipse(hole_bbox, fill=config.hole_color)

    return img


def save_disc(
    img: Image.Image,
    output_dir: Path,
    seed: int,
    format: str = "png",
) -> Path:
    """Save a generated disc image.

    Args:
        img: The PIL Image to save.
        output_dir: Directory to save to.
        seed: Seed used (for filename).
        format: Image format (png or jpeg).

    Returns:
        Path to the saved file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"disc_{seed}.{format}"
    output_path = output_dir / filename

    img.save(output_path, format.upper())

    return output_path


if __name__ == "__main__":
    # Quick test
    import sys

    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 12345
    date = sys.argv[2] if len(sys.argv) > 2 else None

    img = generate_disc(seed=seed, date_str=date)
    output_dir = Path(__file__).parent / "output"
    path = save_disc(img, output_dir, seed)
    print(f"Generated: {path}")

