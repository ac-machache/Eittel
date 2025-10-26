"""
Google Workspace Authentication Module

This module provides OAuth credential management for Google Workspace APIs.

Features:
- Persistent credential storage (file system or Firestore)
- In-memory credential caching for performance
- Automatic token refresh
- Multi-user support
- Cloud-ready (works with Cloud Run, Kubernetes, etc.)

Quick Start:
    >>> from eittel.integrations.gsuite.auth import get_credential_store, GMAIL_SEND_SCOPE
    >>>
    >>> # Get credential store
    >>> store = get_credential_store()
    >>>
    >>> # Load credentials
    >>> credentials = store.get_credential("user@example.com")
    >>>
    >>> # Store credentials
    >>> store.store_credential("user@example.com", credentials)
"""

from .credential_store import (
    CredentialStore,
    LocalDirectoryCredentialStore,
    get_credential_store,
    set_credential_store,
)

from .scopes import (
    # Base scopes
    BASE_SCOPES,
    USERINFO_EMAIL_SCOPE,
    USERINFO_PROFILE_SCOPE,
    OPENID_SCOPE,

    # Service scope groups
    GMAIL_SCOPES,
    CALENDAR_SCOPES,
    DRIVE_SCOPES,
    DOCS_SCOPES,
    SHEETS_SCOPES,
    CHAT_SCOPES,
    FORMS_SCOPES,
    SLIDES_SCOPES,
    TASKS_SCOPES,
    CUSTOM_SEARCH_SCOPES,

    # Individual scopes (commonly used)
    GMAIL_SEND_SCOPE,
    GMAIL_READONLY_SCOPE,
    GMAIL_MODIFY_SCOPE,
    GMAIL_COMPOSE_SCOPE,
    CALENDAR_SCOPE,
    CALENDAR_READONLY_SCOPE,
    CALENDAR_EVENTS_SCOPE,
    DRIVE_SCOPE,
    DRIVE_READONLY_SCOPE,
    DOCS_WRITE_SCOPE,
    DOCS_READONLY_SCOPE,
    SHEETS_WRITE_SCOPE,
    SHEETS_READONLY_SCOPE,

    # Tool mapping and helpers
    TOOL_SCOPES_MAP,
    get_scopes_for_tools,
)

from .session_store import (
    CredentialCache,
    get_credential_cache,
)

__all__ = [
    # Credential storage
    'CredentialStore',
    'LocalDirectoryCredentialStore',
    'get_credential_store',
    'set_credential_store',

    # Credential caching
    'CredentialCache',
    'get_credential_cache',

    # Scopes - groups
    'BASE_SCOPES',
    'GMAIL_SCOPES',
    'CALENDAR_SCOPES',
    'DRIVE_SCOPES',
    'DOCS_SCOPES',
    'SHEETS_SCOPES',
    'CHAT_SCOPES',
    'FORMS_SCOPES',
    'SLIDES_SCOPES',
    'TASKS_SCOPES',
    'CUSTOM_SEARCH_SCOPES',

    # Scopes - individual (commonly used)
    'GMAIL_SEND_SCOPE',
    'GMAIL_READONLY_SCOPE',
    'GMAIL_MODIFY_SCOPE',
    'GMAIL_COMPOSE_SCOPE',
    'CALENDAR_SCOPE',
    'CALENDAR_READONLY_SCOPE',
    'CALENDAR_EVENTS_SCOPE',
    'DRIVE_SCOPE',
    'DRIVE_READONLY_SCOPE',
    'DOCS_WRITE_SCOPE',
    'DOCS_READONLY_SCOPE',
    'SHEETS_WRITE_SCOPE',
    'SHEETS_READONLY_SCOPE',

    # Helpers
    'TOOL_SCOPES_MAP',
    'get_scopes_for_tools',
]
