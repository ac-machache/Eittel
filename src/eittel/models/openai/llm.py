from __future__ import annotations

import contextlib
import os
import json
import logging
from typing import AsyncGenerator
from typing import TYPE_CHECKING

from google.genai import types
import websockets

from google.adk.models.base_llm import BaseLlm
from google.adk.models.base_llm_connection import BaseLlmConnection
from google.adk.models.llm_response import LlmResponse
from google.adk.models.registry import LLMRegistry

from .connection import OpenAIRealtimeConnection
from .tool_schema import function_tools_to_openai_session_tools
from .. import (
  get_realtime_runconfig_provider,
  get_realtime_context,
)

logger = logging.getLogger('google_adk_community.' + __name__)

if TYPE_CHECKING:
  from google.adk.models.llm_request import LlmRequest


class OpenAIRealtime(BaseLlm):
  """Community provider for OpenAI Realtime models (WebSocket)."""

  model: str = 'gpt-realtime'

  @classmethod
  def supported_models(cls) -> list[str]:
    return [r'gpt-4o-realtime-.*', r'gpt-4o-realtime-preview', r'gpt-realtime.*']

  async def generate_content_async(
      self, llm_request: 'LlmRequest', stream: bool = False
  ) -> AsyncGenerator[LlmResponse, None]:
    raise NotImplementedError(
        f'Async generation is not supported for {self.model}. Use live mode.'
    )
    yield  # pragma: no cover

  @contextlib.asynccontextmanager
  async def connect(
      self, llm_request: 'LlmRequest'
  ) -> AsyncGenerator[BaseLlmConnection, None]:
    api_key = os.getenv('OPENAI_API_KEY')
    headers = {'OpenAI-Beta': 'realtime=v1'}
    if api_key:
      headers['Authorization'] = f'Bearer {api_key}'

    if (
        llm_request.live_connect_config
        and llm_request.live_connect_config.http_options
        and llm_request.live_connect_config.http_options.headers
    ):
      headers.update(llm_request.live_connect_config.http_options.headers)

    model_name = llm_request.model or self.model
    url = f'wss://api.openai.com/v1/realtime?model={model_name}'
    try:
      logger.info("OpenAI Realtime connect %s (auth=%s)", url, bool(headers.get('Authorization')))
    except Exception:
      pass
    ws = await websockets.connect(url, additional_headers=headers, max_size=None)
    # Consider the connection as session creation handshake completed on connect
    try:
      logger.info("OpenAI Realtime session.created for model %s", model_name)
    except Exception:
      pass

    # Build session.update payload
    session_update: dict = {'type': 'session.update', 'session': {}}

    # Build overrides from registered provider and runtime context
    try:
      def _deep_merge(base: dict, extra: dict) -> dict:
        """Recursively merge extra into base without dropping nested keys.

        Skips None values so they don't delete existing settings.
        """
        for k, v in (extra or {}).items():
          if v is None:
            continue
          if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = _deep_merge(dict(base[k]), v)
          else:
            base[k] = v
        return base

      overrides = {}
      # Merge provider overrides if a provider has been registered
      prov = get_realtime_runconfig_provider()
      if callable(prov):
        try:
          provider_overrides = prov(llm_request)  # type: ignore[arg-type]
          if isinstance(provider_overrides, dict):
            try:
              logger.info(
                "OpenAI Realtime provider overrides: %s",
                json.dumps(provider_overrides, ensure_ascii=False),
              )
            except Exception:
              logger.info("OpenAI Realtime provider overrides (raw): %s", provider_overrides)
            overrides = _deep_merge(overrides, provider_overrides)
        except Exception:
          pass
      # Merge ephemeral runtime context if set by the app
      runtime_ctx = get_realtime_context()
      if isinstance(runtime_ctx, dict):
        try:
          logger.info(
            "OpenAI Realtime runtime context: %s",
            json.dumps(runtime_ctx, ensure_ascii=False),
          )
        except Exception:
          logger.info("OpenAI Realtime runtime context (raw): %s", runtime_ctx)
        overrides = _deep_merge(overrides, runtime_ctx)
      if overrides:
        session_update['session'] = _deep_merge(
          session_update['session'], overrides
        )
    except Exception:
      pass

    if 'tool_choice' not in session_update['session']:
      session_update['session']['tool_choice'] = 'auto'


    if llm_request.config.system_instruction:
      session_update['session']['instructions'] = (
          llm_request.config.system_instruction
      )

    if llm_request.config.tools:
      tools = function_tools_to_openai_session_tools(llm_request.config.tools)
      if tools:
        session_update['session']['tools'] = tools

    # Log the session.update intent and, in debug, the full session config
    try:
      logger.info("OpenAI Realtime session.update (initial settings)")
      # Always log the session settings at INFO for troubleshooting
      try:
        logger.info(
          "OpenAI Realtime session settings: %s",
          json.dumps(session_update.get('session', {}), ensure_ascii=False),
        )
      except Exception:
        # Fallback to debug if serialization fails
        if logger.isEnabledFor(logging.DEBUG):
          logger.debug(
            "OpenAI Realtime session settings (raw): %s",
            session_update.get('session', {}),
          )
    except Exception:
      pass

    await ws.send(json.dumps(session_update, separators=(",", ":"), ensure_ascii=False))

    try:
      yield OpenAIRealtimeConnection(websocket=ws, model_name=model_name)
    finally:
      try:
        await ws.close()
      except Exception:
        pass


# Register on import
for regex in OpenAIRealtime.supported_models():
  LLMRegistry.register(OpenAIRealtime)
