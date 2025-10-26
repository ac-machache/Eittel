"""
Simple in-memory credential cache for Google OAuth credentials.

This module provides a thread-safe, in-memory cache for Google OAuth credentials
to avoid repeated database/filesystem reads during the same session.
"""

import logging
from typing import Dict, Optional
from threading import RLock
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)


class CredentialCache:
    """
    Thread-safe in-memory cache for Google OAuth credentials.

    This cache stores credentials by user email to provide fast access
    without hitting the persistent storage (file/Firestore) on every call.

    Usage:
        >>> cache = CredentialCache()
        >>> cache.set("user@example.com", credentials)
        >>> creds = cache.get("user@example.com")
    """

    def __init__(self):
        """Initialize the credential cache."""
        self._cache: Dict[str, Credentials] = {}
        self._lock = RLock()
        logger.debug("CredentialCache initialized")

    def get(self, user_email: str) -> Optional[Credentials]:
        """
        Get credentials from cache.

        Args:
            user_email: User's email address

        Returns:
            Credentials if found and valid, None otherwise
        """
        with self._lock:
            creds = self._cache.get(user_email)

            if creds is None:
                logger.debug(f"Cache miss for {user_email}")
                return None

            # Check if credentials are still valid
            if creds.valid:
                logger.debug(f"Cache hit for {user_email} (valid)")
                return creds

            # Check if expired but refreshable
            if creds.expired and creds.refresh_token:
                logger.debug(f"Cache hit for {user_email} (expired but refreshable)")
                return creds

            # Credentials are invalid and not refreshable - remove from cache
            logger.debug(f"Cache hit for {user_email} (invalid, removing)")
            del self._cache[user_email]
            return None

    def set(self, user_email: str, credentials: Credentials) -> None:
        """
        Store credentials in cache.

        Args:
            user_email: User's email address
            credentials: Google OAuth credentials
        """
        with self._lock:
            self._cache[user_email] = credentials
            logger.debug(f"Cached credentials for {user_email}")

    def remove(self, user_email: str) -> bool:
        """
        Remove credentials from cache.

        Args:
            user_email: User's email address

        Returns:
            True if credentials were removed, False if not found
        """
        with self._lock:
            if user_email in self._cache:
                del self._cache[user_email]
                logger.debug(f"Removed cached credentials for {user_email}")
                return True
            return False

    def clear(self) -> None:
        """Clear all cached credentials."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.debug(f"Cleared {count} cached credentials")

    def list_users(self) -> list[str]:
        """
        List all users with cached credentials.

        Returns:
            List of user email addresses
        """
        with self._lock:
            return list(self._cache.keys())


# Global credential cache instance
_global_cache: Optional[CredentialCache] = None


def get_credential_cache() -> CredentialCache:
    """
    Get the global credential cache instance.

    Returns:
        The singleton CredentialCache instance
    """
    global _global_cache
    if _global_cache is None:
        _global_cache = CredentialCache()
    return _global_cache
