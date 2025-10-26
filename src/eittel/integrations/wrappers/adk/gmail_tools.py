"""
Gmail Tools for Google ADK

This module provides ADK-compatible Gmail tools with persistent OAuth credential management.
"""

from typing import Optional
from google.adk.tools.google_tool import GoogleTool
from google.adk.tools._google_credentials import BaseGoogleCredentialsConfig
from google.adk.tools.tool_context import ToolContext
from googleapiclient.discovery import build

from ...gsuite.gmail.client import GmailClient
from ...gsuite.auth import (
    get_credential_store,
    get_credential_cache,
    GMAIL_SEND_SCOPE,
    GMAIL_READONLY_SCOPE,
    GMAIL_MODIFY_SCOPE,
    GMAIL_COMPOSE_SCOPE,
    BASE_SCOPES,
)


class PersistentGmailTool(GoogleTool):
    """
    Base class for Gmail tools with persistent credential storage.

    Unlike ADK's default GoogleTool, this uses our persistent credential
    system (file or Firestore) so users don't have to re-authenticate
    on every session.

    Features:
    - Credentials persist across sessions
    - Survives server restarts
    - L1 cache (memory) + L2 storage (file/Firestore)
    - Automatic token refresh
    """

    def __init__(
        self,
        func,
        credentials_config: BaseGoogleCredentialsConfig,
        tool_settings=None,
    ):
        """
        Initialize the persistent Gmail tool.

        Args:
            func: The tool function to execute
            credentials_config: ADK credentials configuration
            tool_settings: Optional tool settings
        """
        super().__init__(func, credentials_config=credentials_config, tool_settings=tool_settings)
        # Hide the 'gmail' parameter from the agent (LLM doesn't need to see it)
        self._ignore_params.append("gmail")
        self.credential_store = get_credential_store()
        self.credential_cache = get_credential_cache()

    async def _get_valid_credentials(self, tool_context: ToolContext):
        """
        Get valid credentials using our persistent storage.

        Flow:
        1. Get actual user from tool_context
        2. Check L1 cache (memory)
        3. Check L2 storage (file/Firestore)
        4. Try to refresh if expired
        5. Fall back to ADK's OAuth flow if needed

        Args:
            tool_context: ADK tool context

        Returns:
            Valid credentials or None if OAuth flow is needed
        """
        # Get the actual user making this request
        user_id = tool_context.invocation_context.user_id
        if not user_id:
            raise ValueError("Cannot identify user: tool_context.invocation_context.user_id is None")

        # L1: Check in-memory cache
        creds = self.credential_cache.get(user_id)
        if creds and creds.valid:
            return creds

        # L2: Check persistent storage
        creds = self.credential_store.get_credential(user_id)
        if creds:
            if creds.valid:
                # Cache for next time
                self.credential_cache.set(user_id, creds)
                return creds

            # Try to refresh
            if creds.expired and creds.refresh_token:
                try:
                    from google.auth.transport.requests import Request
                    creds.refresh(Request())
                    # Save refreshed credentials
                    self.credential_store.store_credential(user_id, creds)
                    self.credential_cache.set(user_id, creds)
                    return creds
                except Exception as e:
                    # Refresh failed, fall through to ADK OAuth
                    pass

        # L3: Use ADK's OAuth flow
        creds = await self._credentials_manager.get_valid_credentials(tool_context)

        # Save to our persistent storage
        if creds:
            self.credential_store.store_credential(user_id, creds)
            self.credential_cache.set(user_id, creds)

        return creds

    async def run_async(self, args: dict, tool_context: ToolContext):
        """
        Execute the tool with credential handling.

        Args:
            args: Tool arguments from the agent
            tool_context: ADK tool execution context

        Returns:
            Tool execution result
        """
        try:
            # Get valid credentials
            credentials = await self._get_valid_credentials(tool_context)

            if credentials is None:
                return (
                    "User authorization is required to access Gmail. "
                    "Please complete the authorization flow."
                )

            # Build Gmail service
            service = build('gmail', 'v1', credentials=credentials)

            # Create Gmail client
            gmail_client = GmailClient(service)

            # Execute the tool function with the client
            return await self.func(gmail_client, **args)

        except Exception as ex:
            return {
                "status": "ERROR",
                "error_details": str(ex),
            }


# ==============================================================================
# Gmail Tool Functions (What ADK registers and the agent sees)
# ==============================================================================

async def search_gmail_messages(
    gmail: GmailClient,
    query: str,
    page_size: int = 10
) -> str:
    """
    Search messages in Gmail based on a query.

    Args:
        query: Gmail search query (supports standard Gmail operators like 'from:', 'subject:', 'is:unread', etc.)
        page_size: Maximum number of messages to return (default: 10, max: 100)

    Returns:
        Formatted list of matching messages with IDs and URLs

    Examples:
        - "from:boss@company.com is:unread" - Unread emails from your boss
        - "subject:invoice after:2024/01/01" - Invoices from this year
        - "has:attachment larger:5M" - Emails with large attachments
    """
    return await gmail.search_messages(query=query, page_size=page_size)


async def get_gmail_message_content(
    gmail: GmailClient,
    message_id: str
) -> str:
    """
    Get the full content of a specific Gmail message.

    Args:
        message_id: Gmail message ID (from search results)

    Returns:
        Complete message details including headers and body
    """
    return await gmail.get_message_content(message_id=message_id)


async def send_gmail_message(
    gmail: GmailClient,
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None
) -> str:
    """
    Send an email via Gmail.

    Args:
        to: Recipient email address
        subject: Email subject line
        body: Email body content (plain text)
        cc: Carbon copy recipients (optional, comma-separated)
        bcc: Blind carbon copy recipients (optional, comma-separated)

    Returns:
        Success message with sent message ID
    """
    return await gmail.send_message(
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc
    )


# ==============================================================================
# Tool Registration Helper
# ==============================================================================

def create_gmail_tools(
    client_id: str,
    client_secret: str
) -> list:
    """
    Create Gmail tools for ADK with persistent credential storage.

    Each user will automatically get their own credentials based on their user_id
    from the tool_context. This supports true multi-user scenarios where different
    users can use the same agent with their own Gmail accounts.

    Args:
        client_id: Google OAuth client ID
        client_secret: Google OAuth client secret

    Returns:
        List of configured Gmail tools ready to add to an ADK agent

    Example:
        >>> gmail_tools = create_gmail_tools(
        ...     client_id="your-client-id",
        ...     client_secret="your-client-secret"
        ... )
        >>>
        >>> from google.adk.agents import Agent
        >>> agent = Agent(
        ...     name="EmailAssistant",
        ...     tools=gmail_tools
        ... )
        >>>
        >>> # User A calls agent -> uses User A's Gmail
        >>> # User B calls agent -> uses User B's Gmail
        >>> # Credentials are automatically isolated per user!
    """
    # Create credentials config
    credentials_config = BaseGoogleCredentialsConfig(
        client_id=client_id,
        client_secret=client_secret,
        scopes=list(set(BASE_SCOPES + [
            GMAIL_SEND_SCOPE,
            GMAIL_READONLY_SCOPE,
            GMAIL_MODIFY_SCOPE,
            GMAIL_COMPOSE_SCOPE,
        ]))
    )

    # Create tools
    tools = [
        PersistentGmailTool(
            func=search_gmail_messages,
            credentials_config=credentials_config,
        ),
        PersistentGmailTool(
            func=get_gmail_message_content,
            credentials_config=credentials_config,
        ),
        PersistentGmailTool(
            func=send_gmail_message,
            credentials_config=credentials_config,
        ),
    ]

    return tools
