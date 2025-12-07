"""Visual generation package for Coolio.

Generates thumbnail images for YouTube videos using Gemini via OpenRouter.
Generates looping video clips using Kling AI image-to-video.
"""

from coolio.visuals.generator import VisualGenerator
from coolio.visuals.klingai import KlingAIVideoGenerator
from coolio.visuals.prompts import generate_video_motion_prompt, generate_visual_prompt

__all__ = [
    "VisualGenerator",
    "KlingAIVideoGenerator",
    "generate_visual_prompt",
    "generate_video_motion_prompt",
]

