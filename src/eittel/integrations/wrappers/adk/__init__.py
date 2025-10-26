"""
ADK Wrappers for Google Workspace Integration

This module provides Google ADK-compatible tool wrappers with persistent OAuth
credential management for Google Workspace services.
"""

from .gmail_tools import (
    PersistentGmailTool,
    create_gmail_tools,
    search_gmail_messages,
    get_gmail_message_content,
    send_gmail_message,
)

from .calendar_tools import (
    PersistentCalendarTool,
    create_calendar_tools,
    list_calendars,
    get_calendar_events,
    create_calendar_event,
    delete_calendar_event,
)

__all__ = [
    # Gmail tools
    'PersistentGmailTool',
    'create_gmail_tools',
    'search_gmail_messages',
    'get_gmail_message_content',
    'send_gmail_message',

    # Calendar tools
    'PersistentCalendarTool',
    'create_calendar_tools',
    'list_calendars',
    'get_calendar_events',
    'create_calendar_event',
    'delete_calendar_event',
]
