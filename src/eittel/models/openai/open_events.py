from __future__ import annotations


from typing import Any, Callable, Optional, TypeAlias, Union

from pydantic import BaseModel, ConfigDict, Field


class OpenAIEventTypes:
  """String constants for OpenAI Realtime event types.

  Split into client->server control events and server->client events.
  """

  class Client:
    SESSION_UPDATE = 'session.update'
    CONVERSATION_ITEM_CREATE = 'conversation.item.create'
    CONVERSATION_ITEM_DELETE = 'conversation.item.delete'
    CONVERSATION_ITEM_TRUNCATE = 'conversation.item.truncate'
    INPUT_AUDIO_BUFFER_APPEND = 'input_audio_buffer.append'
    INPUT_AUDIO_BUFFER_COMMIT = 'input_audio_buffer.commit'
    INPUT_AUDIO_BUFFER_CLEAR = 'input_audio_buffer.clear'
    RESPONSE_CREATE = 'response.create'
    RESPONSE_CANCEL = 'response.cancel'
    OUTPUT_AUDIO_BUFFER_CLEAR = 'output_audio_buffer.clear'

  class Server:
    SESSION_CREATED = 'session.created'
    SESSION_UPDATED = 'session.updated'
    RATE_LIMITS_UPDATED = 'rate_limits.updated'

    # Conversation items and transcription
    CONVERSATION_ITEM_CREATED = 'conversation.item.created'
    CONVERSATION_ITEM_TRUNCATED = 'conversation.item.truncated'
    INPUT_TRANSCRIPT_DELTA = 'conversation.item.input_audio_transcription.delta'
    INPUT_TRANSCRIPT_COMPLETED = 'conversation.item.input_audio_transcription.completed'

    # Input audio state
    INPUT_AUDIO_SPEECH_STARTED = 'input_audio_buffer.speech_started'
    INPUT_AUDIO_SPEECH_STOPPED = 'input_audio_buffer.speech_stopped'
    INPUT_AUDIO_COMMITTED = 'input_audio_buffer.committed'
    INPUT_AUDIO_TIMEOUT_TRIGGERED = 'input_audio_buffer.timeout_triggered'

    # Response lifecycle and streaming
    RESPONSE_CREATED = 'response.created'
    RESPONSE_TEXT_DELTA = 'response.text.delta'
    RESPONSE_OUTPUT_TEXT_DELTA = 'response.output_text.delta'
    RESPONSE_OUTPUT_TEXT_DONE = 'response.output_text.done'
    RESPONSE_OUTPUT_AUDIO_DELTA = 'response.audio.delta'
    RESPONSE_OUTPUT_AUDIO_DONE = 'response.output_audio.done'
    RESPONSE_AUDIO_TRANSCRIPT_DELTA = 'response.audio_transcript.delta'
    RESPONSE_AUDIO_TRANSCRIPT_DONE = 'response.audio_transcript.done'
    RESPONSE_FUNCTION_ARGS_DELTA = 'response.function_call_arguments.delta'
    RESPONSE_FUNCTION_ARGS_DONE = 'response.function_call_arguments.done'
    RESPONSE_OUTPUT_ITEM_ADDED = 'response.output_item.added'
    RESPONSE_OUTPUT_ITEM_DONE = 'response.output_item.done'
    RESPONSE_DONE = 'response.done'

    # Output audio buffer state
    OUTPUT_AUDIO_STARTED = 'output_audio_buffer.started'
    OUTPUT_AUDIO_STOPPED = 'output_audio_buffer.stopped'
    OUTPUT_AUDIO_CLEARED = 'output_audio_buffer.cleared'

    # Error
    ERROR = 'error'


# ------------------------------
# Pydantic models (server events)
# ------------------------------


class ServerEvent(BaseModel):
  """Base model for server-sent events. Allows vendor extras to pass through."""

  type: str

  model_config = ConfigDict(extra='allow')


class ResponseTextDelta(ServerEvent):
  type: str = Field(default=OpenAIEventTypes.Server.RESPONSE_TEXT_DELTA)
  delta: str | None = None


class ResponseOutputTextDelta(ServerEvent):
  type: str = Field(default=OpenAIEventTypes.Server.RESPONSE_OUTPUT_TEXT_DELTA)
  delta: str | None = None


class ResponseOutputTextDone(ServerEvent):
  type: str = Field(default=OpenAIEventTypes.Server.RESPONSE_OUTPUT_TEXT_DONE)
  text: str | None = None


