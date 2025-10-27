"""
Gmail Tools for Google ADK

This module provides ADK-compatible Gmail tools with persistent OAuth credential management.
No experimental dependencies - production ready.
"""

from typing import Optional

from ...gsuite.auth import (
    BASE_SCOPES,
    GMAIL_COMPOSE_SCOPE,
    GMAIL_MODIFY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
)
from ...gsuite.gmail.client import GmailClient
from .base_google_tool import EittelGoogleTool


class PersistentGmailTool(EittelGoogleTool):
    """
    Gmail tool with persistent credential storage.

    This tool loads pre-authorized credentials from Firestore/file storage.
    Users must be authorized via your web application before using these tools.

    Features:
    - Credentials persist across sessions
    - Survives server restarts
    - L1 cache (memory) + L2 storage (file/Firestore)
    - Automatic token refresh
    - Multi-user support
    - No experimental ADK dependencies
    """

    def __init__(self, func, scopes: list[str]):
        """
        Initialize the persistent Gmail tool.

        Args:
            func: The tool function to execute
            scopes: OAuth scopes required for Gmail access
        """
        super().__init__(
            func=func,
            scopes=scopes,
            service_name="gmail",
            service_version="v1",
            hidden_param_name="gmail",
        )


# ==============================================================================
# Gmail Tool Functions (What ADK registers and the agent sees)
# ==============================================================================


async def search_gmail_messages(gmail: GmailClient, query: str, page_size: int) -> str:
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
    if not page_size:
        page_size = 10
    return await gmail.search_messages(query=query, page_size=page_size)


async def get_gmail_message_content(gmail: GmailClient, message_id: str) -> str:
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
    bcc: Optional[str] = None,
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
    return await gmail.send_message(to=to, subject=subject, body=body, cc=cc, bcc=bcc)


# ==============================================================================
# Tool Registration Helper
# ==============================================================================


def create_gmail_tools(include: Optional[list[str]] = None) -> list:
    """
    Create Gmail tools for ADK with persistent credential storage.

    Users must be pre-authorized via your web application. This function
    creates tools that load existing credentials from Firestore/file storage.

    Each user will automatically get their own credentials based on their user_id
    from the tool_context. This supports true multi-user scenarios where different
    users can use the same agent with their own Gmail accounts.

    Args:
        include: Optional list of tool names to include. If None, includes all tools.
                 Available tools: 'search', 'get_content', 'send'

    Returns:
        List of configured Gmail tools ready to add to an ADK agent

    Examples:
        >>> # Get all Gmail tools
        >>> gmail_tools = create_gmail_tools()

        >>> # Get only search and read tools (no send)
        >>> gmail_tools = create_gmail_tools(include=['search', 'get_content'])

        >>> # Get only send tool
        >>> gmail_tools = create_gmail_tools(include=['send'])
    """
    # Define required scopes
    scopes = list(
        set(
            BASE_SCOPES
            + [
                GMAIL_SEND_SCOPE,
                GMAIL_READONLY_SCOPE,
                GMAIL_MODIFY_SCOPE,
                GMAIL_COMPOSE_SCOPE,
            ]
        )
    )

    # Define all available tools
    all_tools = {
        'search': PersistentGmailTool(
            func=search_gmail_messages,
            scopes=scopes,
        ),
        'get_content': PersistentGmailTool(
            func=get_gmail_message_content,
            scopes=scopes,
        ),
        'send': PersistentGmailTool(
            func=send_gmail_message,
            scopes=scopes,
        ),
    }

    # Filter tools based on include list
    if include is None:
        # Return all tools
        return list(all_tools.values())
    else:
        # Return only requested tools
        return [all_tools[name] for name in include if name in all_tools]
