"""OAuth authentication package for secure third-party integrations.

This package provides:
- Secure OAuth2 flow implementation with CSRF protection
- Firebase Authentication integration
- Redis-based state management
- Token storage and refresh
"""

from .google_routes import router as google_oauth_router
from .state_storage import OAuthStateStorage
from .firebase_auth import verify_firebase_token
from .oauth_manager import GoogleOAuthManager, FirestoreTokenStorage

__all__ = [
    "google_oauth_router",
    "OAuthStateStorage",
    "verify_firebase_token",
    "GoogleOAuthManager",
    "FirestoreTokenStorage",
]
