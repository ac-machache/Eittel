"""
Google Calendar API Client

This module provides a clean, framework-agnostic client for Google Calendar API operations.
"""

import asyncio
import datetime
import json
import logging
import re
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# ==============================================================================
# Helper Functions (Pure utility functions, no service dependency)
# ==============================================================================

def _parse_reminders_json(
    reminders_input: Optional[Union[str, List[Dict[str, Any]]]],
    function_name: str
) -> List[Dict[str, Any]]:
    """
    Parse reminders from JSON string or list object and validate them.

    Args:
        reminders_input: Reminders as JSON string or list of dicts
        function_name: Name of calling function (for logging)

    Returns:
        List of reminder dictionaries

    Raises:
        ValueError: If reminders format is invalid
    """
    if reminders_input is None:
        return []

    # If already a list, validate and return
    if isinstance(reminders_input, list):
        for reminder in reminders_input:
            if not isinstance(reminder, dict):
                raise ValueError(f"{function_name}: Each reminder must be a dictionary")
            if "method" not in reminder or "minutes" not in reminder:
                raise ValueError(
                    f"{function_name}: Each reminder must have 'method' and 'minutes' keys"
                )
        return reminders_input

    # If string, parse as JSON
    if isinstance(reminders_input, str):
        try:
            parsed = json.loads(reminders_input)
            if not isinstance(parsed, list):
                raise ValueError(f"{function_name}: Reminders JSON must be a list")
            for reminder in parsed:
                if not isinstance(reminder, dict):
                    raise ValueError(f"{function_name}: Each reminder must be a dictionary")
                if "method" not in reminder or "minutes" not in reminder:
                    raise ValueError(
                        f"{function_name}: Each reminder must have 'method' and 'minutes' keys"
                    )
            return parsed
        except json.JSONDecodeError as e:
            raise ValueError(f"{function_name}: Invalid JSON for reminders: {e}")

    raise ValueError(
        f"{function_name}: reminders must be a JSON string or a list of dictionaries"
    )


def _format_attendee_details(attendees: List[Dict[str, Any]], indent: str = "  ") -> str:
    """
    Format attendee details for display.

    Args:
        attendees: List of attendee dictionaries
        indent: String indentation for formatting

    Returns:
        Formatted attendee details string
    """
    if not attendees:
        return f"{indent}(No attendees)"

    lines = []
    for attendee in attendees:
        email = attendee.get("email", "N/A")
        name = attendee.get("displayName", "")
        response = attendee.get("responseStatus", "needsAction")
        optional = attendee.get("optional", False)
        organizer = attendee.get("organizer", False)

        attendee_str = f"{indent}- {email}"
        if name:
            attendee_str += f" ({name})"

        tags = []
        if organizer:
            tags.append("Organizer")
        if optional:
            tags.append("Optional")
        tags.append(f"Status: {response}")

        attendee_str += f" [{', '.join(tags)}]"
        lines.append(attendee_str)

    return "\n".join(lines)


def _correct_time_format_for_api(
    datetime_str: Optional[str],
    timezone_str: Optional[str],
    field_name: str
) -> Dict[str, str]:
    """
    Validate and format datetime for Google Calendar API.

    Args:
        datetime_str: DateTime string (ISO format or date-only)
        timezone_str: Timezone string (e.g., "America/New_York")
        field_name: Field name for error messages

    Returns:
        Dictionary with 'dateTime'/'date' and 'timeZone' keys

    Raises:
        ValueError: If datetime format is invalid
    """
    if not datetime_str:
        raise ValueError(f"{field_name} is required")

    # Check if it's a date-only format (YYYY-MM-DD)
    date_only_pattern = r"^\d{4}-\d{2}-\d{2}$"
    if re.match(date_only_pattern, datetime_str):
        # All-day event
        return {"date": datetime_str}

    # DateTime format - validate ISO 8601
    try:
        # Try parsing to validate format
        datetime.datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
        result = {"dateTime": datetime_str}
        if timezone_str:
            result["timeZone"] = timezone_str
        return result
    except ValueError as e:
        raise ValueError(
            f"Invalid {field_name} format: {datetime_str}. "
            f"Use ISO 8601 format (e.g., '2024-03-15T10:00:00') or date format (YYYY-MM-DD). Error: {e}"
        )


# ==============================================================================
# Calendar Client Class
# ==============================================================================

