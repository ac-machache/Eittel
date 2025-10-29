"""Secure OAuth2 routes for Google Calendar and Gmail integration.

This module implements OAuth2 flow with proper CSRF protection using:
- Firebase Authentication for user verification
- Redis-based state storage for CSRF protection
- Token refresh and revocation
- Secure token storage in Firestore
"""

from __future__ import annotations

import os
import logging
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from google.cloud import firestore
from redis import Redis

from oauth.oauth_manager import (
    GoogleOAuthManager,
    FirestoreTokenStorage,
)
from oauth.firebase_auth import verify_firebase_token
from oauth.state_storage import OAuthStateStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/google", tags=["Google OAuth"])


# Environment variables - Load once at module level
UPSTASH_REDIS_URL = os.getenv("UPSTASH_REDIS_URL")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")
FRONTEND_URL = os.getenv("FRONTEND_URL")
FIRESTORE_PROJECT = os.getenv("FIRESTORE_PROJECT")
FIRESTORE_DATABASE = os.getenv("FIRESTORE_DATABASE", "(default)")


# Initialize Redis client for state storage (using native Redis protocol)
def get_redis_client() -> Redis:
    """Get Redis client for OAuth state storage.

    Uses Upstash Redis with native Redis protocol (not REST API).
    """
    if not UPSTASH_REDIS_URL:
        raise ValueError("UPSTASH_REDIS_URL environment variable not set")

    return Redis.from_url(
        UPSTASH_REDIS_URL,
        decode_responses=False,  # We'll handle decoding
    )