class ResponseOutputAudioDelta(ServerEvent):
  type: str = Field(default=OpenAIEventTypes.Server.RESPONSE_OUTPUT_AUDIO_DELTA)
  delta: str | None = None


class ResponseOutputAudioDone(ServerEvent):
  type: str = Field(default=OpenAIEventTypes.Server.RESPONSE_OUTPUT_AUDIO_DONE)



class ResponseAudioTranscriptDelta(ServerEvent):
  type: str = Field(
      default=OpenAIEventTypes.Server.RESPONSE_AUDIO_TRANSCRIPT_DELTA
  )
  delta: str | None = None


class ResponseAudioTranscriptDone(ServerEvent):
  type: str = Field(
      default=OpenAIEventTypes.Server.RESPONSE_AUDIO_TRANSCRIPT_DONE
  )
  transcript: str | None = None


class InputTranscriptDelta(ServerEvent):
  type: str = Field(default=OpenAIEventTypes.Server.INPUT_TRANSCRIPT_DELTA)
  delta: str | None = None
  item_id: str | None = None


class InputTranscriptCompleted(ServerEvent):
  type: str = Field(
      default=OpenAIEventTypes.Server.INPUT_TRANSCRIPT_COMPLETED
  )
  transcript: str | None = None
  item_id: str | None = None


class InputAudioSpeechStarted(ServerEvent):
  type: str = Field(
      default=OpenAIEventTypes.Server.INPUT_AUDIO_SPEECH_STARTED
  )


class InputAudioSpeechStopped(ServerEvent):
  type: str = Field(
      default=OpenAIEventTypes.Server.INPUT_AUDIO_SPEECH_STOPPED
  )


class InputAudioCommitted(ServerEvent):
  type: str = Field(default=OpenAIEventTypes.Server.INPUT_AUDIO_COMMITTED)


class InputAudioTimeoutTriggered(ServerEvent):
  type: str = Field(
      default=OpenAIEventTypes.Server.INPUT_AUDIO_TIMEOUT_TRIGGERED
  )


class ConversationItemTruncated(ServerEvent):
  type: str = Field(
      default=OpenAIEventTypes.Server.CONVERSATION_ITEM_TRUNCATED
  )


class ResponseOutputItemAdded(ServerEvent):
  type: str = Field(
      default=OpenAIEventTypes.Server.RESPONSE_OUTPUT_ITEM_ADDED
  )
  item: dict[str, Any] | None = None


class ResponseFunctionCallArgumentsDelta(ServerEvent):
  type: str = Field(
      default=OpenAIEventTypes.Server.RESPONSE_FUNCTION_ARGS_DELTA
  )
  delta: str | None = None
  item_id: str | None = None


class ResponseFunctionCallArgumentsDone(ServerEvent):
  type: str = Field(
      default=OpenAIEventTypes.Server.RESPONSE_FUNCTION_ARGS_DONE
  )
  arguments: str | None = None
  item_id: str | None = None


class ResponseOutputItemDone(ServerEvent):
  type: str = Field(
      default=OpenAIEventTypes.Server.RESPONSE_OUTPUT_ITEM_DONE
  )
  item: dict[str, Any] | None = None


class ResponseDone(ServerEvent):
  type: str = Field(default=OpenAIEventTypes.Server.RESPONSE_DONE)
  response: dict[str, Any] | None = None


class OutputAudioStarted(ServerEvent):
  type: str = Field(default=OpenAIEventTypes.Server.OUTPUT_AUDIO_STARTED)


class OutputAudioStopped(ServerEvent):
  type: str = Field(default=OpenAIEventTypes.Server.OUTPUT_AUDIO_STOPPED)


class OutputAudioCleared(ServerEvent):
  type: str = Field(default=OpenAIEventTypes.Server.OUTPUT_AUDIO_CLEARED)


class ErrorEvent(ServerEvent):
  type: str = Field(default=OpenAIEventTypes.Server.ERROR)
  error: dict[str, Any] | None = None


ServerEventUnion: TypeAlias = Union[
  ResponseTextDelta,
  ResponseOutputTextDelta,
  ResponseOutputAudioDelta,
  ResponseOutputTextDone,
  ResponseOutputAudioDone,
  ResponseAudioTranscriptDelta,
  ResponseAudioTranscriptDone,
  InputTranscriptDelta,
  InputTranscriptCompleted,
  InputAudioSpeechStarted,
  InputAudioSpeechStopped,
  InputAudioCommitted,
  InputAudioTimeoutTriggered,
  ConversationItemTruncated,
  ResponseOutputItemAdded,
  ResponseFunctionCallArgumentsDelta,
  ResponseFunctionCallArgumentsDone,
  ResponseOutputItemDone,
  ResponseDone,
  OutputAudioStarted,
  OutputAudioStopped,
  OutputAudioCleared,
  ErrorEvent,
]


