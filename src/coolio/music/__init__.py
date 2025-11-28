"""Music generation module.

This module provides the music generation pipeline:
- generator: Orchestrates track generation and library reuse
- providers: Music generation providers (ElevenLabs, Stable Audio)
- agent: Backwards-compatible session planning (delegates to Curator)
"""

from coolio.music.generator import MusicGenerator, GenerationSession

__all__ = ["MusicGenerator", "GenerationSession"]
