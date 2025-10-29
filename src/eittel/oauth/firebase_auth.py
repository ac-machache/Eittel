"""Firebase Authentication verification for OAuth endpoints."""

from __future__ import annotations

from typing import Optional
from fastapi import HTTPException, Header, Depends
from firebase_admin import auth
import logging

logger = logging.getLogger(__name__)


async def verify_firebase_token(
    authorization: Optional[str] = Header(None, description="Firebase ID token")
) -> str:
    """Verify Firebase authentication token and extract user ID.

    This dependency should be used on OAuth endpoints to ensure only
    authenticated users can initiate OAuth flows for their own accounts.

    Args:
        authorization: Authorization header with format "Bearer <token>"

    Returns:
        Firebase user ID (uid) from verified token

    Raises:
        HTTPException: 401 if token is missing, invalid, or expired
    """
    if not authorization:
        logger.warning("Missing Authorization header")
        raise HTTPException(
            status_code=401,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract token from "Bearer <token>" format
    parts = authorization.split()

    if len(parts) != 2 or parts[0].lower() != "bearer":
        logger.warning("Invalid Authorization header format")
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token format. Expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1]

    try:
        # Verify the Firebase ID token
        decoded_token = auth.verify_id_token(token)

        user_id = decoded_token.get("uid")

        if not user_id:
            logger.error("Token verified but missing 'uid' claim")
            raise HTTPException(
                status_code=401,
                detail="Invalid token: missing user ID",
            )

        logger.info(f"Successfully verified Firebase token for user {user_id}")

        return user_id

    except auth.InvalidIdTokenError:
        logger.warning("Invalid Firebase ID token")
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    except auth.ExpiredIdTokenError:
        logger.warning("Expired Firebase ID token")
        raise HTTPException(
            status_code=401,
            detail="Authentication token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    except auth.RevokedIdTokenError:
        logger.warning("Revoked Firebase ID token")
        raise HTTPException(
            status_code=401,
            detail="Authentication token revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    except auth.CertificateFetchError:
        logger.error("Failed to fetch Firebase public keys")
        raise HTTPException(
            status_code=503,
            detail="Authentication service temporarily unavailable",
        )

    except Exception as e:
        logger.error(f"Unexpected error verifying Firebase token: {e}")
        raise HTTPException(
            status_code=401,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Alternative: If you prefer to verify token from query parameter (less secure)
async def verify_firebase_token_query(
    firebase_token: Optional[str] = None,
) -> str:
    """Verify Firebase token from query parameter.

    WARNING: This is less secure than header-based auth because:
    - Tokens appear in server logs
    - Tokens appear in browser history
    - Tokens can be leaked via Referer headers

    Only use this if you have specific requirements that prevent header-based auth.

    Args:
        firebase_token: Firebase ID token from query parameter

    Returns:
        Firebase user ID (uid) from verified token

    Raises:
        HTTPException: 401 if token is missing, invalid, or expired
    """
    if not firebase_token:
        raise HTTPException(
            status_code=401,
            detail="Missing firebase_token parameter",
        )

    try:
        decoded_token = auth.verify_id_token(firebase_token)
        user_id = decoded_token.get("uid")

        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Invalid token: missing user ID",
            )

        return user_id

    except Exception as e:
        logger.error(f"Failed to verify Firebase token from query: {e}")
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token",
        )
