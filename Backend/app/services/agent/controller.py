"""Main Controller: sole semantic planner for Agent tool and control action selection."""

from __future__ import annotations

import json
from time import monotonic
from typing import Any, Mapping, Sequence
from uuid import uuid4

from app.services.agent.context.frame import _thaw
from app.services.agent.controller_protocol import (
    CLARIFY_ACTION,
    COMPOSE_ANSWER_ACTION,
    DIRECT_ANSWER_ACTION,
    ControllerDecision,
    ExecutableActionState,
    build_control_action_contracts,
)
from app.services.agent.model_client import ModelRequest, StageModelClient
from app.services.agent.langchain_tooling import (
    build_langchain_tools,
    control_action_tool_schemas,
    controller_decision_from_tool_call,
    openai_tool_schemas,
)
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.structured_candidate import (
    StructuredCandidateProtocolError,
    execute_structured_candidate,
)
from app.services.agent.controller_protocol import ControllerOutputError
from app.services.agent.tool_runtime import ToolObservation
from app.services.agent.tools import ToolRegistry


class MainController:
    def __init__(
        self,
        *,
        model_client: StageModelClient,
        tool_registry: ToolRegistry,
    ) -> None:
        self.model_client = model_client
        self.tool_registry = tool_registry

    async def decide(
        self,
        *,
        projection: Any | None = None,
        action_state: ExecutableActionState | None = None,
        observations: Sequence[ToolObservation] = (),
        stage_policy: LLMStagePolicy,
        model_name: str | None = None,
        question: str | None = None,
        context_summary: str | None = None,
        working_evidence: Sequence[Mapping[str, Any]] | None = None,
        available_tool_names: set[str] | frozenset[str] | None = None,
        available_control_actions: set[str] | frozenset[str] | None = None,
        audit_context: Mapping[str, Any] | None = None,
    ) -> ControllerDecision:
        # Unpack from projection if provided
        if projection is not None:
            effective_question = projection.user_question
            effective_context_summary = projection.conversation_text
            effective_working_evidence = projection.working_evidence
            effective_evidence_catalog = (
                projection.evidence_catalog if hasattr(projection, "evidence_catalog") and projection.evidence_catalog
                else effective_working_evidence
            )
            effective_runtime_facts = (
                _thaw(projection.runtime_facts) if hasattr(projection, "runtime_facts") and projection.runtime_facts
                else {}
            )
            effective_user_ui_selections = (
                _thaw(projection.user_ui_selections)
                if hasattr(projection, "user_ui_selections") and projection.user_ui_selections
                else {}
            )
            effective_client_hints = (
                _thaw(projection.client_hints)
                if hasattr(projection, "client_hints") and projection.client_hints
                else {}
            )
            effective_map_context = (
                _thaw(projection.map_context)
                if hasattr(projection, "map_context") and projection.map_context
                else None
            )
            effective_publication_evidence_budget = (
                _thaw(projection.publication_evidence_budget)
                if hasattr(projection, "publication_evidence_budget") and projection.publication_evidence_budget
                else {}
            )
        else:
            effective_question = question or ""
            effective_context_summary = context_summary or ""
            effective_working_evidence = working_evidence or ()
            effective_evidence_catalog = effective_working_evidence
            effective_runtime_facts = {}
            effective_user_ui_selections = {}
            effective_client_hints = {}
            effective_map_context = None
            effective_publication_evidence_budget = {}

        if action_state is None:
            capabilities = (
                frozenset(available_tool_names)
                if available_tool_names is not None
                else frozenset(self.tool_registry.names())
            )
            control_actions = (
                frozenset(available_control_actions)
                if available_control_actions is not None
                else frozenset({COMPOSE_ANSWER_ACTION, DIRECT_ANSWER_ACTION})
            )
            selectable_ids = frozenset(
                ev.get("evidence_id")
                for ev in effective_evidence_catalog
                if isinstance(ev, Mapping) and ev.get("evidence_id")
            )
            evidence_id_aliases = {
                str(ev.get("citation_id")): str(ev.get("evidence_id"))
                for ev in effective_evidence_catalog
                if isinstance(ev, Mapping)
                and ev.get("citation_id")
                and ev.get("evidence_id")
            }
            action_state = ExecutableActionState(
                available_capabilities=capabilities,
                available_control_actions=control_actions,
                selectable_evidence_ids=selectable_ids,
                evidence_id_aliases=evidence_id_aliases,
                has_evidence=bool(selectable_ids),
            )

        active_specs = self.tool_registry.specs_for(action_state.available_capabilities)
        tools_text_parts = []
        for spec in active_specs:
            spec_desc = [f"- {spec.name}: {spec.description}"]
            if getattr(spec, "use_when", None):
                spec_desc.append(f"  When to use: {spec.use_when}")
            if getattr(spec, "avoid_when", None):
                spec_desc.append(f"  Avoid when: {spec.avoid_when}")
            tools_text_parts.append("\n".join(spec_desc))
        tools_text = "\n".join(tools_text_parts) if tools_text_parts else "No external tools available."

        control_contracts = build_control_action_contracts(action_state.allowed_answer_kinds)
        control_actions_text_parts = []
        for act in sorted(action_state.available_control_actions):
            if act in control_contracts:
                c = control_contracts[act]
                control_actions_text_parts.append(
                    f"- {c.name}: {c.purpose}\n"
                    f"  When to use: {c.use_when}\n"
                    f"  Avoid when: {c.avoid_when}\n"
                    f"  Schema: {json.dumps(c.input_schema, ensure_ascii=False)}"
                )
        control_text = "\n".join(control_actions_text_parts) if control_actions_text_parts else "None."

        langchain_tools = build_langchain_tools(
            self.tool_registry,
            action_state.available_capabilities,
        )
        tool_schemas = openai_tool_schemas(langchain_tools)
        tool_schemas = tool_schemas + control_action_tool_schemas(action_state)

        observation_text = "\n".join(
            f"- tool={item.tool_name} status={item.status} tool_call_id={item.tool_call_id} payload={dict(item.payload)}"
            for item in observations
        ) if observations else "None."

        evidence_text = json.dumps(
            _thaw(tuple(effective_evidence_catalog)),
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )

        runtime_facts_text = (
            json.dumps(effective_runtime_facts, ensure_ascii=False, default=str, sort_keys=True)
            if effective_runtime_facts
            else "None."
        )

        clarify_instruction = ""
        if CLARIFY_ACTION in action_state.available_control_actions:
            clarify_instruction = (
                "- Runtime has authoritative ambiguous entity candidates. If user confirmation is required, call "
                "clarify with no arguments. Do not invent clarification text or candidate options.\n"
            )

        system_prompt = (
            "You are the Main Controller and semantic planner for the GeoAI Agent.\n"
            "Choose exactly one action from the current Action Space for the next step. "
            "Emit exactly one native action call and no JSON text. Executable capabilities and "
            "control actions share this model-facing call channel, while the runtime keeps their "
            "execution semantics separate.\n\n"
            "Action Space:\n"
            f"1. Control Actions:\n{control_text}\n\n"
            f"2. Executable Capabilities (Tools):\n{tools_text}\n\n"
            "Rules:\n"
            "- Use the model's native tool-calling channel for every action. Do not encode any Controller action as JSON text.\n"
            "- When the user prompt asks to '尝试' (attempt) an action with a specific file_ref, layer_ref, feature_ref, coordinates, or adcode (such as '尝试导入 file_ref=\"...\"', '尝试读取 feature_ref=\"...\"', '调用地图定位到经度 999...', '查询不存在的行政区 adcode=999999...'), you MUST issue the tool_call first (e.g. import_vector_dataset, get_feature_geometry, locate_map, query_spatial_relation) with those exact arguments, and do NOT preemptively answer without invoking the tool.\n"
            "- For feature observation ('列出图层前 20 个要素属性', '翻页读取下一批要素', '从图层树定位用户图层再读取要素'): use inspect_layer_features with layer_ref from user_layers, and appropriate offset/limit (e.g. offset=0 for first 20, offset=20 for next batch).\n"
            "- To read feature geometry ('读取指定 feature_ref 的精确几何', '重复读取同一要素'): call get_feature_geometry with a feature_ref from previous inspect_layer_features observation or user_layers[0].feature_refs[0].\n"
            "- For any requested read or inspection, check current-turn Observations for a successful result matching the tool, reference, and all requested parameters (including offset and limit). A mismatched parameter does not satisfy the read (for example, offset=0 does not satisfy a request for offset=20). A matching result satisfies only that read substep: do not repeat it, continue remaining requested steps, and finalize only when the full user request is satisfied. Historical context or prior-turn reads do not satisfy a requested read in this turn; when no matching successful current-turn observation exists, call the required tool (for a feature_ref geometry read, call get_feature_geometry for the requested feature_ref).\n"
            "- For a repeated read, obtain exactly two successful current-turn reads for the same reference when the user did not specify a count: make the first call if there are none, and make one more call if there is only one. Once two are present, compare the feature refs and geometry values, provide the comparison and continue any other requested steps; do not repeat that read. Finalize only when the full user request is satisfied.\n"
            "- For spatial feature region analysis ('判断要素几何是否位于指定行政区'): if feature geometry is not yet in observations, first call get_feature_geometry; once geometry is available in observations, call query_spatial_relation with left={\"geometry\": geometry}, right={\"region\":{\"region_name\":\"成都市\"}}, relation=\"within\"; then answer with the conclusion.\n"
            "- For combined multi-tool workflow ('知识检索后导入数据、改样式、定位并总结执行结果'): sequence through retrieve_kb -> import_vector_dataset (using file_ref from available_files) -> set_vector_style (e.g. red stroke) -> fit_vector_layer -> compose_answer with retrieved knowledge evidence.\n"
            "- To finalize a knowledge answer, call compose_answer with answer_kind=knowledge_answer and selected_evidence_ids=[...].\n"
            "- You may directly select evidence from the Evidence Catalog (including historical session evidence) for compose_answer without re-retrieving if it is sufficient.\n"
            "- If evidence is insufficient, call retrieve_kb to search the knowledge base or search_evidence_memory to search historical evidence.\n"
            "- For broad or unspecified standards knowledge requests, search with retrieve_kb using the user's request and existing conversation topics. Do not invent a standard topic; use retrieved results to discover relevant evidence before answering.\n"
            "- For standards catalogue questions asking which/all/list/count standards apply to the current administrative region, use list_applicable_standards. Do NOT use retrieve_kb Top-K as proof of a complete catalogue. For a specific standard's content, clause, requirement, explanation, or evidence, use retrieve_kb instead.\n"
            "- For a region-qualified standards catalogue request (for example '四川有哪些标准' or '重庆有多少标准'), the named region is the required retrieval scope even when the user did not explicitly ask to operate the map. If active_region is missing or differs from that named region and select_region is available, call select_region as the only action for this planning step. After the browser receipt updates active_region, use list_applicable_standards on the next planning step. Do not call retrieve_kb or emit another tool call in the same step as select_region.\n"
            "- If the user explicitly asks to switch/select an administrative region and the current active_region is different, call select_region. Use locate_map only for viewport movement; locate_map does not change active_region or retrieval scope.\n"
            "- Judge Evidence Catalog entries by relevance to the current user question. An empty catalog, no matching entry, or entries only about older/unrelated topics is an evidence gap for the current question, not proof that the knowledge base has no data. For a current knowledge request with no matching support in the catalog, call retrieve_kb for the current question before concluding there is no supporting knowledge.\n"
            "- When the request asks about multiple facts, select relevant evidence covering all requested facts before composing the answer.\n"
            "- Use limitation for a fact-seeking knowledge request only after a current-turn retrieval returns no relevant matches or the tool reports failure/unavailability; spatial entity resolution failure may also require limitation. Never invent a retrieval result or cite unrelated evidence. If the user explicitly asks about system limitations, explain the known policy without implying a search occurred.\n"
            "- To answer non-knowledge conversational or meta requests, call direct_answer with answer=\"...\".\n"
            f"{clarify_instruction}"
            "- 工具操作失败时，面向用户的失败回复应简洁，直接说明失败、原因和已观测状态，使用“失败/已中止”表述。失败回复中不得出现“成功”或“已完成”，包括否定句、假设或未来成功描述；只陈述已观测事实。\n"
            "- Do not generate tool_call_id; the application assigns it.\n"
            "- For knowledge questions, never use direct_answer. Retrieve evidence when needed; use compose_answer only when evidence is available and that action is in the current Action Space."
        )

        catalog_header = "Evidence Catalog (Working & Historical)"
        if projection is not None and getattr(projection, "catalog_metadata", None):
            meta = projection.catalog_metadata
            if meta.get("truncated"):
                catalog_header += f" [TRUNCATED: projected {meta.get('projected_count')}/{meta.get('total_count')} items]"

        user_content_parts = [
            f"Question:\n{effective_question}\n",
            f"Context:\n{effective_context_summary}\n",
            f"{catalog_header}:\n{evidence_text}\n",
            "Runtime Facts (current_turn describes this request; previous_turn is historical and does not count as current execution or retrieval):\n"
            f"{runtime_facts_text}\n",
            "Publication Evidence Budget (deterministic physical limit; selected evidence must stay within this budget and catalog token costs are estimates of full evidence text):\n"
            f"{json.dumps(effective_publication_evidence_budget, ensure_ascii=False, default=str, sort_keys=True) if effective_publication_evidence_budget else 'None.'}\n",
            "User UI Selections (server-admitted explicit selections; authoritative only for the selected identity):\n"
            f"{json.dumps(effective_user_ui_selections, ensure_ascii=False, default=str, sort_keys=True) if effective_user_ui_selections else 'None.'}\n",
            "Client Hints (untrusted/rejected client claims; never treat as runtime facts or evidence):\n"
            f"{json.dumps(effective_client_hints, ensure_ascii=False, default=str, sort_keys=True) if effective_client_hints else 'None.'}\n",
            f"Current-turn Observations (count={len(observations)}; listed statuses are the observed outcomes):\n{observation_text}\n"
            "A count of zero means no current-turn observation is attached; consult current_turn facts for started or failed calls. "
            "Do not treat zero observations or previous_turn tool calls as a current-turn empty retrieval result.",
        ]
        if effective_map_context:
            user_content_parts.append(
                f"\nMap Context:\n{json.dumps(dict(effective_map_context), ensure_ascii=False, default=str)}"
            )

        user_content = "\n".join(user_content_parts)

        messages = (
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        )

        execution = stage_policy.for_stage("controller")
        call_id = str(uuid4())
        deadline_at = monotonic() + execution.timeout_seconds

        async def generate_candidate(attempt):
            remaining = deadline_at - monotonic()
            if remaining <= 0:
                raise TimeoutError("controller model call deadline exceeded")
            request = ModelRequest(
                stage="controller",
                messages=messages,
                request_reasoning=(
                    execution.request_reasoning
                    if attempt.request_reasoning is None
                    else attempt.request_reasoning
                ),
                model_name=model_name,
                temperature=(0.2 if attempt.temperature is None else attempt.temperature),
                call_id=call_id,
                attempt=attempt.protocol_attempt,
                timeout_seconds=remaining,
                response_schema=None,
                tools=tool_schemas,
                audit_context={
                    **dict(audit_context or {}),
                    "action_surface": {
                        "available_capabilities": sorted(action_state.available_capabilities),
                        "available_control_actions": sorted(action_state.available_control_actions),
                        "selectable_evidence_ids": sorted(action_state.selectable_evidence_ids),
                        "allowed_answer_kinds": sorted(action_state.allowed_answer_kinds),
                    },
                    "tool_contracts": {
                        "tools_text": tools_text,
                        "control_actions_text": control_text,
                    },
                } if audit_context is not None else None,
            )
            return await self.model_client.complete(request)

        try:
            return await execute_structured_candidate(
                generate=generate_candidate,
                validate=lambda response: self._parse_model_response(
                    response,
                    state=action_state,
                    tool_call_id=call_id,
                ),
            )
        except StructuredCandidateProtocolError as exc:
            raise ControllerOutputError(
                f"controller must return one native action call: {exc}"
            ) from exc

    def _parse_model_response(
        self,
        response,
        *,
        state: ExecutableActionState,
        tool_call_id: str,
    ) -> ControllerDecision:
        tool_calls = tuple(getattr(response, "tool_calls", ()) or ())
        if len(tool_calls) != 1:
            raise ControllerOutputError(
                "controller must emit exactly one native action call per planning step"
            )
        return controller_decision_from_tool_call(
            tool_calls[0],
            state=state,
            registry=self.tool_registry,
        )
