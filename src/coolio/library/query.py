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

    def query_tracks(self, genre: str, exclude_days: int = 7) -> List[TrackMetadata]:
        """Query tracks from the library with hard filters.

        Args:
            genre: Target genre to filter by.
            exclude_days: Number of days to exclude recently used tracks.

        Returns:
            List of candidate TrackMetadata objects.
        """
        prefix = f"library/tracks/{genre}/"
        logger.info(f"Querying library for genre '{genre}' (prefix: {prefix})...")

        try:
            # List all JSON files in the genre directory
            # Note: simplistic listing, might need pagination for large libraries
            objects = self.storage.list_objects(prefix=prefix, max_keys=1000)
            json_keys = [obj["Key"] for obj in objects if obj["Key"].endswith(".json")]
        except Exception as e:
            logger.error(f"Failed to list objects for genre {genre}: {e}")
            return []

        candidates = []
        cutoff_date = datetime.now() - timedelta(days=exclude_days)

        for key in json_keys:
            try:
                data = self.storage.read_json(key)
                track = TrackMetadata.from_dict(data)

                # 1. Genre Check (redundant if using prefix, but good for safety)
                if track.genre != genre:
                    continue

                # 2. Recency Check
                if track.last_used_at and track.last_used_at > cutoff_date:
                    logger.debug(f"Skipping track {track.track_id} (used {track.last_used_at})")
                    continue

                candidates.append(track)
            except Exception as e:
                logger.warning(f"Failed to process track metadata at {key}: {e}")
                continue

        logger.info(f"Found {len(candidates)} candidate tracks for genre '{genre}' after filtering.")
        return candidates

