from __future__ import annotations

import os
from typing import Any, Protocol

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

from gridaware.agents.models import AgentRunTrace, AgentToolCallTrace
from gridaware.tool_executor import GridToolRuntime


DEFAULT_AGENT_MODEL = "gpt-4.1-mini"


class ResponsesClient(Protocol):
    @property
    def responses(self) -> Any: ...


class ResponsesRunResult(BaseModel):
    output_text: str
    trace: AgentRunTrace


def create_openai_client() -> OpenAI:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_API")
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY in .env before running agents.")
    return OpenAI(api_key=api_key)


def run_responses_agent(
    *,
    client: ResponsesClient,
    model: str,
    system_prompt: str,
    user_prompt: str,
    tools: list[dict[str, Any]],
    runtime: GridToolRuntime,
    text_format: dict[str, Any],
    max_tool_rounds: int = 4,
    initial_tool_choice: dict[str, Any] | None = None,
) -> ResponsesRunResult:
    allowed_tool_names = {tool["name"] for tool in tools}
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        tools=tools,
        text={"format": text_format},
        parallel_tool_calls=False,
        tool_choice=initial_tool_choice,
    )
    trace = AgentRunTrace(response_ids=[response.id])

    for _ in range(max_tool_rounds):
        function_calls = _function_calls(response)
        if not function_calls:
            return ResponsesRunResult(output_text=response.output_text, trace=trace)

        tool_outputs = []
        for call in function_calls:
            if call.name not in allowed_tool_names:
                raise RuntimeError(f"Agent requested disallowed tool: {call.name}")
            output = runtime.execute(call.name, call.arguments)
            trace.tool_calls.append(
                AgentToolCallTrace(name=call.name, arguments=call.arguments, output=output)
            )
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": output,
                }
            )

        response = client.responses.create(
            model=model,
            previous_response_id=response.id,
            input=tool_outputs,
            tools=tools,
            text={"format": text_format},
            parallel_tool_calls=False,
        )
        trace.response_ids.append(response.id)

    raise RuntimeError(f"Agent exceeded max_tool_rounds={max_tool_rounds}")


def json_schema_text_format(name: str, schema: dict[str, Any], description: str) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": name,
        "description": description,
        "schema": schema,
        "strict": True,
    }


def pydantic_strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    return _inline_schema_refs(model.model_json_schema())


def _function_calls(response: Any) -> list[Any]:
    return [item for item in response.output if item.type == "function_call"]


def _inline_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline local $defs because strict JSON schema support is intentionally narrow."""

    definitions = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.rsplit("/", 1)[-1]
                return resolve(definitions[name].copy())
            return {key: resolve(value) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)
