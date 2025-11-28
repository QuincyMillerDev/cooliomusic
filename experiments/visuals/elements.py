"""Procedural graphic elements for coolio disc artwork.

Each function generates a single bold graphic element that varies
per session based on a seed. The elements are drawn in black on
the white disc to create a distinctive, brutalist aesthetic.
"""

import math
import random
from dataclasses import dataclass
from PIL import Image, ImageDraw


@dataclass
class LineElement:
    """A diagonal line element."""

    start: tuple[float, float]
    end: tuple[float, float]
    thickness: int


@dataclass
class ArcElement:
    """A curved arc sweep element."""

    bbox: tuple[float, float, float, float]
    start_angle: float
    end_angle: float
    thickness: int


@dataclass
class WedgeElement:
    """A pie-slice wedge element."""

    center: tuple[float, float]
    radius: float
    start_angle: float
    end_angle: float


@dataclass
class CircleElement:
    """An offset circle element."""

    center: tuple[float, float]
    radius: float
    thickness: int


def diagonal_line(seed: int, disc_radius: int, center: tuple[int, int]) -> LineElement:
    """Generate a diagonal line that spans the disc.

    Args:
        seed: Random seed for deterministic generation.
        disc_radius: Radius of the disc in pixels.
        center: Center point of the disc (x, y).

    Returns:
        LineElement with start, end coordinates and thickness.
    """
    random.seed(seed)

    # Angle from horizontal (15-75 degrees for variety)
    angle_deg = random.uniform(15, 75)
    # Randomly flip to get negative angles too
    if random.random() > 0.5:
        angle_deg = -angle_deg

    angle_rad = math.radians(angle_deg)

    # Line thickness varies with seed
    thickness = random.randint(25, 55)

    # Calculate line that extends beyond disc to ensure full coverage
    # Use 1.5x radius to ensure it spans the entire disc
    length = disc_radius * 1.5

    cx, cy = center
    dx = math.cos(angle_rad) * length
    dy = math.sin(angle_rad) * length

    start = (cx - dx, cy - dy)
    end = (cx + dx, cy + dy)

    return LineElement(start=start, end=end, thickness=thickness)


def arc_sweep(seed: int, disc_radius: int, center: tuple[int, int]) -> ArcElement:
    """Generate a curved arc that sweeps across the disc.

    Args:
        seed: Random seed for deterministic generation.
        disc_radius: Radius of the disc in pixels.
        center: Center point of the disc (x, y).

    Returns:
        ArcElement with bounding box, angles, and thickness.
    """
    random.seed(seed)

    # Arc radius is larger than disc for sweeping effect
    arc_radius = disc_radius * random.uniform(0.8, 1.4)

    # Offset the arc center from disc center
    offset_angle = random.uniform(0, 360)
    offset_dist = disc_radius * random.uniform(0.3, 0.7)
    offset_x = math.cos(math.radians(offset_angle)) * offset_dist
    offset_y = math.sin(math.radians(offset_angle)) * offset_dist

    cx, cy = center
    arc_cx = cx + offset_x
    arc_cy = cy + offset_y

    # Bounding box for the arc
    bbox = (
        arc_cx - arc_radius,
        arc_cy - arc_radius,
        arc_cx + arc_radius,
        arc_cy + arc_radius,
    )

    # Arc sweep angles
    start_angle = random.uniform(0, 180)
    sweep = random.uniform(60, 120)
    end_angle = start_angle + sweep

    thickness = random.randint(20, 50)

    return ArcElement(
        bbox=bbox,
        start_angle=start_angle,
        end_angle=end_angle,
        thickness=thickness,
    )


def wedge(seed: int, disc_radius: int, center: tuple[int, int]) -> WedgeElement:
    """Generate a pie-slice wedge cut through the disc.

    Args:
        seed: Random seed for deterministic generation.
        disc_radius: Radius of the disc in pixels.
        center: Center point of the disc (x, y).

    Returns:
        WedgeElement with center, radius, and angle range.
    """
    random.seed(seed)

    # Wedge starts from a point near the edge
    start_angle = random.uniform(0, 360)

    # Wedge opening angle (15-45 degrees for sharp look)
    opening = random.uniform(15, 45)
    end_angle = start_angle + opening

    return WedgeElement(
        center=center,
        radius=disc_radius * 1.1,  # Slightly larger to cut through
        start_angle=start_angle,
        end_angle=end_angle,
    )


def offset_circle(
    seed: int, disc_radius: int, center: tuple[int, int]
) -> CircleElement:
    """Generate a large circle that intersects the disc edge.

    Args:
        seed: Random seed for deterministic generation.
        disc_radius: Radius of the disc in pixels.
        center: Center point of the disc (x, y).

    Returns:
        CircleElement with offset center, radius, and thickness.
    """
    random.seed(seed)

    # Circle is large and offset from center
    circle_radius = disc_radius * random.uniform(0.4, 0.8)

    # Position the circle so it intersects the disc edge
    offset_angle = random.uniform(0, 360)
    offset_dist = disc_radius * random.uniform(0.4, 0.7)

    cx, cy = center
    circle_cx = cx + math.cos(math.radians(offset_angle)) * offset_dist
    circle_cy = cy + math.sin(math.radians(offset_angle)) * offset_dist

    thickness = random.randint(15, 40)

    return CircleElement(
        center=(circle_cx, circle_cy),
        radius=circle_radius,
        thickness=thickness,
    )


def draw_element(
    draw: ImageDraw.ImageDraw,
    element: LineElement | ArcElement | WedgeElement | CircleElement,
    color: str = "black",
) -> None:
    """Draw an element onto an ImageDraw context.

    Args:
        draw: PIL ImageDraw object.
        element: The element to draw.
        color: Fill/stroke color (default black).
    """
    if isinstance(element, LineElement):
        draw.line(
            [element.start, element.end],
            fill=color,
            width=element.thickness,
        )

    elif isinstance(element, ArcElement):
        draw.arc(
            element.bbox,
            start=element.start_angle,
            end=element.end_angle,
            fill=color,
            width=element.thickness,
        )

    elif isinstance(element, WedgeElement):
        draw.pieslice(
            [
                (element.center[0] - element.radius, element.center[1] - element.radius),
                (element.center[0] + element.radius, element.center[1] + element.radius),
            ],
            start=element.start_angle,
            end=element.end_angle,
            fill=color,
        )

    elif isinstance(element, CircleElement):
        bbox = [
            (element.center[0] - element.radius, element.center[1] - element.radius),
            (element.center[0] + element.radius, element.center[1] + element.radius),
        ]
        draw.ellipse(bbox, outline=color, width=element.thickness)


def get_random_element(
    seed: int, disc_radius: int, center: tuple[int, int]
) -> LineElement | ArcElement | WedgeElement | CircleElement:
    """Get a random element type based on seed.

    For initial implementation, heavily favor diagonal lines as they
    are the most graphic and distinctive. Other elements can be
    enabled once the base system is working.

    Args:
        seed: Random seed.
        disc_radius: Radius of the disc.
        center: Center of the disc.

    Returns:
        A randomly selected element.
    """
    random.seed(seed)

    # For now, mostly use diagonal lines (80% chance)
    # Can adjust weights later for more variety
    choice = random.random()

    if choice < 0.80:
        return diagonal_line(seed, disc_radius, center)
    elif choice < 0.90:
        return arc_sweep(seed, disc_radius, center)
    elif choice < 0.95:
        return wedge(seed, disc_radius, center)
    else:
        return offset_circle(seed, disc_radius, center)

