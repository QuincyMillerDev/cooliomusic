"""Visual generation package for Coolio.

Generates thumbnail images for YouTube videos using Flux via fal.ai.
"""

from coolio.visuals.generator import VisualGenerator
from coolio.visuals.prompts import generate_visual_prompt

__all__ = ["VisualGenerator", "generate_visual_prompt"]

