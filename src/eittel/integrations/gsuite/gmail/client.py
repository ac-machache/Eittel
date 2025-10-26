"""
Gmail API Client

This module provides a clean, framework-agnostic client for Gmail API operations.
"""

import asyncio
import base64
import logging
from email.mime.text import MIMEText
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

GMAIL_BATCH_SIZE = 25
GMAIL_REQUEST_DELAY = 0.1
HTML_BODY_TRUNCATE_LIMIT = 20000


# ==============================================================================
# Helper Functions (Pure utility functions, no service dependency)
# ==============================================================================


def _extract_message_body(payload):
    """
    Helper function to extract plain text body from a Gmail message payload.
    (Maintained for backward compatibility)

    Args:
        payload (dict): The message payload from Gmail API

    Returns:
        str: The plain text body content, or empty string if not found
    """
    bodies = _extract_message_bodies(payload)
    return bodies.get("text", "")


def _extract_message_bodies(payload):
    """
    Extract both plain text and HTML bodies from a Gmail message payload.

    Args:
        payload (dict): The message payload from Gmail API

    Returns:
        dict: Dictionary with 'text' and 'html' keys containing respective body content
    """
    result = {"text": "", "html": ""}

    def traverse(part):
        if "parts" in part:
            for subpart in part["parts"]:
                traverse(subpart)
        elif part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                try:
                    result["text"] = base64.urlsafe_b64decode(data).decode("utf-8")
                except Exception as e:
                    logger.warning(f"Failed to decode text/plain body: {e}")
        elif part.get("mimeType") == "text/html":
            data = part.get("body", {}).get("data")
            if data:
                try:
                    result["html"] = base64.urlsafe_b64decode(data).decode("utf-8")
                except Exception as e:
                    logger.warning(f"Failed to decode text/html body: {e}")

    traverse(payload)
    return result


def _format_body_content(text_body: str, html_body: str) -> str:
    """
    Format body content for LLM consumption with length limiting.

    Args:
        text_body: Plain text body content
        html_body: HTML body content

    Returns:
        Formatted body string, truncated if needed
    """
    if text_body:
        return text_body
    elif html_body:
        if len(html_body) > HTML_BODY_TRUNCATE_LIMIT:
            return f"{html_body[:HTML_BODY_TRUNCATE_LIMIT]}...[truncated, {len(html_body)} total chars]"
        return html_body
    return "(No body content)"


def _extract_headers(payload: dict, header_names: List[str]) -> Dict[str, str]:
    """
    Extract specific headers from message payload.

    Args:
        payload: Message payload
        header_names: List of header names to extract

    Returns:
        Dictionary mapping header names to values
    """
    headers = {}
    for header in payload.get("headers", []):
        name = header.get("name")
        if name in header_names:
            headers[name] = header.get("value", "")
    return headers


def _prepare_gmail_message(
    to: str,
    subject: str,
    body: str,
    from_email: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
) -> Dict:
    """
    Prepare a Gmail message for sending.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body content
        from_email: Sender email (optional)
        cc: CC recipients (optional)
        bcc: BCC recipients (optional)
        in_reply_to: Message-ID of message being replied to (optional)
        references: Message-ID references for threading (optional)

    Returns:
        Dictionary containing the prepared message
    """
    message = MIMEText(body)
    message["To"] = to
    message["Subject"] = subject

    if from_email:
        message["From"] = from_email
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return {"raw": raw_message}


def _generate_gmail_web_url(item_id: str, account_index: int = 0) -> str:
    """
    Generate a Gmail web interface URL for a message or thread.

    Args:
        item_id: Message ID or Thread ID
        account_index: Gmail account index (for multi-account setups)

    Returns:
        Gmail web interface URL
    """
    return f"https://mail.google.com/mail/u/{account_index}/#all/{item_id}"


def _format_gmail_results_plain(messages: list, query: str) -> str:
    """
    Format Gmail search results in a plain, LLM-friendly format.

    Args:
        messages: List of message objects from Gmail API
        query: The search query used

    Returns:
        Formatted string with search results
    """
    if not messages:
        return f"No messages found matching query: '{query}'"

    output_lines = [
        f"Found {len(messages)} message(s) matching query: '{query}'",
        "",
        "Results:",
        "--------",
    ]

    for idx, msg in enumerate(messages, 1):
        msg_id = msg.get("id", "N/A")
        thread_id = msg.get("threadId", "N/A")
        web_url = _generate_gmail_web_url(msg_id)

        output_lines.extend(
            [
                f"{idx}. Message ID: {msg_id}",
                f"   Thread ID: {thread_id}",
                f"   Gmail URL: {web_url}",
                "",
            ]
        )

    output_lines.append(
        "To get full message content, use get_gmail_message_content() with the Message ID."
    )

    return "\n".join(output_lines)


