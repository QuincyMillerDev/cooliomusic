"""Video composition package for Coolio.

Composes final YouTube videos from session assets:
- Thumbnail image (from Flux)
- Mixed audio (from mixer)
- Waveform visualization overlay
"""

from coolio.video.composer import VideoComposer
from coolio.video.waveform import generate_waveform_video
from coolio.video.metadata import generate_youtube_metadata

__all__ = ["VideoComposer", "generate_waveform_video", "generate_youtube_metadata"]

