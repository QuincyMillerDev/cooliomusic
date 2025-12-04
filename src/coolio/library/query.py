import logging
from datetime import datetime, timedelta
from typing import List, Optional

from coolio.library.metadata import TrackMetadata
from coolio.library.storage import R2Storage

logger = logging.getLogger(__name__)


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
            # List all JSON files in the tracks directory
            objects = self.storage.list_objects(prefix=prefix, max_keys=1000)
            json_keys = [obj["Key"] for obj in objects if obj["Key"].endswith(".json")]
        except Exception as e:
            logger.error(f"Failed to list library objects: {e}")
            return []

        candidates = []
        cutoff_date = datetime.now() - timedelta(days=exclude_days)

        for key in json_keys:
            try:
                data = self.storage.read_json(key)
                track = TrackMetadata.from_dict(data)

                # Recency Check - skip recently used tracks
                if track.last_used_at and track.last_used_at > cutoff_date:
                    logger.debug(f"Skipping track {track.track_id} (used {track.last_used_at})")
                    continue

                candidates.append(track)
            except Exception as e:
                logger.warning(f"Failed to process track metadata at {key}: {e}")
                continue

        logger.info(f"Found {len(candidates)} candidate tracks after filtering.")
        return candidates

