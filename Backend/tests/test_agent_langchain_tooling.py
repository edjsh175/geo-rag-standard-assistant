from __future__ import annotations

import pytest

from app.services.agent.controller_protocol import ExecutableActionState, TOOL_CALL_ACTION
from app.services.agent.langchain_tooling import (
    build_langchain_tools,
    controller_decision_from_tool_call,
    openai_tool_schemas,
)
from app.services.agent.tools import (
    LocateMapInput,
    RetrieveKbInput,
    build_default_tool_registry,
)


def test_langchain_tool_surface_reuses_registry_pydantic_contracts() -> None:
    registry = build_default_tool_registry()

    tools = build_langchain_tools(
        registry,
        frozenset({"retrieve_kb", "locate_map"}),
    )

    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == {"retrieve_kb", "locate_map"}
    assert by_name["retrieve_kb"].args_schema is RetrieveKbInput
    assert by_name["locate_map"].args_schema is LocateMapInput
    assert by_name["retrieve_kb"].args_schema.model_json_schema() == registry.get(
        "retrieve_kb"
    ).input_schema


def test_langchain_tool_cannot_execute_outside_geoai_tool_runtime() -> None:
    registry = build_default_tool_registry()
    tool = build_langchain_tools(registry, frozenset({"retrieve_kb"}))[0]

    with pytest.raises(RuntimeError, match="GeoAI ToolRuntime"):
        tool.invoke({"query": "滑坡监测"})


def test_standard_tool_call_is_adapted_to_canonical_controller_decision() -> None:
    registry = build_default_tool_registry()
    state = ExecutableActionState(
        available_capabilities=frozenset({"retrieve_kb"}),
        available_control_actions=frozenset(),
        has_evidence=False,
    )

    decision = controller_decision_from_tool_call(
        {
            "name": "retrieve_kb",
            "args": {"query": "重庆滑坡监测"},
            "id": "call-native-1",
            "type": "tool_call",
        },
        state=state,
        registry=registry,
    )

    assert decision.action == TOOL_CALL_ACTION
    assert decision.tool == "retrieve_kb"
    assert decision.arguments == {"query": "重庆滑坡监测"}
    assert decision.tool_call_id == "call-native-1"


def test_standard_tool_call_is_rejected_when_capability_not_currently_executable() -> None:
    registry = build_default_tool_registry()
    state = ExecutableActionState(
        available_capabilities=frozenset(),
        available_control_actions=frozenset(),
        has_evidence=False,
    )

    with pytest.raises(ValueError, match="not available in current state"):
        controller_decision_from_tool_call(
            {
                "name": "retrieve_kb",
                "args": {"query": "重庆滑坡监测"},
                "id": "call-native-2",
                "type": "tool_call",
            },
            state=state,
            registry=registry,
        )


def test_openai_tool_schemas_are_generated_from_langchain_tools() -> None:
    registry = build_default_tool_registry()
    tools = build_langchain_tools(registry, frozenset({"retrieve_kb"}))

    schemas = openai_tool_schemas(tools)

    assert len(schemas) == 1
    schema = schemas[0]
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "retrieve_kb"
    parameters = schema["function"]["parameters"]
    assert parameters["type"] == "object"
    assert parameters["required"] == ["query"]
    assert parameters["properties"]["query"]["type"] == "string"
    assert parameters["properties"]["query"]["minLength"] == 1


def test_geosql_langchain_schema_exposes_plan_not_sql_text() -> None:
    registry = build_default_tool_registry()
    tools = build_langchain_tools(registry, frozenset({"query_geospatial_data"}))
    assert len(tools) == 1
    schema = tools[0].args_schema.model_json_schema()
    assert "operation" in schema["properties"]
    assert "target_table" in schema["properties"]
    assert "sql" not in schema["properties"]
