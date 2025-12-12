"""Track metadata for library storage."""

import hashlib
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class TrackMetadata:
    """Metadata for a track stored in the library.

    Simplified schema focusing on essential track information.
    """

    # Identity
    track_id: str
    title: str  # Human-readable name (e.g., "Recursive Patterns")

    # Musical attributes
    genre: str
    duration_ms: int

    # Generation info
    provider: str  # "elevenlabs" or "stable_audio"
    prompt_hash: str  # SHA256 of the prompt for deduplication
    session_id: str  # Which session created this track

    # Timestamps for curator agent filtering
    created_at: datetime
    last_used_at: datetime | None = None
    usage_count: int = 0

    # R2 storage keys (populated after upload)
    audio_key: str | None = None
    metadata_key: str | None = None
    
    # Optional: keep BPM for informational use (not planning)
    bpm: int | None = None

    @classmethod
    def create(
        cls,
        title: str,
        genre: str,
        duration_ms: int,
        provider: str,
        prompt: str,
        session_id: str,
        bpm: int | None = None,
    ) -> "TrackMetadata":
        """Create a new TrackMetadata with generated ID and timestamps."""
        return cls(
            track_id=str(uuid.uuid4())[:8],
            title=title,
            genre=genre,
            duration_ms=duration_ms,
            provider=provider,
            prompt_hash=hashlib.sha256(prompt.encode()).hexdigest()[:16],
            session_id=session_id,
            created_at=datetime.now(),
            bpm=bpm,
        )

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        data = asdict(self)
        # Convert datetime to ISO format strings
        data["created_at"] = self.created_at.isoformat()
        if self.last_used_at:
            data["last_used_at"] = self.last_used_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "TrackMetadata":
        """Deserialize from dictionary.

        Includes defensive defaults for optional fields to handle
        older tracks in R2 that may have deprecated fields.
        """
        # Defensive defaults for optional fields
        data.setdefault("last_used_at", None)
        data.setdefault("usage_count", 0)
        data.setdefault("audio_key", None)
        data.setdefault("metadata_key", None)
        data.setdefault("bpm", None)
        
        # Remove deprecated fields from old schema
        data.pop("subgenre", None)
        data.pop("energy", None)
        data.pop("role", None)

        # Convert ISO strings back to datetime
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        if data.get("last_used_at"):
            data["last_used_at"] = datetime.fromisoformat(data["last_used_at"])

        return cls(**data)

    def mark_used(self) -> None:
        """Update usage tracking when track is reused."""
        self.last_used_at = datetime.now()
        self.usage_count += 1

    def r2_audio_key(self) -> str:
        """Generate the R2 key for the audio file."""
        return f"library/tracks/{self.genre}/{self.track_id}.mp3"

    def r2_metadata_key(self) -> str:
        """Generate the R2 key for the metadata JSON."""
        return f"library/tracks/{self.genre}/{self.track_id}.json"

