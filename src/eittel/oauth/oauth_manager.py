"""OAuth2 token management for Google APIs."""

from __future__ import annotations

import json
import os
from typing import Any, Optional
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import logging

logger = logging.getLogger(__name__)


class GoogleOAuthManager:
    """Manages OAuth2 authentication and token refresh for Google APIs."""
    
    # Required scopes for Calendar and Gmail
    SCOPES = [
        'https://www.googleapis.com/auth/calendar',
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.modify',
    ]
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ):
        """Initialize OAuth manager.
        
        Args:
            client_id: Google OAuth2 client ID
            client_secret: Google OAuth2 client secret
            redirect_uri: OAuth2 redirect URI (e.g., https://your-app.com/auth/callback)
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
    
    def create_authorization_url(self, user_id: str) -> tuple[str, str]:
        """Create OAuth2 authorization URL.
        
        Args:
            user_id: User identifier to pass as state
            
        Returns:
            Tuple of (authorization_url, state)
        """
        flow = Flow.from_client_config(
            client_config={
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.redirect_uri],
                }
            },
            scopes=self.SCOPES,
        )
        flow.redirect_uri = self.redirect_uri
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',  # Get refresh token
            include_granted_scopes='true',
            prompt='consent',  # Force consent to get refresh token
            state=user_id,  # Pass user_id as state
        )
        
        return authorization_url, state
    
    def exchange_code_for_tokens(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for tokens.
        
        Args:
            code: Authorization code from OAuth callback
            
        Returns:
            Dictionary containing token information
        """
        flow = Flow.from_client_config(
            client_config={
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.redirect_uri],
                }
            },
            scopes=self.SCOPES,
        )
        flow.redirect_uri = self.redirect_uri
        
        flow.fetch_token(code=code)
        
        credentials = flow.credentials
        
        return {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes,
            "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
        }
    
    def credentials_from_dict(self, token_data: dict[str, Any]) -> Credentials:
        """Create Credentials object from stored token data.
        
        Args:
            token_data: Dictionary containing token information
            
        Returns:
            Google Credentials object
        """
        expiry = None
        if token_data.get("expiry"):
            try:
                expiry = datetime.fromisoformat(token_data["expiry"])
            except (ValueError, TypeError):
                pass
        
        return Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes", self.SCOPES),
            expiry=expiry,  # ← FIX: Pass the expiry to detect expired tokens!
        )
    
    def refresh_credentials(self, credentials: Credentials) -> dict[str, Any]:
        """Refresh expired credentials.
        
        Args:
            credentials: Google Credentials object
            
        Returns:
            Updated token data dictionary
        """
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        
        return {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes,
            "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
        }
    
    def get_calendar_service(self, credentials: Credentials):
        """Build Google Calendar API service.
        
        Args:
            credentials: Google Credentials object
            
        Returns:
            Google Calendar API service
        """
        return build('calendar', 'v3', credentials=credentials)
    
    def get_gmail_service(self, credentials: Credentials):
        """Build Gmail API service.
        
        Args:
            credentials: Google Credentials object
            
        Returns:
            Gmail API service
        """
        return build('gmail', 'v1', credentials=credentials)


class FirestoreTokenStorage:
    """Store and retrieve OAuth tokens in Firestore (sync client).

    Uses environment variables for configuration to ensure consistency
    with FirestoreCredentialStore:
    - FIRESTORE_COLLECTION: Collection name (default: "technico")
    - FIRESTORE_TOKEN_FIELD: Token field name (default: "google_oauth_tokens")
    """

    def __init__(self, firestore_client):
        """Initialize token storage.

        Args:
            firestore_client: Firestore client instance
        """
        self.db = firestore_client

        # Read from same env vars as FirestoreCredentialStore for consistency
        self.collection_name = os.getenv("FIRESTORE_COLLECTION", "technico")
        self.token_field = os.getenv("FIRESTORE_TOKEN_FIELD", "google_oauth_tokens")

        logger.info(
            f"Initialized FirestoreTokenStorage: "
            f"collection={self.collection_name}, token_field={self.token_field}"
        )

    def store_tokens(self, user_id: str, token_data: dict[str, Any]) -> None:
        """Store user's OAuth tokens in Firestore."""
        doc_ref = self.db.collection(self.collection_name).document(user_id)
        doc_ref.set(
            {
                self.token_field: token_data,
                'google_oauth_connected_at': datetime.utcnow().isoformat(),
            },
            merge=True,
        )
        logger.info(f"Stored OAuth tokens for user {user_id} in {self.collection_name}/{user_id}/{self.token_field}")

    def get_tokens(self, user_id: str) -> Optional[dict[str, Any]]:
        """Retrieve user's OAuth tokens from Firestore."""
        doc_ref = self.db.collection(self.collection_name).document(user_id)
        doc_snapshot = doc_ref.get()
        if not doc_snapshot.exists:
            logger.warning(f"No user document found for {user_id} in {self.collection_name}")
            return None
        data = doc_snapshot.to_dict()
        return data.get(self.token_field)

    def delete_tokens(self, user_id: str) -> None:
        """Delete user's OAuth tokens from Firestore."""
        doc_ref = self.db.collection(self.collection_name).document(user_id)
        doc_ref.update(
            {
                self.token_field: None,
                'google_oauth_connected_at': None,
            }
        )
        logger.info(f"Deleted OAuth tokens for user {user_id} from {self.collection_name}/{user_id}/{self.token_field}")
