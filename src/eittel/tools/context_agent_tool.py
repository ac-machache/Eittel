from __future__ import annotations

from typing import Any
import json

from google.genai import types
from typing_extensions import override

from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.agent_tool import AgentToolConfig
from google.adk.tools.tool_context import ToolContext
from google.adk.tools.tool_configs import ToolArgsConfig
from google.adk.tools._forwarding_artifact_service import ForwardingArtifactService


class ContextAgentTool(AgentTool):
  """Runs another agent within the current tool call.

  - Creates a lightweight child session to execute the embedded agent
  - Optionally seeds the child session with parent conversation context
  - Forwards artifacts and state updates back to the parent
  """

  def __init__(
      self,
      agent,
      *,
      skip_summarization: bool = False,
      inherit_parent_session: bool = False,
  ) -> None:
    super().__init__(agent=agent, skip_summarization=skip_summarization)
    self.inherit_parent_session: bool = inherit_parent_session

  @override
  async def run_async(
      self,
      *,
      args: dict[str, Any],
      tool_context: ToolContext,
  ) -> Any:
    from google.adk.agents.llm_agent import LlmAgent
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    if self.skip_summarization:
      tool_context.actions.skip_summarization = True

    if isinstance(self.agent, LlmAgent) and self.agent.input_schema:
      input_value = self.agent.input_schema.model_validate(args)
      content = types.Content(
          role='user',
          parts=[
              types.Part.from_text(
                  text=input_value.model_dump_json(exclude_none=True)
              )
          ],
      )
    else:
      req = args.get('request')
      if not isinstance(req, str) or not req.strip():
        req = 'Do what you are instructed to do'
      content = types.Content(
          role='user',
          parts=[types.Part.from_text(text=req)],
      )

    # Use parent's app_name, forward artifacts, keep memory/session lightweight
    runner = Runner(
        app_name=tool_context._invocation_context.app_name,
        agent=self.agent,
        artifact_service=ForwardingArtifactService(tool_context),
        session_service=InMemorySessionService(),
        memory_service=tool_context._invocation_context.memory_service,
        credential_service=tool_context._invocation_context.credential_service,
    )

    # Create a child session seeded with the parent's current state and user id.
    parent_ctx = tool_context._invocation_context
    session = await runner.session_service.create_session(
        app_name=tool_context._invocation_context.app_name,
        user_id=parent_ctx.user_id,
        state=tool_context.state.to_dict(),
    )

    # Optionally inherit parent session events so the embedded agent has context.
    if self.inherit_parent_session:
      parent_branch = parent_ctx.branch
      for parent_event in parent_ctx.session.events:
        if parent_branch and parent_event.branch and not parent_branch.startswith(parent_event.branch):
          continue
        event_copy = parent_event.model_copy(deep=True)
        if event_copy.actions and event_copy.actions.state_delta:
          event_copy.actions.state_delta = {}
        event_copy.author = self.agent.name
        await runner.session_service.append_event(session=session, event=event_copy)

    last_event = None
    async for event in runner.run_async(
        user_id=session.user_id, session_id=session.id, new_message=content
    ):
      # Forward state delta to parent session.
      if event.actions.state_delta:
        tool_context.state.update(event.actions.state_delta)
      last_event = event

    if not last_event or not last_event.content or not last_event.content.parts:
      return ''
    merged_text = '\n'.join(p.text for p in last_event.content.parts if p.text)
    if isinstance(self.agent, LlmAgent) and self.agent.output_schema:
      tool_result = self.agent.output_schema.model_validate_json(
          merged_text
      ).model_dump(exclude_none=True)
    else:
      tool_result = merged_text
    return tool_result

  @classmethod
  @override
  def from_config(
      cls, config: ToolArgsConfig, config_abs_path: str
  ) -> ContextAgentTool:
    from google.adk.agents import config_agent_utils

    agent_tool_config = AgentToolConfig.model_validate(config.model_dump())
    agent = config_agent_utils.resolve_agent_reference(
        agent_tool_config.agent, config_abs_path
    )
    return cls(
        agent=agent,
        skip_summarization=agent_tool_config.skip_summarization,
        inherit_parent_session=getattr(agent_tool_config, 'inherit_parent_session', False),
    )


