"""
Calendar Tools for Google ADK

This module provides ADK-compatible Calendar tools with persistent OAuth credential management.
No experimental dependencies - production ready.
"""

from typing import Any, Dict, List, Optional

from ...gsuite.auth import (
    BASE_SCOPES,
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_READONLY_SCOPE,
    CALENDAR_SCOPE,
)
from ...gsuite.gcalendar.client import CalendarClient
from .base_google_tool import EittelGoogleTool


class PersistentCalendarTool(EittelGoogleTool):
    """
    Calendar tool with persistent credential storage.

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
        Initialize the persistent Calendar tool.

        Args:
            func: The tool function to execute
            scopes: OAuth scopes required for Calendar access
        """
        super().__init__(
            func=func,
            scopes=scopes,
            service_name="calendar",
            service_version="v3",
            hidden_param_name="calendar",
        )


# ==============================================================================
# Calendar Tool Functions (What ADK registers and the agent sees)
# ==============================================================================


async def list_calendars(calendar: CalendarClient) -> str:
    """
    List all calendars for the authenticated user.

    Returns:
        Formatted list of calendars with their IDs and access levels

    Example response shows calendar names, whether they're primary, and access roles.
    """
    return await calendar.list_calendars()


async def get_calendar_events(
    calendar: CalendarClient,
    calendar_id: str,
    max_results: int,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    query: Optional[str] = None,
) -> str:
    """
    Get events from a calendar within a time range.

    Args:
        calendar_id: Calendar ID to query (default: "primary" for user's main calendar)
        max_results: Maximum number of events to return (default: 10, max: 250)
        time_min: Start of time range in ISO 8601 format (e.g., "2024-03-01T00:00:00Z")
        time_max: End of time range in ISO 8601 format (optional)
        query: Free text search query to filter events (optional)

    Returns:
        Formatted list of events with details (time, location, attendees, etc.)

    Examples:
        - Get next 10 events: get_calendar_events()
        - Get events for March: get_calendar_events(time_min="2024-03-01T00:00:00Z", time_max="2024-04-01T00:00:00Z")
        - Search meetings: get_calendar_events(query="team meeting")
    """
    if not calendar_id:
        calendar_id = "primary"
    if not max_results:
        max_results = 10
    return await calendar.get_events(
        calendar_id=calendar_id,
        max_results=max_results,
        time_min=time_min,
        time_max=time_max,
        query=query,
    )


async def create_calendar_event(
    calendar: CalendarClient,
    summary: str,
    start_time: str,
    end_time: str,
    calendar_id: str,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[List[str]] = None,
    timezone: Optional[str] = None,
    reminders: Optional[str] = None,
) -> str:
    """
    Create a new calendar event.

    Args:
        summary: Event title/summary
        start_time: Event start time - ISO 8601 format (e.g., "2024-03-15T10:00:00") or date only for all-day (e.g., "2024-03-15")
        end_time: Event end time - same format as start_time
        calendar_id: Calendar ID (default: "primary")
        description: Detailed event description (optional)
        location: Event location (optional)
        attendees: List of attendee email addresses (optional)
        timezone: Timezone for the event (e.g., "America/New_York", "Europe/London") - optional
        reminders: Event reminders as JSON string (e.g., '{"useDefault": false, "overrides": [{"method": "email", "minutes": 30}]}') (optional)

    Returns:
        Success message with event ID and calendar link

    Examples:
        - Simple meeting: create_calendar_event(
              summary="Team Standup",
              start_time="2024-03-15T09:00:00",
              end_time="2024-03-15T09:30:00"
          )
        - All-day event: create_calendar_event(
              summary="Conference",
              start_time="2024-03-20",
              end_time="2024-03-21"
          )
        - With attendees: create_calendar_event(
              summary="Project Review",
              start_time="2024-03-15T14:00:00",
              end_time="2024-03-15T15:00:00",
              attendees=["alice@company.com", "bob@company.com"],
              location="Conference Room A"
          )
    """

    if not calendar_id:
        calendar_id = "primary"
    return await calendar.create_event(
        summary=summary,
        start_time=start_time,
        end_time=end_time,
        calendar_id=calendar_id,
        description=description,
        location=location,
        attendees=attendees,
        timezone=timezone,
        reminders=reminders,
    )


async def delete_calendar_event(
    calendar: CalendarClient, event_id: str, calendar_id: str
) -> str:
    """
    Delete a calendar event.

    Args:
        event_id: ID of the event to delete (from get_calendar_events results)
        calendar_id: Calendar ID (default: "primary")

    Returns:
        Success message confirming deletion

    Example:
        delete_calendar_event(event_id="abc123xyz")
    """
    if not calendar_id:
        calendar_id = "primary"
    return await calendar.delete_event(event_id=event_id, calendar_id=calendar_id)


# ==============================================================================
# Tool Registration Helper
# ==============================================================================


def create_calendar_tools(include: Optional[List[str]] = None) -> list:
    """
    Create Calendar tools for ADK with persistent credential storage.

    Users must be pre-authorized via your web application. This function
    creates tools that load existing credentials from Firestore/file storage.

    Each user will automatically get their own credentials based on their user_id
    from the tool_context. This supports true multi-user scenarios where different
    users can use the same agent with their own Google Calendar accounts.

    Args:
        include: Optional list of tool names to include. If None, includes all tools.
                 Available tools: 'list', 'get_events', 'create', 'delete'

    Returns:
        List of configured Calendar tools ready to add to an ADK agent

    Examples:
        >>> # Get all Calendar tools
        >>> calendar_tools = create_calendar_tools()

        >>> # Get only read tools (no create/delete)
        >>> calendar_tools = create_calendar_tools(include=['list', 'get_events'])

        >>> # Get only create tool
        >>> calendar_tools = create_calendar_tools(include=['create'])
    """
    # Define required scopes
    scopes = list(
        set(
            BASE_SCOPES
            + [
                CALENDAR_SCOPE,
                CALENDAR_READONLY_SCOPE,
                CALENDAR_EVENTS_SCOPE,
            ]
        )
    )

    # Define all available tools
    all_tools = {
        'list': PersistentCalendarTool(
            func=list_calendars,
            scopes=scopes,
        ),
        'get_events': PersistentCalendarTool(
            func=get_calendar_events,
            scopes=scopes,
        ),
        'create': PersistentCalendarTool(
            func=create_calendar_event,
            scopes=scopes,
        ),
        'delete': PersistentCalendarTool(
            func=delete_calendar_event,
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