def _format_thread_content(thread_data: dict, thread_id: str) -> str:
    """
    Format thread content for LLM consumption.

    Args:
        thread_data: Thread data from Gmail API
        thread_id: Thread ID

    Returns:
        Formatted thread content string
    """
    messages = thread_data.get("messages", [])
    if not messages:
        return f"Thread {thread_id} contains no messages."

    output_lines = [
        f"Thread ID: {thread_id}",
        f"Number of messages: {len(messages)}",
        f"Gmail URL: {_generate_gmail_web_url(thread_id)}",
        "",
        "Messages in thread:",
        "=" * 80,
    ]

    for idx, msg in enumerate(messages, 1):
        msg_id = msg.get("id", "N/A")
        payload = msg.get("payload", {})

        headers = _extract_headers(
            payload, ["From", "To", "Subject", "Date", "Cc", "Bcc"]
        )

        bodies = _extract_message_bodies(payload)
        body_content = _format_body_content(
            bodies.get("text", ""), bodies.get("html", "")
        )

        output_lines.extend(
            [
                f"\nMessage {idx}/{len(messages)}:",
                f"Message ID: {msg_id}",
                f"From: {headers.get('From', 'N/A')}",
                f"To: {headers.get('To', 'N/A')}",
                f"Subject: {headers.get('Subject', 'N/A')}",
                f"Date: {headers.get('Date', 'N/A')}",
            ]
        )

        if headers.get("Cc"):
            output_lines.append(f"Cc: {headers['Cc']}")
        if headers.get("Bcc"):
            output_lines.append(f"Bcc: {headers['Bcc']}")

        output_lines.extend(["", "Body:", "-" * 40, body_content, "-" * 40])

    return "\n".join(output_lines)


# ==============================================================================
# Gmail Client Class
# ==============================================================================


class GmailClient:
    """
    Gmail API client for email operations.

    This client provides methods for searching, reading, sending, and managing
    Gmail messages. It requires a pre-authenticated Gmail API service object.

    Args:
        service: Authenticated Gmail API service object from googleapiclient

    Example:
        >>> from googleapiclient.discovery import build
        >>> service = build('gmail', 'v1', credentials=credentials)
        >>> gmail = GmailClient(service)
        >>> await gmail.search_messages(query="from:someone@example.com")
    """

    def __init__(self, service):
        """
        Initialize Gmail client with authenticated service.

        Args:
            service: Authenticated Gmail API service object
        """
        self.service = service
        logger.debug("GmailClient initialized")

    async def search_messages(self, query: str, page_size: int = 10) -> str:
        """
        Search messages in Gmail account based on a query.

        Args:
            query: Gmail search query (supports standard Gmail search operators)
            page_size: Maximum number of messages to return (default: 10)

        Returns:
            Formatted string with search results including Message IDs, Thread IDs, and URLs

        Example:
            >>> results = await gmail.search_messages(
            ...     query="from:boss@company.com is:unread",
            ...     page_size=5
            ... )
        """
        logger.info(f"[search_messages] Query: '{query}', Page size: {page_size}")

        response = await asyncio.to_thread(
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=page_size)
            .execute
        )

        if response is None:
            logger.warning("[search_messages] Null response from Gmail API")
            return f"No response received from Gmail API for query: '{query}'"

        messages = response.get("messages", []) or []
        formatted_output = _format_gmail_results_plain(messages, query)

        logger.info(f"[search_messages] Found {len(messages)} messages")
        return formatted_output

    async def get_message_content(self, message_id: str) -> str:
        """
        Get full content of a specific Gmail message.

        Args:
            message_id: Gmail message ID

        Returns:
            Formatted string with complete message details (headers, body, etc.)

        Example:
            >>> content = await gmail.get_message_content(message_id="18c1...")
        """
        logger.info(f"[get_message_content] Message ID: {message_id}")

        message = await asyncio.to_thread(
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute
        )

        payload = message.get("payload", {})
        headers = _extract_headers(
            payload, ["From", "To", "Subject", "Date", "Cc", "Bcc"]
        )

        bodies = _extract_message_bodies(payload)
        body_content = _format_body_content(
            bodies.get("text", ""), bodies.get("html", "")
        )

        output_lines = [
            f"Message ID: {message_id}",
            f"Thread ID: {message.get('threadId', 'N/A')}",
            f"Gmail URL: {_generate_gmail_web_url(message_id)}",
            "",
            f"From: {headers.get('From', 'N/A')}",
            f"To: {headers.get('To', 'N/A')}",
            f"Subject: {headers.get('Subject', 'N/A')}",
            f"Date: {headers.get('Date', 'N/A')}",
        ]

        if headers.get("Cc"):
            output_lines.append(f"Cc: {headers['Cc']}")
        if headers.get("Bcc"):
            output_lines.append(f"Bcc: {headers['Bcc']}")

        output_lines.extend(["", "Body:", "-" * 40, body_content, "-" * 40])

        logger.info(f"[get_message_content] Retrieved message: {message_id}")
        return "\n".join(output_lines)

    async def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
    ) -> str:
        """
        Send an email message via Gmail.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body content (plain text)
            cc: CC recipients (optional)
            bcc: BCC recipients (optional)

        Returns:
            Success message with sent message ID

        Example:
            >>> result = await gmail.send_message(
            ...     to="colleague@example.com",
            ...     subject="Project Update",
            ...     body="Here's the latest update..."
            ... )
        """
        logger.info(f"[send_message] To: {to}, Subject: {subject}")

        send_body = _prepare_gmail_message(
            to=to, subject=subject, body=body, cc=cc, bcc=bcc
        )

        result = await asyncio.to_thread(
            self.service.users().messages().send(userId="me", body=send_body).execute
        )

        message_id = result.get("id")
        logger.info(f"[send_message] Sent message ID: {message_id}")

        return f"Message sent successfully. Message ID: {message_id}"

    # TODO: Add more methods (draft, threads, labels, etc.)
