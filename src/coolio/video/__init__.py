"""Video composition package for Coolio.

Composes final YouTube videos from session assets:
- Video clip (looped for audio duration)
- Mixed audio (from mixer)
"""

from coolio.video.composer import VideoComposer
from coolio.video.metadata import generate_youtube_metadata

__all__ = ["VideoComposer", "generate_youtube_metadata"]