_EVENT_TYPE_TO_MODEL: dict[str, type[ServerEvent]] = {
  OpenAIEventTypes.Server.RESPONSE_TEXT_DELTA: ResponseTextDelta,
  OpenAIEventTypes.Server.RESPONSE_OUTPUT_TEXT_DELTA: ResponseOutputTextDelta,
  OpenAIEventTypes.Server.RESPONSE_OUTPUT_AUDIO_DELTA: ResponseOutputAudioDelta,
  OpenAIEventTypes.Server.RESPONSE_OUTPUT_TEXT_DONE: ResponseOutputTextDone,
  OpenAIEventTypes.Server.RESPONSE_OUTPUT_AUDIO_DONE: ResponseOutputAudioDone,
  OpenAIEventTypes.Server.RESPONSE_AUDIO_TRANSCRIPT_DELTA: ResponseAudioTranscriptDelta,
  OpenAIEventTypes.Server.RESPONSE_AUDIO_TRANSCRIPT_DONE: ResponseAudioTranscriptDone,
  OpenAIEventTypes.Server.INPUT_TRANSCRIPT_DELTA: InputTranscriptDelta,
  OpenAIEventTypes.Server.INPUT_TRANSCRIPT_COMPLETED: InputTranscriptCompleted,
  OpenAIEventTypes.Server.INPUT_AUDIO_SPEECH_STARTED: InputAudioSpeechStarted,
  OpenAIEventTypes.Server.INPUT_AUDIO_SPEECH_STOPPED: InputAudioSpeechStopped,
  OpenAIEventTypes.Server.INPUT_AUDIO_COMMITTED: InputAudioCommitted,
  OpenAIEventTypes.Server.INPUT_AUDIO_TIMEOUT_TRIGGERED: InputAudioTimeoutTriggered,
  OpenAIEventTypes.Server.CONVERSATION_ITEM_TRUNCATED: ConversationItemTruncated,
  OpenAIEventTypes.Server.RESPONSE_OUTPUT_ITEM_ADDED: ResponseOutputItemAdded,
  OpenAIEventTypes.Server.RESPONSE_FUNCTION_ARGS_DELTA: ResponseFunctionCallArgumentsDelta,
  OpenAIEventTypes.Server.RESPONSE_FUNCTION_ARGS_DONE: ResponseFunctionCallArgumentsDone,
  OpenAIEventTypes.Server.RESPONSE_OUTPUT_ITEM_DONE: ResponseOutputItemDone,
  OpenAIEventTypes.Server.RESPONSE_DONE: ResponseDone,
  OpenAIEventTypes.Server.OUTPUT_AUDIO_STARTED: OutputAudioStarted,
  OpenAIEventTypes.Server.OUTPUT_AUDIO_STOPPED: OutputAudioStopped,
  OpenAIEventTypes.Server.OUTPUT_AUDIO_CLEARED: OutputAudioCleared,
  OpenAIEventTypes.Server.ERROR: ErrorEvent,
}


def parse_server_event(event: dict[str, Any]) -> ServerEvent:
  """Parse a raw server event dict into a typed Pydantic model.

  If no specific model exists for the given type, fall back to ServerEvent.
  """
  etype = event.get('type')
  model_cls = _EVENT_TYPE_TO_MODEL.get(etype)
  if model_cls is None:
    return ServerEvent(**event)
  return model_cls(**event)


class OpenAIEventRouter:
  """Simple router that maps event.type to registered handler callables.

  Handlers receive the typed Pydantic event and the original payload.
  """

  def __init__(self):
    self._handlers: dict[str, Callable[[ServerEvent, dict[str, Any]], list[Any]]] = {}

  def register(self, event_type: str, handler: Callable[[ServerEvent, dict[str, Any]], list[Any]]):
    self._handlers[event_type] = handler

  def dispatch(self, event: dict[str, Any]) -> list[Any]:
    if not isinstance(event, dict):
      return []
    typed = parse_server_event(event)
    handler = self._handlers.get(typed.type)
    if handler is None:
      return []
    return handler(typed, event)


