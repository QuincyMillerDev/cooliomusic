import logging
from datetime import datetime, timedelta
from typing import List, Optional

from coolio.library.metadata import TrackMetadata
from coolio.library.storage import R2Storage

logger = logging.getLogger(__name__)

# Keep the planner prompt bounded even if the library grows large.
# We still scan the whole library so recency exclusion has full visibility,
# then return a capped set of best candidates for the planner to consider.
_MAX_CANDIDATES_FOR_PLANNER = 200


class LibraryQuery:
    """Handles querying and filtering tracks from the R2 library."""

    def __init__(self, storage: Optional[R2Storage] = None):
        self.storage = storage or R2Storage()

    def query_tracks(self, exclude_days: int = 7) -> List[TrackMetadata]:
        """Query all tracks from the library.

        Args:
            exclude_days: Number of days to exclude recently used tracks.

        Returns:
            List of candidate TrackMetadata objects.
        """
        prefix = "library/tracks/"
        logger.info(f"Querying library for all tracks (prefix: {prefix})...")

        try:
            # List all JSON files in the tracks directory (paginated).
            json_keys: list[str] = []
            for obj in self.storage.iter_objects(prefix=prefix):
                key = obj.get("Key")
                if key and key.endswith(".json"):
                    json_keys.append(key)
        except Exception as e:
            logger.error(f"Failed to list library objects: {e}")
            return []

        candidates: list[TrackMetadata] = []
        cutoff_date = datetime.now() - timedelta(days=exclude_days)

        for key in json_keys:
            try:
                data = self.storage.read_json(key)
                track = TrackMetadata.from_dict(data)

                # PROVIDER FILTER: Only return ElevenLabs tracks for reuse.
                # Rationale: ElevenLabs tracks cost more to generate (~$0.30/min),
                # so reusing them maximizes cost savings. Stable Audio tracks are
                # cheap ($0.20 flat) so we prefer to generate fresh ones.
                # The LLM planner only sees ElevenLabs candidates.
                if track.provider != "elevenlabs":
                    continue

                # Recency Check - skip recently used tracks
                if track.last_used_at and track.last_used_at > cutoff_date:
                    logger.debug(f"Skipping track {track.track_id} (used {track.last_used_at})")
                    continue

                candidates.append(track)
            except Exception as e:
                logger.warning(f"Failed to process track metadata at {key}: {e}")
                continue

        total = len(candidates)

        # Prefer tracks that have never been used, then least-recently-used.
        # This reduces repetition across sessions while staying simple.
        candidates.sort(
            key=lambda t: (
                t.last_used_at is not None,
                t.last_used_at or datetime.min,
                t.created_at,
            )
        )

        if total > _MAX_CANDIDATES_FOR_PLANNER:
            candidates = candidates[:_MAX_CANDIDATES_FOR_PLANNER]

        logger.info(
            f"Found {total} ElevenLabs tracks available for reuse "
            f"(returning {len(candidates)} for planner)"
        )
        return candidates

