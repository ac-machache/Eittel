from __future__ import annotations

from typing import Any, Dict, List

from google.genai import types


_TYPE_MAP: dict[str, str] = {
    'OBJECT': 'object',
    'STRING': 'string',
    'INTEGER': 'integer',
    'NUMBER': 'number',
    'BOOLEAN': 'boolean',
    'ARRAY': 'array',
}


def adk_schema_to_openai_json_schema(
    schema: types.Schema | dict | None,
) -> Dict[str, Any]:
  """Convert ADK/GenAI Schema to OpenAI JSON Schema for function tools."""
  if schema is None:
    return {}
  if isinstance(schema, dict):
    return schema

  json_schema: dict[str, Any] = {}

  # Map type enum/name to JSON Schema type
  stype = None
  try:
    stype = schema.type
  except Exception:
    stype = None
  if stype is not None:
    key: str | None = None
    if isinstance(stype, str):
      key = stype
    elif hasattr(stype, 'value'):
      key = stype.value
    elif hasattr(stype, 'name'):
      key = stype.name
    else:
      key = str(stype).split('.')[-1]
    mapped = _TYPE_MAP.get((key or '').upper(), None)
    if mapped:
      json_schema['type'] = mapped

  if getattr(schema, 'description', None):
    json_schema['description'] = schema.description

  if getattr(schema, 'enum', None):
    json_schema['enum'] = schema.enum

  properties = getattr(schema, 'properties', None)
  if properties and isinstance(properties, dict):
    props_obj: dict[str, Any] = {}
    for key, subschema in properties.items():
      props_obj[key] = adk_schema_to_openai_json_schema(subschema)
    json_schema['properties'] = props_obj
    if 'type' not in json_schema:
      json_schema['type'] = 'object'

  required = getattr(schema, 'required', None)
  if required and isinstance(required, list):
    json_schema['required'] = list(required)

  items = getattr(schema, 'items', None)
  if items:
    json_schema['items'] = adk_schema_to_openai_json_schema(items)

  return json_schema


def function_tools_to_openai_session_tools(
    tools: list[types.Tool | types.ToolDict] | None,
) -> List[Dict[str, Any]]:
  """Convert ADK function tools to OpenAI `session.tools` entries."""
  if not tools:
    return []
  converted: list[dict[str, Any]] = []
  for tool in tools:
    if not isinstance(tool, (types.Tool, types.ToolDict)):
      continue
    if not tool.function_declarations:
      continue
    for decl in tool.function_declarations:
      params_schema = (
          adk_schema_to_openai_json_schema(decl.parameters)
          if decl.parameters
          else {'type': 'object'}
      )
      converted.append({
          'type': 'function',
          'name': decl.name,
          'description': decl.description,
          'parameters': params_schema,
      })
  return converted