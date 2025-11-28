"""Track metadata for library storage."""

import hashlib
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class TrackMetadata:
    """Metadata for a track stored in the library.

    Designed to support curator agent queries for track reuse and
    DJ-style playlist generation.
    """

    # Identity
    track_id: str
    title: str  # Human-readable name (e.g., "These Things Will Come To Be")

    # Musical attributes
    genre: str
    subgenre: str | None
    bpm: int
    duration_ms: int
    energy: int  # 1-10 scale
    role: str  # intro, build, peak, sustain, cooldown, outro

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

    @classmethod
    def create(
        cls,
        title: str,
        genre: str,
        bpm: int,
        duration_ms: int,
        energy: int,
        role: str,
        provider: str,
        prompt: str,
        session_id: str,
        subgenre: str | None = None,
    ) -> "TrackMetadata":
        """Create a new TrackMetadata with generated ID and timestamps."""
        return cls(
            track_id=str(uuid.uuid4())[:8],
            title=title,
            genre=genre,
            subgenre=subgenre,
            bpm=bpm,
            duration_ms=duration_ms,
            energy=energy,
            role=role,
            provider=provider,
            prompt_hash=hashlib.sha256(prompt.encode()).hexdigest()[:16],
            session_id=session_id,
            created_at=datetime.now(),
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
        """Deserialize from dictionary."""
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

