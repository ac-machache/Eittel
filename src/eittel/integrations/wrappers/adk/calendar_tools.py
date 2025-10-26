"""
Calendar Tools for Google ADK

This module provides ADK-compatible Calendar tools with persistent OAuth credential management.
"""

from typing import Optional, List, Dict, Any, Union
from google.adk.tools.google_tool import GoogleTool
from google.adk.tools._google_credentials import BaseGoogleCredentialsConfig
from google.adk.tools.tool_context import ToolContext
from googleapiclient.discovery import build

from ...gsuite.gcalendar.client import CalendarClient
from ...gsuite.auth import (
    get_credential_store,
    get_credential_cache,
    CALENDAR_SCOPE,
    CALENDAR_READONLY_SCOPE,
    CALENDAR_EVENTS_SCOPE,
    BASE_SCOPES,
)


class PersistentCalendarTool(GoogleTool):
    """
    Base class for Calendar tools with persistent credential storage.

    Features:
    - Credentials persist across sessions
    - Survives server restarts
    - L1 cache (memory) + L2 storage (file/Firestore)
    - Automatic token refresh
    - Multi-user support (credentials isolated per user_id)
    """

    def __init__(
        self,
        func,
        credentials_config: BaseGoogleCredentialsConfig,
        tool_settings=None,
    ):
        """
        Initialize the persistent Calendar tool.

        Args:
            func: The tool function to execute
            credentials_config: ADK credentials configuration
            tool_settings: Optional tool settings
        """
        super().__init__(func, credentials_config=credentials_config, tool_settings=tool_settings)
        # Hide the 'calendar' parameter from the agent (LLM doesn't need to see it)
        self._ignore_params.append("calendar")
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
                    "User authorization is required to access Google Calendar. "
                    "Please complete the authorization flow."
                )

            # Build Calendar service
            service = build('calendar', 'v3', credentials=credentials)

            # Create Calendar client
            calendar_client = CalendarClient(service)

            # Execute the tool function with the client
            return await self.func(calendar_client, **args)

        except Exception as ex:
            return {
                "status": "ERROR",
                "error_details": str(ex),
            }


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
    calendar_id: str = "primary",
    max_results: int = 10,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    query: Optional[str] = None
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
    return await calendar.get_events(
        calendar_id=calendar_id,
        max_results=max_results,
        time_min=time_min,
        time_max=time_max,
        query=query
    )


async def create_calendar_event(
    calendar: CalendarClient,
    summary: str,
    start_time: str,
    end_time: str,
    calendar_id: str = "primary",
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[List[str]] = None,
    timezone: Optional[str] = None,
    reminders: Optional[Union[str, List[Dict[str, Any]]]] = None
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
        reminders: Event reminders as JSON string or list of dicts with 'method' and 'minutes' (optional)

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
    return await calendar.create_event(
        summary=summary,
        start_time=start_time,
        end_time=end_time,
        calendar_id=calendar_id,
        description=description,
        location=location,
        attendees=attendees,
        timezone=timezone,
        reminders=reminders
    )


async def delete_calendar_event(
    calendar: CalendarClient,
    event_id: str,
    calendar_id: str = "primary"
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
    return await calendar.delete_event(
        event_id=event_id,
        calendar_id=calendar_id
    )


# ==============================================================================
# Tool Registration Helper
# ==============================================================================

def create_calendar_tools(
    client_id: str,
    client_secret: str
) -> list:
    """
    Create Calendar tools for ADK with persistent credential storage.

    Each user will automatically get their own credentials based on their user_id
    from the tool_context. This supports true multi-user scenarios.

    Args:
        client_id: Google OAuth client ID
        client_secret: Google OAuth client secret

    Returns:
        List of configured Calendar tools ready to add to an ADK agent

    Example:
        >>> calendar_tools = create_calendar_tools(
        ...     client_id="your-client-id",
        ...     client_secret="your-client-secret"
        ... )
        >>>
        >>> from google.adk.agents import Agent
        >>> agent = Agent(
        ...     name="CalendarAssistant",
        ...     tools=calendar_tools
        ... )
    """
    # Create credentials config
    credentials_config = BaseGoogleCredentialsConfig(
        client_id=client_id,
        client_secret=client_secret,
        scopes=list(set(BASE_SCOPES + [
            CALENDAR_SCOPE,
            CALENDAR_READONLY_SCOPE,
            CALENDAR_EVENTS_SCOPE,
        ]))
    )

    # Create tools
    tools = [
        PersistentCalendarTool(
            func=list_calendars,
            credentials_config=credentials_config,
        ),
        PersistentCalendarTool(
            func=get_calendar_events,
            credentials_config=credentials_config,
        ),
        PersistentCalendarTool(
            func=create_calendar_event,
            credentials_config=credentials_config,
        ),
        PersistentCalendarTool(
            func=delete_calendar_event,
            credentials_config=credentials_config,
        ),
    ]

    return tools
