"""Agents module for AI-driven music curation and generation.

The system uses a Curator agent that plans sessions by mixing library
tracks with new generation requests. It always runs first in the pipeline.
"""

from coolio.agents.curator import generate_curation_plan
from coolio.models import SessionPlan, TrackSlot

# Backwards compatibility aliases
CurationPlan = SessionPlan
CurationSlot = TrackSlot

__all__ = [
    "SessionPlan",
    "TrackSlot",
    "generate_curation_plan",
    # Backwards compatibility
    "CurationPlan",
    "CurationSlot",
]