def get_oauth_manager() -> GoogleOAuthManager:
    """Get configured OAuth manager instance."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
        raise ValueError(
            "Missing required OAuth environment variables: "
            "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI"
        )

    return GoogleOAuthManager(
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        redirect_uri=GOOGLE_REDIRECT_URI,
    )


def get_state_storage() -> OAuthStateStorage:
    """Get OAuth state storage instance."""
    redis_client = get_redis_client()
    return OAuthStateStorage(redis_client)


def get_firestore_client() -> firestore.Client:
    """Get Firestore client instance."""
    if not FIRESTORE_PROJECT:
        raise ValueError("FIRESTORE_PROJECT environment variable not set")

    return firestore.Client(
        project=FIRESTORE_PROJECT,
        database=FIRESTORE_DATABASE,
    )


def get_token_storage(db: firestore.Client = Depends(get_firestore_client)) -> FirestoreTokenStorage:
    """Get Firestore token storage instance."""
    return FirestoreTokenStorage(db)


@router.post("/authorize")
async def authorize(
    user_id: str = Depends(verify_firebase_token),
):
    """Initiate OAuth2 flow for Google Calendar and Gmail.

    This endpoint is protected by Firebase Authentication. The user must
    provide a valid Firebase ID token in the Authorization header.

    Security features:
    - Requires Firebase Authentication (user can only OAuth for themselves)
    - Generates cryptographically secure state token
    - State stored in Redis with 10-minute expiration
    - CSRF protection via state validation in callback

    Request:
        POST /auth/google/authorize
        Headers:
            Authorization: Bearer <firebase_id_token>

    Response:
        {
            "authorization_url": "https://accounts.google.com/o/oauth2/auth?..."
        }

    Frontend should redirect user to the authorization_url:
        window.location.href = response.authorization_url

    Args:
        user_id: Firebase user ID (extracted from verified token)

    Returns:
        JSON with Google authorization URL
    """
    try:
        oauth_manager = get_oauth_manager()
        state_storage = get_state_storage()

        # Generate secure random state and store mapping
        state_token = state_storage.create_state(user_id)

        # Create authorization URL with secure state
        authorization_url, _ = oauth_manager.create_authorization_url(state_token)

        logger.info(f"Generated OAuth authorization URL for user {user_id}")

        return JSONResponse(
            {
                "authorization_url": authorization_url,
                "message": "Redirect user to authorization_url",
            }
        )

    except Exception as e:
        logger.error(f"Failed to create authorization URL: {e}")
        raise HTTPException(status_code=500, detail="Failed to initiate OAuth flow")


@router.get("/callback")
async def oauth_callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str = Query(..., description="State token for CSRF protection"),
    error: str = Query(default=None, description="Error from Google"),
):
    """Handle OAuth2 callback from Google.

    This endpoint receives the authorization code from Google's OAuth server
    and exchanges it for access/refresh tokens. The state parameter is
    validated to prevent CSRF attacks.

    Security features:
    - Validates state token from Redis (CSRF protection)
    - One-time state consumption (prevents replay attacks)
    - State expires after 10 minutes
    - Tokens stored securely in Firestore

    Args:
        code: Authorization code from Google
        state: State token for CSRF validation
        error: Error message if authorization failed

    Returns:
        Redirect to frontend success/error page
    """
    if error:
        logger.error(f"OAuth authorization error from Google: {error}")
        if not FRONTEND_URL:
            raise HTTPException(status_code=500, detail="FRONTEND_URL not configured")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/assistant/google?oauth_error={error}"
        )

    try:
        # Validate and consume state token (CSRF protection)
        state_storage = get_state_storage()
        user_id = state_storage.validate_and_consume(state)

        if not user_id:
            logger.error("Invalid or expired OAuth state token")
            if not FRONTEND_URL:
                raise HTTPException(status_code=500, detail="FRONTEND_URL not configured")
            return RedirectResponse(
                url=f"{FRONTEND_URL}/assistant/google?oauth_error=invalid_state"
            )

        # Exchange authorization code for tokens
        oauth_manager = get_oauth_manager()
        token_data = oauth_manager.exchange_code_for_tokens(code)

        # Store tokens in Firestore
        db = get_firestore_client()
        token_storage = FirestoreTokenStorage(db)
        token_storage.store_tokens(user_id, token_data)

        logger.info(f"Successfully stored OAuth tokens for user {user_id}")

        # Redirect to frontend success page
        if not FRONTEND_URL:
            raise HTTPException(status_code=500, detail="FRONTEND_URL not configured")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/assistant/google?oauth_success=true"
        )

    except Exception as e:
        logger.error(f"Failed to process OAuth callback: {e}", exc_info=True)
        if not FRONTEND_URL:
            raise HTTPException(status_code=500, detail="FRONTEND_URL not configured")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/assistant/google?oauth_error=callback_failed"
        )


@router.get("/status")
async def oauth_status(
    user_id: str = Depends(verify_firebase_token),
):
    """Check if user has connected Google Calendar and Gmail.

    This endpoint is protected by Firebase Authentication.

    Request:
        GET /auth/google/status
        Headers:
            Authorization: Bearer <firebase_id_token>

    Response:
        {
            "connected": true,
            "scopes": ["https://www.googleapis.com/auth/calendar", ...],
            "needs_refresh": false
        }

    Args:
        user_id: Firebase user ID (extracted from verified token)

    Returns:
        JSON with connection status and scope information
    """
    try:
        token_storage = get_token_storage()
        tokens = token_storage.get_tokens(user_id)

        if not tokens:
            return JSONResponse(
                {
                    "connected": False,
                    "scopes": [],
                    "needs_refresh": False,
                }
            )

        # Check if token needs refresh
        oauth_manager = get_oauth_manager()
        credentials = oauth_manager.credentials_from_dict(tokens)
        needs_refresh = credentials.expired if credentials.expiry else False

        return JSONResponse(
            {
                "connected": True,
                "scopes": tokens.get("scopes", []),
                "needs_refresh": needs_refresh,
            }
        )

    except Exception as e:
        logger.error(f"Failed to check OAuth status: {e}")
        raise HTTPException(status_code=500, detail="Failed to check OAuth status")


@router.post("/refresh")
async def refresh_tokens(
    user_id: str = Depends(verify_firebase_token),
):
    """Manually refresh OAuth tokens for the authenticated user.

    This endpoint is protected by Firebase Authentication.
    Typically, token refresh happens automatically when making API calls,
    but this endpoint allows manual refresh if needed.

    Request:
        POST /auth/google/refresh
        Headers:
            Authorization: Bearer <firebase_id_token>

    Response:
        {
            "success": true,
            "message": "Tokens refreshed successfully"
        }

    Args:
        user_id: Firebase user ID (extracted from verified token)

    Returns:
        JSON with refresh status
    """
    try:
        token_storage = get_token_storage()
        tokens = token_storage.get_tokens(user_id)

        if not tokens:
            raise HTTPException(
                status_code=404,
                detail="No OAuth tokens found. Please connect Google first."
            )

        # Refresh credentials
        oauth_manager = get_oauth_manager()
        credentials = oauth_manager.credentials_from_dict(tokens)

        if not credentials.expired:
            return JSONResponse(
                {
                    "success": True,
                    "message": "Tokens are still valid, no refresh needed",
                }
            )

        # Refresh and update tokens
        refreshed_tokens = oauth_manager.refresh_credentials(credentials)
        token_storage.store_tokens(user_id, refreshed_tokens)

        logger.info(f"Successfully refreshed OAuth tokens for user {user_id}")

        return JSONResponse(
            {
                "success": True,
                "message": "Tokens refreshed successfully",
            }
        )

    except Exception as e:
        logger.error(f"Failed to refresh OAuth tokens: {e}")
        raise HTTPException(status_code=500, detail="Failed to refresh tokens")


@router.post("/disconnect")
async def disconnect_oauth(
    user_id: str = Depends(verify_firebase_token),
):
    """Disconnect Google Calendar and Gmail integration.

    This endpoint:
    1. Revokes tokens with Google (if possible)
    2. Removes stored tokens from Firestore

    This endpoint is protected by Firebase Authentication.

    Request:
        POST /auth/google/disconnect
        Headers:
            Authorization: Bearer <firebase_id_token>

    Response:
        {
            "success": true,
            "message": "Google integration disconnected"
        }

    Args:
        user_id: Firebase user ID (extracted from verified token)

    Returns:
        Success message
    """
    try:
        token_storage = get_token_storage()
        tokens = token_storage.get_tokens(user_id)

        # Try to revoke tokens with Google
        if tokens and tokens.get("token"):
            try:
                import requests
                revoke_url = "https://oauth2.googleapis.com/revoke"
                response = requests.post(
                    revoke_url,
                    params={"token": tokens["token"]},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

                if response.status_code == 200:
                    logger.info(f"Successfully revoked Google tokens for user {user_id}")
                else:
                    logger.warning(
                        f"Failed to revoke tokens with Google (status {response.status_code}), "
                        "but will still delete from storage"
                    )
            except Exception as revoke_error:
                logger.warning(
                    f"Failed to revoke tokens with Google: {revoke_error}, "
                    "but will still delete from storage"
                )

        # Delete tokens from Firestore
        token_storage.delete_tokens(user_id)

        logger.info(f"Disconnected Google OAuth for user {user_id}")

        return JSONResponse(
            {
                "success": True,
                "message": "Google integration disconnected",
            }
        )

    except Exception as e:
        logger.error(f"Failed to disconnect OAuth: {e}")
        raise HTTPException(status_code=500, detail="Failed to disconnect")
