"""
Base Google Tool for ADK - No Experimental Dependencies

This module provides a production-ready base class for Google API tools
that doesn't depend on any experimental ADK features.

Key features:
- Uses FunctionTool (stable ADK API)
- Loads pre-authorized credentials from Firestore/file storage
- Multi-user support via tool_context.user_id
- Automatic token refresh
- L1 (memory) + L2 (persistent) credential caching
"""

from typing import Callable, Optional

from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext
from google.auth.transport.requests import Request

from ...gsuite.auth import (
    get_credential_cache,
    get_credential_store,
)


class EittelGoogleTool(FunctionTool):
    """
    Base class for Google API tools with persistent credential storage.

    This class extends FunctionTool (stable) instead of GoogleTool (experimental).
    It assumes users are pre-authorized via a separate OAuth flow.

    Features:
    - Loads existing credentials from Firestore or file storage
    - Multi-user support (credentials isolated by user_id)
    - Automatic token refresh when expired
    - L1 (memory cache) + L2 (persistent storage) for performance

    **Important:** This tool does NOT trigger OAuth flows. Users must be
    pre-authorized through your web application before using these tools.
    """

    def __init__(
        self,
        func: Callable,
        scopes: list[str],
        service_name: str,
        service_version: str,
        hidden_param_name: str = "client",
    ):
        """
        Initialize the Google API tool.

        Args:
            func: The tool function to execute
            scopes: OAuth scopes required for this tool
            service_name: Google API service name (e.g., 'gmail', 'calendar')
            service_version: API version (e.g., 'v1', 'v3')
            hidden_param_name: Name of the hidden client parameter (default: 'client')
        """
        super().__init__(func)

        # Hide the client parameter from LLM
        self._ignore_params.append(hidden_param_name)

        # Store configuration
        self.hidden_param_name = hidden_param_name
        self.scopes = scopes
        self.service_name = service_name
        self.service_version = service_version

        # Initialize credential storage
        self.credential_store = get_credential_store()
        self.credential_cache = get_credential_cache()

    async def _get_valid_credentials(self, tool_context: ToolContext):
        """
        Get valid credentials for the current user.

        This method:
        1. Checks L1 cache (memory)
        2. Falls back to L2 storage (Firestore/file)
        3. Refreshes expired tokens automatically
        4. Returns None if user is not authorized

        Args:
            tool_context: ADK tool context

        Returns:
            Valid credentials or None if user needs to authorize
        """
        # Get the actual user making this request
        user_id = tool_context._invocation_context.user_id
        if not user_id:
            raise ValueError(
                "Cannot identify user: tool_context.invocation_context.user_id is None"
            )

        # L1: Check in-memory cache
        creds = self.credential_cache.get(user_id)
        if creds and creds.valid:
            return creds

        # L2: Check persistent storage
        import logging
        logger = logging.getLogger(__name__)

        creds = self.credential_store.get_credential(user_id)
        if creds:
            logger.info(f"Found credentials for user {user_id} in storage (valid={creds.valid}, expired={creds.expired})")
            if creds.valid:
                # Cache for next time
                self.credential_cache.set(user_id, creds)
                return creds

            # Try to refresh expired token
            if creds.expired and creds.refresh_token:
                try:
                    logger.info(f"Refreshing expired token for user {user_id}")
                    creds.refresh(Request())
                    # Save refreshed credentials
                    self.credential_store.store_credential(user_id, creds)
                    self.credential_cache.set(user_id, creds)
                    logger.info(f"Successfully refreshed token for user {user_id}")
                    return creds
                except Exception as e:
                    # Refresh failed - credentials are invalid
                    logger.error(f"Failed to refresh token for user {user_id}: {e}")
                    return None
        else:
            logger.warning(f"No credentials found for user {user_id} in storage")

        # No credentials found or refresh failed
        return None

    async def run_async(self, args: dict, tool_context: ToolContext):
        """
        Execute the tool with credential handling.

        This method is called by ADK when the LLM invokes this tool.
        It handles credential retrieval and service initialization.

        Args:
            args: Tool arguments from the agent
            tool_context: ADK tool execution context

        Returns:
            Tool execution result or error message
        """
        try:
            # Get valid credentials
            credentials = await self._get_valid_credentials(tool_context)

            if credentials is None:
                return {
                    "status": "error",
                    "error_type": "authorization_required",
                    "message": (
                        f"User authorization is required to access {self.service_name.title()}. "
                        "Please complete the authorization flow in the web application."
                    ),
                }

            # Build Google API service
            from googleapiclient.discovery import build

            service = build(
                self.service_name, self.service_version, credentials=credentials
            )

            # Create client instance
            # The func expects the client as first parameter
            # We need to pass it dynamically
            from ...gsuite.gcalendar.client import CalendarClient
            from ...gsuite.gmail.client import GmailClient

            if self.service_name == "gmail":
                client = GmailClient(service)
            elif self.service_name == "calendar":
                client = CalendarClient(service)
            else:
                raise ValueError(f"Unknown service: {self.service_name}")

            # Execute the tool function with the client
            # Inject the client into args using the correct hidden param name
            # Note: self._ignore_params contains ['tool_context', 'input_stream', hidden_param_name]
            # We need to use the hidden_param_name we set during __init__, not just any ignored param
            args[self.hidden_param_name] = client

            # Filter args to only include valid parameters for the function
            # This is critical - FunctionTool does this filtering, but since we override
            # run_async(), we must do it ourselves to remove ADK internal params like 'input_stream'
            import inspect
            signature = inspect.signature(self.func)
            valid_params = {param for param in signature.parameters}
            filtered_args = {k: v for k, v in args.items() if k in valid_params}

            # Check for missing mandatory arguments (same as FunctionTool does)
            # This prevents confusing errors when LLM doesn't provide required params
            mandatory_args = []
            for name, param in signature.parameters.items():
                if param.default == inspect.Parameter.empty and param.kind not in (
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                ):
                    mandatory_args.append(name)

            missing_mandatory_args = [
                arg for arg in mandatory_args if arg not in filtered_args
            ]

            if missing_mandatory_args:
                missing_mandatory_args_str = '\n'.join(missing_mandatory_args)
                error_str = f"""Invoking `{self.name}()` failed as the following mandatory input parameters are not present:
{missing_mandatory_args_str}
You could retry calling this tool, but it is IMPORTANT for you to provide all the mandatory parameters."""
                return {'error': error_str}

            # Call the function with filtered args
            if inspect.iscoroutinefunction(self.func):
                return await self.func(**filtered_args)
            else:
                return self.func(**filtered_args)

        except Exception as ex:
            # Log the full error for debugging
            import traceback
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Tool execution failed: {ex}", exc_info=True)

            # Return detailed error
            return {
                "status": "error",
                "error_type": "execution_error",
                "message": str(ex),
                "traceback": traceback.format_exc(),
            }
