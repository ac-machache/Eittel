from __future__ import annotations


import base64
import json
import logging
from typing import AsyncGenerator, Any
import websockets
from google.genai import types

from google.adk.models.base_llm_connection import BaseLlmConnection
from google.adk.models.llm_response import LlmResponse
from .open_events import (
  OpenAIEventRouter,
  OpenAIEventTypes,
)

logger = logging.getLogger('google_adk_community.' + __name__)


class OpenAIRealtimeConnection(BaseLlmConnection):
  """OpenAI Realtime WebSocket connection implementing BaseLlmConnection.

  This provides the minimal bridging needed for ADK live flows:
  - send_history: forwards user text history as conversation items
  - send_content: forwards new user text or function responses and starts a turn
  - send_realtime: appends audio chunks and commits on activity end
  - receive: yields LlmResponse with audio bytes, text aggregation, tool calls,
    transcription deltas, and turn_complete when done
  """

  def __init__(
      self,
      *,
      websocket: websockets.asyncio.client.ClientConnection,
      model_name: str,
      tool_param_names: dict[str, set[str]] | None = None,
  ):
    self._ws = websocket
    self._model_name = model_name
    self._closed = False
    self._tool_param_names = tool_param_names or {}
    # Track pending function calls where arguments stream via deltas
    self._pending_func_calls: dict[str, dict] = {}
    # Holds final text from response.output_text.done until response.done arrives
    # Event router
    self._router = OpenAIEventRouter()
    self._register_event_handlers()

  async def _send(self, event: dict):
    try:
      await self._ws.send(json.dumps(event))
    except Exception as e:
      logger.error('Failed to send event to OpenAI Realtime: %s', e)
      raise

  # ----------------------
  # BaseLlmConnection API
  # ----------------------

  async def send_history(self, history: list[types.Content]):
    """
    Send the entire conversation history to a new session to reconstitute its context.

    This function iterates through a chronologically-ordered history list (managed
    by a higher-level controller) and "replays" each event to the new server
    session.
    """
    if not history:
        return

    # Previously tracked whether the last history item was user text to
    # auto-trigger a response. This behavior is removed to avoid automatic
    # responses during history prime.
    for content in history:
        if not content.parts:
            continue

        # IMPORTANT: The ADK framework represents tool responses (function_response)
        # as Content with role='user'. We MUST check for this specific part type
        # FIRST, before processing it as a generic user text message.
        is_function_response = content.parts[0].function_response is not None

        # --- Case 1: The content is a function response from your system. ---
        if is_function_response:
            # Represent tool responses as user text to preserve context without
            # requiring a matching function_call in this session.
            texts = []
            for part in content.parts:
                if part.function_response:
                    try:
                        output_text = json.dumps(part.function_response.response)
                    except Exception:
                        output_text = str(part.function_response.response)
                    texts.append({'type': 'input_text', 'text': output_text})
            if texts:
                await self._send({
                    'type': 'conversation.item.create',
                    'item': {
                        'type': 'message',
                        'role': 'user',
                        'content': texts,
                    },
                })
            # Do not trigger response.create for tool responses.
            continue

        # --- Case 2: The content is from the model (assistant). ---
        # This is the critical fix: we send the model's past actions,
        # including the crucial `function_call` requests.
        elif content.role == 'model':
            for part in content.parts:
                # Sub-case 2a: The model previously requested a tool call.
                if part.function_call:
                    # Skip replaying assistant function calls when priming history.
                    continue
                # Sub-case 2b: The model previously sent a text message.
                if part.text:
                    await self._send({
                      'type': 'conversation.item.create',
                      'item': {
                          'type': 'message',
                          'role': 'assistant',
                          'content': [{'type': 'text', 'text': part.text}],
                      },
                    })

        # --- Case 3: The content is a standard user text message. ---
        # This runs only if it's not a function_response.
        elif content.role == 'user':
            texts = [{'type': 'input_text', 'text': p.text} for p in content.parts if p.text]
            if texts:
                await self._send({
                    'type': 'conversation.item.create',
                    'item': {
                        'type': 'message',
                        'role': 'user',
                        'content': texts,
                    },
                })
            else:
                pass

    # Do not auto-trigger a response after priming conversation history.

  async def send_content(self, content: types.Content):
    """Send user text or function responses and start a response."""
    assert content.parts
    # Function responses
    if content.parts[0].function_response:
      for part in content.parts:
        if not part.function_response:
          continue
        call_id = part.function_response.id
        output = json.dumps(part.function_response.response)
        await self._send({
            'type': 'conversation.item.create',
            'item': {
                'type': 'function_call_output',
                'call_id': call_id,
                'output': output,
            },
        })
      logger.debug('Trigger response.create after function outputs')
      await self._send({'type': 'response.create'})
      return

    # Plain text
    texts = []
    for p in content.parts:
      if p.text:
        texts.append({'type': 'input_text', 'text': p.text})
    if texts:
      await self._send({
          'type': 'conversation.item.create',
          'item': {
              'type': 'message',
              'role': 'user',
              'content': texts,
          },
      })
      logger.debug('Trigger response.create after user message')
      await self._send({'type': 'response.create'})

  async def send_realtime(self, input):
    """Send realtime input: Blob audio or activity markers.

    Supported:
    - types.Blob: append audio chunk
    - types.ActivityStart: map to response.create (manual turn start)
    - types.ActivityEnd: map to response.cancel (manual barge/end)
    """
    if isinstance(input, types.Blob):
      audio_b64 = base64.b64encode(input.data).decode('utf-8')
      await self._send({'type': 'input_audio_buffer.append', 'audio': audio_b64})
      return
    # Map ActivityStart/End to control events for non-VAD workflows
    if getattr(types, 'ActivityStart', None) and isinstance(input, types.ActivityStart):
      # For client-managed turns (no server VAD), commit appended audio and start response
      await self.commit_input_audio()
      await self.start_response()
      return
    if getattr(types, 'ActivityEnd', None) and isinstance(input, types.ActivityEnd):
      await self.clear_input_audio()
      return
    raise ValueError('Unsupported realtime input type: %s' % type(input))


  async def receive(self) -> AsyncGenerator[LlmResponse, None]:
    """Receive server events and yield mapped LlmResponse objects."""
    try:
      async for message in self._ws:
        try:
          event = json.loads(message)
        except Exception as e:
          logger.error('Invalid JSON from OpenAI Realtime: %s', e)
          continue

        for resp in self._router.dispatch(event):
          yield resp
    except websockets.exceptions.ConnectionClosedOK:
      return
    except websockets.exceptions.ConnectionClosed as e:
      logger.error('OpenAI Realtime connection closed unexpectedly: %s', e)
      raise

  async def close(self):
    if self._closed:
      return
    try:
      await self._ws.close()
    finally:
      self._closed = True

  # ----------------------
  # Client control helpers
  # ----------------------

  async def start_response(self):
    await self._send({'type': 'response.create'})

  async def cancel_response(self):
    await self._send({'type': 'response.cancel'})

  async def commit_input_audio(self):
    await self._send({'type': 'input_audio_buffer.commit'})

  async def clear_input_audio(self):
    await self._send({'type': 'input_audio_buffer.clear'})

  async def clear_output_audio(self):
    await self._send({'type': 'output_audio_buffer.clear'})

  async def update_session(self, session_updates: dict):
    await self._send({'type': 'session.update', 'session': session_updates or {}})

  

  # ----------------------
  # Event routing
  # ----------------------

  def _register_event_handlers(self):
    # Map server event types to instance methods

    # ===== CONTROL EVENTS =====
    # Session and response lifecycle management
    self._router.register(OpenAIEventTypes.Server.CONVERSATION_ITEM_TRUNCATED, lambda e, raw: self._handle_conversation_truncated())
    self._router.register(OpenAIEventTypes.Server.RESPONSE_DONE, lambda e, raw: self._handle_response_done(raw))
    self._router.register(OpenAIEventTypes.Server.ERROR, lambda e, raw: self._handle_error(raw))

    # ===== INPUT-RELATED EVENTS =====
    # Speech detection and transcription
    self._router.register(OpenAIEventTypes.Server.INPUT_AUDIO_SPEECH_STARTED, lambda e, raw: self._handle_speech_started())
    self._router.register(OpenAIEventTypes.Server.INPUT_AUDIO_SPEECH_STOPPED, lambda e, raw: self._handle_speech_stopped())
    self._router.register(OpenAIEventTypes.Server.INPUT_AUDIO_TIMEOUT_TRIGGERED, lambda e, raw: self._handle_timeout_triggered())
    self._router.register(OpenAIEventTypes.Server.INPUT_TRANSCRIPT_DELTA, lambda e, raw: self._handle_input_transcript_delta(raw))
    self._router.register(OpenAIEventTypes.Server.INPUT_TRANSCRIPT_COMPLETED, lambda e, raw: self._handle_input_transcript_completed(raw))

    # ===== OUTPUT-RELATED EVENTS =====
    # Response generation and streaming
    self._router.register(OpenAIEventTypes.Server.RESPONSE_OUTPUT_ITEM_ADDED, lambda e, raw: self._handle_output_item_added(raw))
    self._router.register(OpenAIEventTypes.Server.RESPONSE_FUNCTION_ARGS_DELTA, lambda e, raw: self._handle_function_args_delta(raw))
    self._router.register(OpenAIEventTypes.Server.RESPONSE_FUNCTION_ARGS_DONE, lambda e, raw: self._handle_function_args_done(raw))
    self._router.register(OpenAIEventTypes.Server.RESPONSE_OUTPUT_ITEM_DONE, lambda e, raw: self._handle_output_item_done(raw))

    # Text output streaming
    self._router.register(OpenAIEventTypes.Server.RESPONSE_OUTPUT_TEXT_DELTA, lambda e, raw: self._handle_output_text_delta(raw))
    self._router.register(OpenAIEventTypes.Server.RESPONSE_OUTPUT_TEXT_DONE, lambda e, raw: self._handle_output_text_done(raw))

    # Audio output streaming
    self._router.register(OpenAIEventTypes.Server.OUTPUT_AUDIO_STARTED, lambda e, raw: self._handle_output_audio_started())
    self._router.register(OpenAIEventTypes.Server.RESPONSE_OUTPUT_AUDIO_DELTA, lambda e, raw: self._handle_output_audio_delta(raw))
    self._router.register(OpenAIEventTypes.Server.RESPONSE_OUTPUT_AUDIO_DONE, lambda e, raw: self._handle_output_audio_done(raw))
    self._router.register(OpenAIEventTypes.Server.OUTPUT_AUDIO_STOPPED, lambda e, raw: self._handle_output_audio_stopped())

    # Audio transcription (output transcription)
    self._router.register(OpenAIEventTypes.Server.RESPONSE_AUDIO_TRANSCRIPT_DELTA, lambda e, raw: self._handle_output_transcript_delta(raw))
    self._router.register(OpenAIEventTypes.Server.RESPONSE_AUDIO_TRANSCRIPT_DONE, lambda e, raw: self._handle_output_transcript_done(raw))

  # ===== CONTROL EVENT HANDLERS =====
  # Session and response lifecycle management

  def _handle_conversation_truncated(self) -> list[LlmResponse]:
    return [LlmResponse(interrupted=True, partial=True)]

  def _handle_response_done(
      self, event: dict | None = None
  ) -> list[LlmResponse]:
    return [
        LlmResponse(
            turn_complete=True,
            custom_metadata = event.get('response', {}).get('usage'),
        )
    ]

  def _handle_error(self, event: dict) -> list[LlmResponse]:
    err = event.get('error', {})
    return [
        LlmResponse(
            error_code=str(err.get('code') or 'OPENAI_ERROR'),
            error_message=err.get('message'),
        )
    ]

  # ===== INPUT EVENT HANDLERS =====
  # Speech detection and transcription

  def _handle_speech_started(self) -> list[LlmResponse]:
    return [
        LlmResponse(
            content=types.Content(
                role='SERVER', parts=[types.Part.from_text(text='SPEECH_START')]
            ),
            partial=True,
        )
    ]

  def _handle_speech_stopped(self) -> list[LlmResponse]:
    return [
        LlmResponse(
            content=types.Content(
                role='SERVER', parts=[types.Part.from_text(text='SPEECH_END')]
            ),
            partial=True,
        )
    ]

  def _handle_timeout_triggered(self) -> list[LlmResponse]:
    return [
        LlmResponse(
            content=types.Content(
                role='SERVER', parts=[types.Part.from_text(text='TIMEOUT')]
            ),
            partial=True,
        )
    ]

  def _handle_input_transcript_delta(self, event: dict) -> list[LlmResponse]:
    delta = event.get('delta', '')
    if not delta:
      return []
    return [
        LlmResponse(
            content=types.Content(
                role='user', parts=[types.Part.from_text(text=delta)]
            ),
            partial=True,
        )
    ]

  def _handle_input_transcript_completed(
      self, event: dict
  ) -> list[LlmResponse]:
    transcript = event.get('transcript', '')
    if not transcript:
      return []
    return [
        LlmResponse(
            content=types.Content(
                role='user', parts=[types.Part.from_text(text=transcript)]
            )
        )
    ]

  # ===== OUTPUT EVENT HANDLERS =====
  # Response generation and streaming

  def _handle_output_item_added(self, event: dict) -> list[LlmResponse]:
    item = event.get('item', {})
    if item.get('type') != 'function_call':
      return []
    name = item.get('name') or ''
    args_str = item.get('arguments') or '{}'
    try:
      args = json.loads(args_str)
    except Exception:
      args = {}
    item_id = item.get('id') or item.get('call_id') or ''
    self._pending_func_calls[item_id] = {
        'name': name,
        'args_buffer': (
            args_str if isinstance(args_str, str) else json.dumps(args)
        ),
    }
    # Defer emission until done
    return []

  def _handle_function_args_delta(self, event: dict) -> list[LlmResponse]:
    delta = event.get('delta', '')
    item_id = event.get('item_id') or event.get('id') or ''
    if item_id in self._pending_func_calls:
      self._pending_func_calls[item_id]['args_buffer'] += delta
    return []

  def _handle_function_args_done(self, event: dict) -> list[LlmResponse]:
    item_id = event.get('item_id') or event.get('id') or ''
    args_str = event.get('arguments', '')
    if item_id in self._pending_func_calls and isinstance(args_str, str):
      self._pending_func_calls[item_id]['args_buffer'] = args_str
    return []

  def _handle_output_item_done(self, event: dict) -> list[LlmResponse]:
    item = event.get('item', {})
    if item.get('type') != 'function_call':
      return []
    item_id = item.get('id') or item.get('call_id') or ''
    pending = self._pending_func_calls.pop(item_id, None)
    if not pending:
      return []
    try:
      args = json.loads(pending['args_buffer'] or '{}')
    except Exception:
      args = {}
    func_call = types.FunctionCall(name=pending['name'], args=args)
    func_call.id = item.get('call_id') or item.get('id')
    return [
        LlmResponse(
            content=types.Content(
                role='model', parts=[types.Part(function_call=func_call)]
            )
        )
    ]

  # Text output streaming
  def _handle_output_text_delta(self, event: dict) -> list[LlmResponse]:
    delta = event.get('delta', '')
    if not delta:
      return []
    content = types.Content(
        role='model', parts=[types.Part.from_text(text=delta)]
    )
    return [LlmResponse(content=content, partial=True)]

  def _handle_output_text_done(self, event: dict) -> list[LlmResponse]:
    text = event.get('text', '')
    if text:
      content = types.Content(
          role='model', parts=[types.Part.from_text(text=text)]
      )
      return [(LlmResponse(content=content))]

  # Audio output streaming
  def _handle_output_audio_started(self) -> list[LlmResponse]:
    return [
        LlmResponse(
            content=types.Content(
                role='SERVER', parts=[types.Part.from_text(text='TTS_START')]
            ),
            partial=True,
        )
    ]

  def _handle_output_audio_delta(self, event: dict) -> list[LlmResponse]:
    delta = event.get('delta', '')
    if not delta:
      return []
    try:
      audio_bytes = base64.b64decode(delta)
    except Exception:
      logger.warning('Invalid audio delta payload from OpenAI Realtime')
      return []
    content = types.Content(
        role='model',
        parts=[
            types.Part(
                inline_data=types.Blob(
                    data=audio_bytes,
                    mime_type='audio/pcm',
                )
            )
        ],
    )
    return [LlmResponse(content=content, partial=True)]


  def _handle_output_audio_stopped(self) -> list[LlmResponse]:
    return [
        LlmResponse(
            content=types.Content(
                role='SERVER', parts=[types.Part.from_text(text='TTS_END')]
            ),
            partial=True,
        )
    ]

  # Audio transcription (output transcription)
  def _handle_output_transcript_delta(self, event: dict) -> list[LlmResponse]:
    delta = event.get('delta', '')
    if not delta:
      return []
    return [
        LlmResponse(
            content=types.Content(
                role='model', parts=[types.Part.from_text(text=delta)]
            ),
            partial=True,
        )
    ]

  def _handle_output_transcript_done(self, event: dict) -> list[LlmResponse]:
    # Prefer server-provided transcript; fall back to buffered
    transcript = event.get('transcript', '')
    if not transcript:
      return []
    return [
        LlmResponse(
            content=types.Content(
                role='model', parts=[types.Part.from_text(text=transcript)]
            )
        )
    ]

  # Trimming helpers removed in revert
