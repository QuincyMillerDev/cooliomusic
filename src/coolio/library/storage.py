"""Minimal R2 storage wrapper using boto3."""

import json
import logging
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