class CalendarClient:
    """
    Google Calendar API client for calendar operations.

    This client provides methods for listing calendars, managing events,
    and interacting with Google Calendar. It requires a pre-authenticated
    Calendar API service object.

    Args:
        service: Authenticated Google Calendar API service object

    Example:
        >>> from googleapiclient.discovery import build
        >>> service = build('calendar', 'v3', credentials=credentials)
        >>> calendar = CalendarClient(service)
        >>> await calendar.list_calendars()
    """

    def __init__(self, service):
        """
        Initialize Calendar client with authenticated service.

        Args:
            service: Authenticated Google Calendar API service object
        """
        self.service = service
        logger.debug("CalendarClient initialized")

    async def list_calendars(self) -> str:
        """
        List all calendars for the authenticated user.

        Returns:
            Formatted string with calendar list

        Example:
            >>> calendars = await calendar.list_calendars()
        """
        logger.info("[list_calendars] Fetching calendar list")

        calendar_list = await asyncio.to_thread(
            self.service.calendarList().list().execute
        )

        calendars = calendar_list.get("items", [])

        if not calendars:
            return "No calendars found."

        output_lines = [
            f"Found {len(calendars)} calendar(s):",
            ""
        ]

        for cal in calendars:
            cal_id = cal.get("id", "N/A")
            summary = cal.get("summary", "Unnamed Calendar")
            primary = cal.get("primary", False)
            access_role = cal.get("accessRole", "N/A")

            cal_str = f"- {summary}"
            if primary:
                cal_str += " (Primary)"
            cal_str += f" [Access: {access_role}]"
            cal_str += f"\n  ID: {cal_id}"

            output_lines.append(cal_str)
            output_lines.append("")

        logger.info(f"[list_calendars] Listed {len(calendars)} calendars")
        return "\n".join(output_lines)

    async def get_events(
        self,
        calendar_id: str = "primary",
        max_results: int = 10,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        query: Optional[str] = None
    ) -> str:
        """
        Get events from a calendar.

        Args:
            calendar_id: Calendar ID (default: "primary")
            max_results: Maximum number of events (default: 10)
            time_min: Start time filter (ISO format, optional)
            time_max: End time filter (ISO format, optional)
            query: Search query (optional)

        Returns:
            Formatted string with event details

        Example:
            >>> events = await calendar.get_events(
            ...     calendar_id="primary",
            ...     time_min="2024-03-01T00:00:00Z",
            ...     max_results=5
            ... )
        """
        logger.info(f"[get_events] Calendar: {calendar_id}, Max: {max_results}")

        params = {
            "calendarId": calendar_id,
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime"
        }

        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        if query:
            params["q"] = query

        events_result = await asyncio.to_thread(
            self.service.events().list(**params).execute
        )

        events = events_result.get("items", [])

        if not events:
            return "No events found."

        output_lines = [
            f"Found {len(events)} event(s):",
            "=" * 80,
            ""
        ]

        for event in events:
            event_id = event.get("id", "N/A")
            summary = event.get("summary", "(No title)")
            start = event.get("start", {})
            end = event.get("end", {})
            description = event.get("description", "")
            location = event.get("location", "")
            attendees = event.get("attendees", [])

            start_str = start.get("dateTime", start.get("date", "N/A"))
            end_str = end.get("dateTime", end.get("date", "N/A"))

            output_lines.extend([
                f"Event: {summary}",
                f"ID: {event_id}",
                f"Start: {start_str}",
                f"End: {end_str}",
            ])

            if location:
                output_lines.append(f"Location: {location}")
            if description:
                output_lines.append(f"Description: {description[:200]}...")
            if attendees:
                output_lines.append("Attendees:")
                output_lines.append(_format_attendee_details(attendees))

            output_lines.extend(["", "-" * 80, ""])

        logger.info(f"[get_events] Retrieved {len(events)} events")
        return "\n".join(output_lines)

    async def create_event(
        self,
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
            summary: Event title
            start_time: Start time (ISO format or YYYY-MM-DD for all-day)
            end_time: End time (ISO format or YYYY-MM-DD for all-day)
            calendar_id: Calendar ID (default: "primary")
            description: Event description (optional)
            location: Event location (optional)
            attendees: List of attendee emails (optional)
            timezone: Timezone (e.g., "America/New_York", optional)
            reminders: Reminders as JSON or list (optional)

        Returns:
            Success message with event ID and link

        Example:
            >>> result = await calendar.create_event(
            ...     summary="Team Meeting",
            ...     start_time="2024-03-15T10:00:00",
            ...     end_time="2024-03-15T11:00:00",
            ...     attendees=["colleague@example.com"]
            ... )
        """
        logger.info(f"[create_event] Creating: {summary}")

        # Build event object
        event = {
            "summary": summary,
            "start": _correct_time_format_for_api(start_time, timezone, "start_time"),
            "end": _correct_time_format_for_api(end_time, timezone, "end_time"),
        }

        if description:
            event["description"] = description
        if location:
            event["location"] = location
        if attendees:
            event["attendees"] = [{"email": email} for email in attendees]
        if reminders:
            parsed_reminders = _parse_reminders_json(reminders, "create_event")
            event["reminders"] = {
                "useDefault": False,
                "overrides": parsed_reminders
            }

        # Create the event
        created_event = await asyncio.to_thread(
            self.service.events().insert(calendarId=calendar_id, body=event).execute
        )

        event_id = created_event.get("id")
        html_link = created_event.get("htmlLink", "")

        logger.info(f"[create_event] Created event: {event_id}")
        return f"Event created successfully.\nEvent ID: {event_id}\nLink: {html_link}"

    async def delete_event(
        self,
        event_id: str,
        calendar_id: str = "primary"
    ) -> str:
        """
        Delete a calendar event.

        Args:
            event_id: Event ID to delete
            calendar_id: Calendar ID (default: "primary")

        Returns:
            Success message

        Example:
            >>> result = await calendar.delete_event(event_id="abc123")
        """
        logger.info(f"[delete_event] Deleting event: {event_id}")

        await asyncio.to_thread(
            self.service.events().delete(
                calendarId=calendar_id,
                eventId=event_id
            ).execute
        )

        logger.info(f"[delete_event] Deleted event: {event_id}")
        return f"Event {event_id} deleted successfully from calendar {calendar_id}."

    # TODO: Add modify_event method
