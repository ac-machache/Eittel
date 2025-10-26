# Expose realtime providers and allow explicit registration on demand
from contextvars import ContextVar

def enable_openai_realtime() -> None:
  """Enable OpenAI Realtime provider by importing its module."""
  try:
    from .openai import llm as _  # noqa: F401
  except Exception:
    pass

# Optional provider hook to compute per-request session overrides
_REALTIME_RUNCONFIG_PROVIDER = None

def realtime_runconfig(fn):
  """Decorator to register a function that returns per-run realtime settings."""
  set_realtime_runconfig_provider(fn)
  return fn

def set_realtime_runconfig_provider(fn):
  global _REALTIME_RUNCONFIG_PROVIDER
  _REALTIME_RUNCONFIG_PROVIDER = fn

def get_realtime_runconfig_provider():
  return _REALTIME_RUNCONFIG_PROVIDER

# Per-connection runtime context (no 'with' required)
_REALTIME_RUNTIME_CTX: ContextVar[dict | None] = ContextVar(
    'adk_community_realtime_runtime_ctx', default=None
)

def set_realtime_context(hints: dict) -> object:
  """Set ephemeral per-connection realtime hints; returns a reset token."""
  return _REALTIME_RUNTIME_CTX.set(hints)

def get_realtime_context() -> dict | None:
  return _REALTIME_RUNTIME_CTX.get()

def clear_realtime_context(token: object | None = None) -> None:
  if token is None:
    _REALTIME_RUNTIME_CTX.set(None)
  else:
    try:
      _REALTIME_RUNTIME_CTX.reset(token)
    except Exception:
      _REALTIME_RUNTIME_CTX.set(None)