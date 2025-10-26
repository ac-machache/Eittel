"""
Firestore-based credential store for Google Workspace integrations.

This module provides a Firestore backend for credential storage, enabling
cloud-native, multi-tenant credential management.
"""

import os
import logging
from typing import Optional, List
from datetime import datetime

from google.cloud import firestore
from google.oauth2.credentials import Credentials

from .credential_store import CredentialStore

logger = logging.getLogger(__name__)


class FirestoreCredentialStore(CredentialStore):
    """
    Credential store that uses Google Cloud Firestore for storage.

    This implementation stores OAuth credentials in Firestore, making it suitable
    for cloud deployments with multiple instances and multi-tenant applications.

    Environment Variables:
        FIRESTORE_PROJECT: GCP project ID (required)
        FIRESTORE_DATABASE: Firestore database name (optional, defaults to "(default)")

    Firestore Structure:
        Collection: technico
        Document: {user_id}
        Field: google_oauth_tokens
            {
                "token": "access_token",
                "refresh_token": "refresh_token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "client_id",
                "client_secret": "client_secret",
                "scopes": ["scope1", "scope2"],
                "expiry": "2025-01-15T10:30:00"
            }
    """

    def __init__(self, firestore_project: Optional[str] = None, firestore_database: Optional[str] = None):
        """
        Initialize the Firestore credential store.

        Args:
            firestore_project: GCP project ID. If None, reads from FIRESTORE_PROJECT env var.
            firestore_database: Firestore database name. If None, reads from FIRESTORE_DATABASE
                              env var or defaults to "(default)".

        Raises:
            ValueError: If firestore_project is not provided and FIRESTORE_PROJECT env var is not set.
        """
        # Get project from parameter or environment
        self.project = firestore_project or os.getenv("FIRESTORE_PROJECT")
        if not self.project:
            raise ValueError(
                "Firestore project not configured. "
                "Set FIRESTORE_PROJECT environment variable or pass firestore_project parameter."
            )

        # Get database from parameter, environment, or use default
        self.database = firestore_database or os.getenv("FIRESTORE_DATABASE", "(default)")

        # Collection name (matches your existing structure)
        self.collection_name = "technico"

        # Initialize Firestore client
        try:
            self.db = firestore.Client(
                project=self.project,
                database=self.database,
            )
            logger.info(
                f"Initialized Firestore credential store: "
                f"project={self.project}, database={self.database}, collection={self.collection_name}"
            )
        except Exception as e:
            # Provide context-specific error messages
            error_msg = f"Failed to initialize Firestore client for project={self.project}, database={self.database}"

            error_str = str(e).lower()
            if "permission" in error_str or "forbidden" in error_str or "403" in error_str:
                error_msg += (
                    f": {e}\n"
                    "This appears to be a permissions issue. Please ensure:\n"
                    "  1. The service account has Firestore permissions (roles/datastore.user)\n"
                    "  2. GOOGLE_APPLICATION_CREDENTIALS is set to the correct service account key\n"
                    "  3. The Firestore API is enabled in the GCP project"
                )
            elif "not found" in error_str or "404" in error_str:
                error_msg += (
                    f": {e}\n"
                    f"Project '{self.project}' or database '{self.database}' not found. Please verify:\n"
                    "  1. The project ID is correct\n"
                    "  2. The database exists in the project\n"
                    "  3. You have access to the project"
                )
            elif "credential" in error_str or "auth" in error_str:
                error_msg += (
                    f": {e}\n"
                    "Authentication failed. Please ensure:\n"
                    "  1. GOOGLE_APPLICATION_CREDENTIALS points to a valid service account key file\n"
                    "  2. The service account has not been deleted or disabled\n"
                    "  3. Application Default Credentials are properly configured"
                )
            elif "network" in error_str or "connection" in error_str or "timeout" in error_str:
                error_msg += (
                    f": {e}\n"
                    "Network connectivity issue. Please check:\n"
                    "  1. Internet connectivity is available\n"
                    "  2. Firewall rules allow access to firestore.googleapis.com\n"
                    "  3. The service is not experiencing an outage"
                )
            else:
                error_msg += f": {e}"

            logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg) from e

    def get_credential(self, user_email: str) -> Optional[Credentials]:
        """
        Load OAuth credentials from Firestore for a user.

        Args:
            user_email: User identifier (used as document ID in Firestore)

        Returns:
            Google Credentials object or None if not found or on error
        """
        if not user_email or not user_email.strip():
            logger.warning("get_credential called with empty user_email")
            return None

        try:
            # Get document reference
            doc_ref = self.db.collection(self.collection_name).document(user_email)
            doc = doc_ref.get()

            # Check if document exists
            if not doc.exists:
                logger.debug(f"No Firestore document found for user: {user_email}")
                return None

            # Get document data
            data = doc.to_dict()
            if not data:
                logger.debug(f"Firestore document exists but is empty for user: {user_email}")
                return None

            # Extract token data from google_oauth_tokens field
            token_data = data.get("google_oauth_tokens")
            if not token_data:
                logger.debug(f"No google_oauth_tokens field found for user: {user_email}")
                return None

            # Validate token data structure
            if not isinstance(token_data, dict):
                logger.warning(
                    f"Invalid token data type for user {user_email}: "
                    f"expected dict, got {type(token_data).__name__}"
                )
                return None

            # Convert token data to Credentials object
            credentials = self._token_data_to_credentials(token_data)

            if credentials:
                logger.info(
                    f"Loaded OAuth credentials from Firestore for user: {user_email} "
                    f"(expired={credentials.expired})"
                )
            else:
                logger.warning(f"Failed to convert token data to credentials for user: {user_email}")

            return credentials

        except Exception as e:
            error_str = str(e).lower()

            # Provide context-specific error messages for common issues
            if "permission" in error_str or "forbidden" in error_str:
                logger.error(
                    f"Permission denied when loading credentials for user {user_email}: {e}. "
                    f"Check Firestore IAM permissions.",
                    exc_info=True,
                )
            elif "timeout" in error_str or "deadline" in error_str:
                logger.error(
                    f"Timeout loading credentials for user {user_email}: {e}. "
                    f"Firestore may be experiencing latency issues.",
                    exc_info=True,
                )
            elif "unavailable" in error_str or "service unavailable" in error_str:
                logger.error(
                    f"Firestore service unavailable when loading credentials for user {user_email}: {e}. "
                    f"This may be a temporary outage.",
                    exc_info=True,
                )
            else:
                logger.error(
                    f"Error loading credentials from Firestore for user {user_email}: {e}",
                    exc_info=True,
                )

            return None

    def store_credential(self, user_email: str, credentials: Credentials) -> bool:
        """
        Save OAuth credentials to Firestore for a user.

        Args:
            user_email: User identifier (used as document ID in Firestore)
            credentials: Google Credentials object to store

        Returns:
            True if successfully stored, False otherwise
        """
        if not user_email or not user_email.strip():
            logger.warning("store_credential called with empty user_email")
            return False

        if not credentials:
            logger.warning(f"store_credential called with None credentials for user: {user_email}")
            return False

        try:
            # Convert Credentials to token data dict
            token_data = self._credentials_to_token_data(credentials)

            # Validate that we have required fields
            if not token_data.get("token"):
                logger.error(f"Cannot store credentials for user {user_email}: missing access token")
                return False

            # Get document reference
            doc_ref = self.db.collection(self.collection_name).document(user_email)

            # Store with merge=True to preserve other fields in the document
            doc_ref.set(
                {
                    "google_oauth_tokens": token_data,
                    "google_oauth_connected_at": datetime.utcnow().isoformat(),
                },
                merge=True,
            )

            logger.info(f"Stored OAuth credentials to Firestore for user: {user_email}")
            return True

        except Exception as e:
            error_str = str(e).lower()

            # Provide context-specific error messages
            if "permission" in error_str or "forbidden" in error_str:
                logger.error(
                    f"Permission denied when storing credentials for user {user_email}: {e}. "
                    f"Check Firestore IAM write permissions.",
                    exc_info=True,
                )
            elif "timeout" in error_str or "deadline" in error_str:
                logger.error(
                    f"Timeout storing credentials for user {user_email}: {e}. "
                    f"Firestore may be experiencing latency issues.",
                    exc_info=True,
                )
            elif "quota" in error_str or "rate limit" in error_str:
                logger.error(
                    f"Quota exceeded when storing credentials for user {user_email}: {e}. "
                    f"Check Firestore quota limits.",
                    exc_info=True,
                )
            else:
                logger.error(
                    f"Error storing credentials to Firestore for user {user_email}: {e}",
                    exc_info=True,
                )

            return False

    def delete_credential(self, user_email: str) -> bool:
        """
        Delete OAuth credentials from Firestore for a user.

        This removes the google_oauth_tokens field from the user's document
        but preserves other fields in the document.

        Args:
            user_email: User identifier (used as document ID in Firestore)

        Returns:
            True if successfully deleted or not found, False on error
        """
        if not user_email or not user_email.strip():
            logger.warning("delete_credential called with empty user_email")
            return False

        try:
            # Get document reference
            doc_ref = self.db.collection(self.collection_name).document(user_email)

            # Check if document exists
            doc = doc_ref.get()
            if not doc.exists:
                logger.debug(f"No document to delete for user: {user_email}")
                return True  # Consider it success if document doesn't exist

            # Remove the google_oauth_tokens field (preserve other fields)
            doc_ref.update(
                {
                    "google_oauth_tokens": firestore.DELETE_FIELD,
                    "google_oauth_connected_at": firestore.DELETE_FIELD,
                }
            )

            logger.info(f"Deleted OAuth credentials from Firestore for user: {user_email}")
            return True

        except Exception as e:
            error_str = str(e).lower()

            # Provide context-specific error messages
            if "permission" in error_str or "forbidden" in error_str:
                logger.error(
                    f"Permission denied when deleting credentials for user {user_email}: {e}. "
                    f"Check Firestore IAM write permissions.",
                    exc_info=True,
                )
            elif "not found" in error_str:
                # Document was deleted between get() and update() calls
                logger.info(f"Document not found when deleting credentials for user {user_email} (already deleted)")
                return True
            else:
                logger.error(
                    f"Error deleting credentials from Firestore for user {user_email}: {e}",
                    exc_info=True,
                )

            return False

    def list_users(self) -> List[str]:
        """
        List all users with stored OAuth credentials in Firestore.

        Returns:
            List of user identifiers (document IDs) that have google_oauth_tokens
        """
        try:
            users = []

            # Query all documents in the collection
            docs = self.db.collection(self.collection_name).stream()

            for doc in docs:
                data = doc.to_dict()
                # Only include users that have the google_oauth_tokens field
                if data and data.get("google_oauth_tokens"):
                    users.append(doc.id)

            logger.info(f"Listed {len(users)} users with OAuth credentials from Firestore")
            return sorted(users)

        except Exception as e:
            logger.error(
                f"Error listing users from Firestore: {e}",
                exc_info=True,
            )
            return []

    def _token_data_to_credentials(self, token_data: dict) -> Optional[Credentials]:
        """
        Convert Firestore token data dictionary to Google Credentials object.

        Args:
            token_data: Dictionary containing token information from Firestore

        Returns:
            Google Credentials object or None if conversion fails
        """
        try:
            # Validate required fields
            token = token_data.get("token")
            if not token:
                logger.warning("Token data missing required 'token' field")
                return None

            # Validate token_uri if present
            token_uri = token_data.get("token_uri", "https://oauth2.googleapis.com/token")
            if not token_uri or not isinstance(token_uri, str):
                logger.warning(f"Invalid token_uri in token data: {token_uri}, using default")
                token_uri = "https://oauth2.googleapis.com/token"

            # Validate and parse scopes
            scopes = token_data.get("scopes", [])
            if not isinstance(scopes, list):
                logger.warning(
                    f"Invalid scopes type in token data: expected list, got {type(scopes).__name__}. "
                    f"Using empty list."
                )
                scopes = []

            # Parse expiry datetime if present
            expiry = None
            expiry_str = token_data.get("expiry")
            if expiry_str:
                try:
                    if isinstance(expiry_str, str):
                        expiry = datetime.fromisoformat(expiry_str)
                        # Ensure timezone-naive datetime for Google auth library compatibility
                        if expiry.tzinfo is not None:
                            expiry = expiry.replace(tzinfo=None)
                    else:
                        logger.warning(
                            f"Invalid expiry type in token data: expected str, got {type(expiry_str).__name__}"
                        )
                except (ValueError, TypeError) as e:
                    logger.warning(f"Could not parse expiry time '{expiry_str}': {e}")

            # Extract other fields with type validation
            refresh_token = token_data.get("refresh_token")
            if refresh_token and not isinstance(refresh_token, str):
                logger.warning(f"Invalid refresh_token type: expected str, got {type(refresh_token).__name__}")
                refresh_token = None

            client_id = token_data.get("client_id")
            if client_id and not isinstance(client_id, str):
                logger.warning(f"Invalid client_id type: expected str, got {type(client_id).__name__}")
                client_id = None

            client_secret = token_data.get("client_secret")
            if client_secret and not isinstance(client_secret, str):
                logger.warning(f"Invalid client_secret type: expected str, got {type(client_secret).__name__}")
                client_secret = None

            # Create Credentials object
            credentials = Credentials(
                token=token,
                refresh_token=refresh_token,
                token_uri=token_uri,
                client_id=client_id,
                client_secret=client_secret,
                scopes=scopes,
                expiry=expiry,
            )

            return credentials

        except Exception as e:
            logger.error(
                f"Error converting token data to Credentials: {e}. "
                f"Token data keys: {list(token_data.keys()) if isinstance(token_data, dict) else 'not a dict'}",
                exc_info=True,
            )
            return None

    def _credentials_to_token_data(self, credentials: Credentials) -> dict:
        """
        Convert Google Credentials object to Firestore token data dictionary.

        Args:
            credentials: Google Credentials object

        Returns:
            Dictionary containing token information for Firestore storage
        """
        return {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes or [],
            "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
        }
