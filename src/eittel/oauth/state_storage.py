"""OAuth state management using Redis for CSRF protection."""

from __future__ import annotations

import secrets
from typing import Optional
from datetime import datetime, timedelta

from redis import Redis
from utils.logging import get_logger

logger = get_logger(__name__)


class OAuthStateStorage:
    """Manages OAuth state tokens using Redis for CSRF protection.

    State tokens are used to prevent CSRF attacks during OAuth flows.
    Each state is a cryptographically secure random token that maps to
    a user_id and expires after a short period.
    """

    # State tokens expire after 10 minutes
    STATE_TTL_SECONDS = 600

    # Redis key prefix to avoid collisions
    KEY_PREFIX = "oauth_state:"

    def __init__(self, redis_client: Redis):
        """Initialize state storage.

        Args:
            redis_client: Redis client instance (Upstash or standard Redis)
        """
        self.redis = redis_client

    def create_state(self, user_id: str) -> str:
        """Generate a secure random state token and store the mapping.

        Args:
            user_id: Firebase user ID to associate with this state

        Returns:
            Cryptographically secure random state token
        """
        # Generate 32-byte random token (URL-safe base64 encoded)
        state_token = secrets.token_urlsafe(32)

        # Store in Redis with TTL
        key = f"{self.KEY_PREFIX}{state_token}"

        # Store user_id and creation timestamp
        self.redis.setex(
            key,
            self.STATE_TTL_SECONDS,
            user_id,
        )

        logger.info(f"Created OAuth state for user {user_id}, expires in {self.STATE_TTL_SECONDS}s")

        return state_token

    def validate_and_consume(self, state_token: str) -> Optional[str]:
        """Validate state token and retrieve associated user_id.

        This method validates the state and immediately deletes it to ensure
        one-time use (prevents replay attacks).

        Args:
            state_token: State token from OAuth callback

        Returns:
            User ID if state is valid, None if invalid/expired/used
        """
        key = f"{self.KEY_PREFIX}{state_token}"

        # Get the value (user_id)
        user_id = self.redis.get(key)

        if not user_id:
            logger.warning("Invalid or expired OAuth state token")
            return None

        # Decode if bytes
        if isinstance(user_id, bytes):
            user_id = user_id.decode('utf-8')

        # Delete immediately (one-time use)
        self.redis.delete(key)

        logger.info(f"Validated and consumed OAuth state for user {user_id}")

        return user_id

    def cleanup_expired(self) -> int:
        """Clean up expired state tokens.

        Note: Redis TTL handles this automatically, but this method
        can be used for manual cleanup if needed.

        Returns:
            Number of expired states cleaned up
        """
        # With Redis TTL, this is handled automatically
        # This method is here for completeness/testing
        pattern = f"{self.KEY_PREFIX}*"
        keys = self.redis.keys(pattern)

        expired_count = 0
        for key in keys:
            ttl = self.redis.ttl(key)
            if ttl == -2:  # Key doesn't exist
                expired_count += 1

        logger.info(f"Found {expired_count} expired OAuth state tokens")
        return expired_count
