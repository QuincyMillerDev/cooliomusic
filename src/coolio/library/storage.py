"""Minimal R2 storage wrapper using boto3."""

import json
import logging
import shutil
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from coolio.config import get_settings

logger = logging.getLogger(__name__)


class R2Storage:
    """Thin wrapper around boto3 for Cloudflare R2 operations."""

    def __init__(self) -> None:
        s = get_settings()
        self._client = boto3.client(
            "s3",
            endpoint_url=s.r2_endpoint_url,
            aws_access_key_id=s.r2_access_key_id,
            aws_secret_access_key=s.r2_secret_access_key,
        )
        self._bucket = s.r2_bucket_name

    def upload_file(self, local_path: Path, r2_key: str) -> str:
        """Upload a file to R2.

        Args:
            local_path: Path to the local file.
            r2_key: Destination key in R2 (e.g., "library/tracks/techno/track_abc.mp3").

        Returns:
            The R2 key on success.

        Raises:
            ClientError: If upload fails.
        """
        try:
            self._client.upload_file(str(local_path), self._bucket, r2_key)
            logger.info(f"Uploaded {local_path.name} -> r2://{self._bucket}/{r2_key}")
            return r2_key
        except ClientError as e:
            logger.error(f"Failed to upload {local_path}: {e}")
            raise

    def upload_json(self, data: dict, r2_key: str) -> str:
        """Upload a JSON object to R2.

        Args:
            data: Dictionary to serialize as JSON.
            r2_key: Destination key in R2.

        Returns:
            The R2 key on success.

        Raises:
            ClientError: If upload fails.
        """
        try:
            body = json.dumps(data, indent=2, default=str)
            self._client.put_object(
                Bucket=self._bucket,
                Key=r2_key,
                Body=body.encode("utf-8"),
                ContentType="application/json",
            )
            logger.info(f"Uploaded JSON -> r2://{self._bucket}/{r2_key}")
            return r2_key
        except ClientError as e:
            logger.error(f"Failed to upload JSON to {r2_key}: {e}")
            raise

    def read_json(self, r2_key: str) -> dict:
        """Read a JSON object directly from R2.

        Args:
            r2_key: Key to read.

        Returns:
            Dictionary containing the JSON data.

        Raises:
            ClientError: If read fails.
        """
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=r2_key)
            content = response["Body"].read().decode("utf-8")
            return json.loads(content)
        except ClientError as e:
            logger.error(f"Failed to read JSON from {r2_key}: {e}")
            raise

    def list_objects(self, prefix: str = "", max_keys: int = 100) -> list[dict]:
        """List objects in R2 with optional prefix filter.

        Args:
            prefix: Key prefix to filter by (e.g., "library/tracks/").
            max_keys: Maximum number of keys to return.

        Returns:
            List of object metadata dicts with 'Key', 'Size', 'LastModified'.
        """
        try:
            response = self._client.list_objects_v2(
                Bucket=self._bucket,
                Prefix=prefix,
                MaxKeys=max_keys,
            )
            return response.get("Contents", [])
        except ClientError as e:
            logger.error(f"Failed to list objects with prefix '{prefix}': {e}")
            raise

    def download_file(self, r2_key: str, local_path: Path) -> Path:
        """Download a file from R2.

        Args:
            r2_key: Source key in R2.
            local_path: Local destination path.

        Returns:
            The local path on success.

        Raises:
            ClientError: If download fails.
        """
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            self._client.download_file(self._bucket, r2_key, str(local_path))
            logger.info(f"Downloaded r2://{self._bucket}/{r2_key} -> {local_path}")
            return local_path
        except ClientError as e:
            logger.error(f"Failed to download {r2_key}: {e}")
            raise

    def exists(self, r2_key: str) -> bool:
        """Check if an object exists in R2.

        Args:
            r2_key: Key to check.

        Returns:
            True if object exists, False otherwise.
        """
        try:
            self._client.head_object(Bucket=self._bucket, Key=r2_key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    def upload_image(self, local_path: Path, session_id: str) -> str:
        """Upload a session thumbnail image to R2.

        Args:
            local_path: Path to the local image file (PNG).
            session_id: Session identifier for organizing storage.

        Returns:
            The R2 key on success (sessions/{session_id}/thumbnail.png).

        Raises:
            ClientError: If upload fails.
        """
        r2_key = f"sessions/{session_id}/thumbnail.png"

        # Determine content type from extension
        suffix = local_path.suffix.lower()
        content_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(suffix, "application/octet-stream")

        try:
            with open(local_path, "rb") as f:
                self._client.put_object(
                    Bucket=self._bucket,
                    Key=r2_key,
                    Body=f,
                    ContentType=content_type,
                )
            logger.info(f"Uploaded {local_path.name} -> r2://{self._bucket}/{r2_key}")
            return r2_key
        except ClientError as e:
            logger.error(f"Failed to upload image {local_path}: {e}")
            raise

    def download_thumbnail(self, session_id: str, dest_dir: Path) -> Path | None:
        """Download a session thumbnail from R2 if it exists.

        Args:
            session_id: Session identifier.
            dest_dir: Local directory to save the thumbnail.

        Returns:
            Path to downloaded thumbnail, or None if not found in R2.
        """
        r2_key = f"sessions/{session_id}/thumbnail.png"

        if not self.exists(r2_key):
            logger.info(f"No thumbnail found in R2 for session {session_id}")
            return None

        dest_dir.mkdir(parents=True, exist_ok=True)
        local_path = dest_dir / f"{session_id}_thumbnail.png"

        try:
            self.download_file(r2_key, local_path)
            return local_path
        except ClientError as e:
            logger.error(f"Failed to download thumbnail for {session_id}: {e}")
            return None

    # -------------------------------------------------------------------------
    # Session Storage Methods
    # -------------------------------------------------------------------------

    def upload_session_metadata(self, session_data: dict, session_id: str) -> str:
        """Upload session metadata to R2.

        Args:
            session_data: Session metadata dictionary.
            session_id: Session identifier.

        Returns:
            The R2 key on success (sessions/{session_id}/session.json).
        """
        r2_key = f"sessions/{session_id}/session.json"
        return self.upload_json(session_data, r2_key)

    def upload_final_mix(
        self,
        mix_path: Path,
        tracklist_path: Path | None,
        session_id: str,
    ) -> dict[str, str]:
        """Upload final mix audio and tracklist to R2.

        Args:
            mix_path: Path to the final_mix.mp3 file.
            tracklist_path: Optional path to tracklist.txt.
            session_id: Session identifier.

        Returns:
            Dict with 'mix_key' and optionally 'tracklist_key'.
        """
        result: dict[str, str] = {}

        # Upload the mix audio
        mix_key = f"sessions/{session_id}/audio/final_mix.mp3"
        try:
            with open(mix_path, "rb") as f:
                self._client.put_object(
                    Bucket=self._bucket,
                    Key=mix_key,
                    Body=f,
                    ContentType="audio/mpeg",
                )
            logger.info(f"Uploaded final mix -> r2://{self._bucket}/{mix_key}")
            result["mix_key"] = mix_key
        except ClientError as e:
            logger.error(f"Failed to upload final mix: {e}")
            raise

        # Upload tracklist if provided
        if tracklist_path and tracklist_path.exists():
            tracklist_key = f"sessions/{session_id}/audio/tracklist.txt"
            try:
                with open(tracklist_path, "rb") as f:
                    self._client.put_object(
                        Bucket=self._bucket,
                        Key=tracklist_key,
                        Body=f,
                        ContentType="text/plain",
                    )
                logger.info(f"Uploaded tracklist -> r2://{self._bucket}/{tracklist_key}")
                result["tracklist_key"] = tracklist_key
            except ClientError as e:
                logger.warning(f"Failed to upload tracklist: {e}")

        return result

    def download_session_tracks(
        self,
        track_ids: list[str],
        genre: str,
        dest_dir: Path,
    ) -> list[Path]:
        """Download library tracks to a local directory.

        Args:
            track_ids: List of track IDs to download.
            genre: Genre folder in library.
            dest_dir: Local destination directory.

        Returns:
            List of downloaded file paths.
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[Path] = []

        for track_id in track_ids:
            r2_key = f"library/tracks/{genre}/{track_id}.mp3"
            local_path = dest_dir / f"{track_id}.mp3"

            try:
                self.download_file(r2_key, local_path)
                downloaded.append(local_path)
            except ClientError as e:
                logger.error(f"Failed to download track {track_id}: {e}")

        return downloaded

    def list_sessions(self, max_keys: int = 100) -> list[str]:
        """List all session IDs in R2.

        Returns:
            List of session IDs.
        """
        prefix = "sessions/"
        objects = self.list_objects(prefix=prefix, max_keys=max_keys)

        # Extract unique session IDs from keys like "sessions/session_XXX/..."
        session_ids: set[str] = set()
        for obj in objects:
            key = obj["Key"]
            parts = key.split("/")
            if len(parts) >= 2:
                session_ids.add(parts[1])

        return sorted(session_ids)

    def get_session_metadata(self, session_id: str) -> dict | None:
        """Get session metadata from R2.

        Args:
            session_id: Session identifier.

        Returns:
            Session metadata dict, or None if not found.
        """
        r2_key = f"sessions/{session_id}/session.json"
        try:
            return self.read_json(r2_key)
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise

    def upload_video(
        self,
        video_path: Path,
        session_id: str,
    ) -> str:
        """Upload final video to R2.

        Args:
            video_path: Path to the final video file (MP4).
            session_id: Session identifier.

        Returns:
            The R2 key on success (sessions/{session_id}/video/final_video.mp4).

        Raises:
            ClientError: If upload fails.
        """
        r2_key = f"sessions/{session_id}/video/final_video.mp4"

        try:
            with open(video_path, "rb") as f:
                self._client.put_object(
                    Bucket=self._bucket,
                    Key=r2_key,
                    Body=f,
                    ContentType="video/mp4",
                )
            logger.info(f"Uploaded video -> r2://{self._bucket}/{r2_key}")
            return r2_key
        except ClientError as e:
            logger.error(f"Failed to upload video: {e}")
            raise

    @staticmethod
    def delete_local_session(session_dir: Path) -> bool:
        """Delete a local session directory after successful R2 upload.

        Args:
            session_dir: Path to the session directory.

        Returns:
            True if deleted successfully, False otherwise.
        """
        try:
            if session_dir.exists() and session_dir.is_dir():
                shutil.rmtree(session_dir)
                logger.info(f"Deleted local session: {session_dir}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete local session {session_dir}: {e}")
            return False

