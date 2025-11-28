#!/usr/bin/env python3
"""CLI for testing coolio disc generation.

Usage:
    python test_disc.py --seed 12345 --date "28.11.24"
    python test_disc.py --batch 10  # Generate 10 variants
    python test_disc.py --element line --seed 42
"""

import argparse
import random
import sys
from datetime import datetime
from pathlib import Path

# Add parent to path for imports when running directly
sys.path.insert(0, str(Path(__file__).parent))

from disc_generator import DiscConfig, generate_disc, save_disc


def main():
    parser = argparse.ArgumentParser(
        description="Generate coolio disc artwork for testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_disc.py --seed 12345
  python test_disc.py --seed 42 --date "28.11.24"
  python test_disc.py --batch 5
  python test_disc.py --element line --seed 100
  python test_disc.py --element arc --batch 3
        """,
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible generation (default: random)",
    )

    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help='Date string to display (default: today, format: "DD.MM.YY")',
    )

    parser.add_argument(
        "--batch",
        type=int,
        default=1,
        help="Generate multiple variants with different seeds",
    )

    parser.add_argument(
        "--element",
        type=str,
        choices=["auto", "line", "arc", "wedge", "circle"],
        default="auto",
        help="Force specific element type (default: auto based on seed)",
    )

    parser.add_argument(
        "--size",
        type=int,
        default=1080,
        help="Canvas size in pixels (default: 1080)",
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output directory (default: experiments/visuals/output)",
    )

    parser.add_argument(
        "--format",
        type=str,
        choices=["png", "jpeg"],
        default="png",
        help="Output format (default: png)",
    )

    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the generated image(s) after creation (macOS only)",
    )

    args = parser.parse_args()

    # Determine output directory
    if args.output:
        output_dir = Path(args.output)
    else:
        output_dir = Path(__file__).parent / "output"

    output_dir.mkdir(parents=True, exist_ok=True)

    # Configure
    config = DiscConfig(canvas_size=args.size)

    # Use today's date if not specified
    date_str = args.date
    if date_str is None:
        date_str = datetime.now().strftime("%d.%m.%y")

    # Generate seeds
    if args.batch > 1:
        if args.seed is not None:
            # Use seed as starting point for batch
            random.seed(args.seed)
        seeds = [random.randint(1, 999999) for _ in range(args.batch)]
    else:
        seeds = [args.seed if args.seed is not None else random.randint(1, 999999)]

    # Generate images
    generated = []
    for seed in seeds:
        print(f"Generating disc with seed {seed}...")

        img = generate_disc(
            seed=seed,
            date_str=date_str,
            config=config,
            element_type=args.element,
        )

        path = save_disc(img, output_dir, seed, args.format)
        generated.append(path)
        print(f"  Saved: {path}")

    # Summary
    print(f"\nGenerated {len(generated)} disc(s) in {output_dir}")

    # Open images if requested (macOS)
    if args.open and sys.platform == "darwin":
        import subprocess

        for path in generated:
            subprocess.run(["open", str(path)], check=False)


if __name__ == "__main__":
    main()

