from types import SimpleNamespace

import pytest

from app.services.agent.event_projection import public_event_payload
from app.services.agent.events import AgentEvent
from app.services.agent.session_service import AgentSessionService
from app.services.agent.store import InMemoryAgentStore


def test_nested_canonical_tool_inputs_keep_facts_without_arbitrary_data():
    style = public_event_payload('tool_started', {
        'tool_name': 'set_vector_style', 'arguments': {'layer_ref': 'layer-1', 'style': {
            'stroke': {'color': '#123456', 'width': 3, 'secret': 'hidden'},
            'fill': {'color': '#abcdef', 'opacity': 0.3}, 'radius': 7, 'secret': 'hidden'}}})
    assert style['arguments']['style'] == {
        'stroke': {'color': '#123456', 'width': 3},
        'fill': {'color': '#abcdef', 'opacity': 0.3}, 'radius': 7}
    spatial = public_event_payload('tool_started', {
        'tool_name': 'query_spatial_relation', 'arguments': {
            'left': {'region': {'adcode': '510100', 'secret': 'hidden'}},
            'right': {'geometry': {'type': 'Point', 'coordinates': [104, 30], 'secret': 'hidden'}},
            'relation': 'intersects'}})
    assert spatial['arguments']['left'] == {'region': {'adcode': '510100'}}
    assert spatial['arguments']['right'] == {'geometry': {'type': 'Point'}}
    assert 'hidden' not in str(spatial)


@pytest.mark.asyncio
async def test_public_session_history_filters_stored_audit_fields_and_preserves_final_citations():
    store = InMemoryAgentStore()
    principal, session_id = 'visitor:history-user', 'safe-history'
    await store.get_or_create_session(principal, session_id)
    for event_type, payload in [
        ('user_message', {'text': 'question'}),
        ('context_snapshot_persist_failed', {'error': 'provider_key=hidden'}),
        ('controller_decision', {'tool_name': 'retrieve_kb', 'arguments': {'secret': 'hidden'}}),
        ('answer_generated', {'citations': ['E1'], 'raw_prompt': 'hidden'}),
        ('publication_completed', {'state': 'published', 'citations': ['E2']}),
        ('assistant_message', {'text': 'Final answer [E2]'}),
    ]:
        await store.append_event(principal, AgentEvent(event_type=event_type, payload=payload,
            session_id=session_id, turn_id='turn-1', trace_id='trace-1'))
    async def evidence(*args, **kwargs):
        return [SimpleNamespace(document_id=f'doc-{i}', citation_id=f'E{i}',
            evidence_id=f'evidence-{i}', source='kb', title=f'Document {i}') for i in (1, 2)]
    store.list_evidence_items = evidence
    service = AgentSessionService(store)
    detail = await service.get_session_detail(principal_id=principal, session_id=session_id)
    assert 'hidden' not in str(detail)
    assert not any(event['event_type'] == 'context_snapshot_persist_failed'
                   for event in detail['turns'][0]['events'])
    assistant = next(message for message in detail['messages'] if message['role'] == 'assistant')
    assert [ref['document_id'] for ref in assistant['references']] == ['doc-2']
    # An explicitly empty final citation list remains authoritative.
    await store.append_event(principal, AgentEvent(event_type='publication_completed',
        payload={'state': 'published', 'citations': [], 'results': [{'id': 'old-document'}]}, session_id=session_id,
        turn_id='turn-1', trace_id='trace-1'))
    detail = await service.get_session_detail(principal_id=principal, session_id=session_id)
    assert next(message for message in detail['messages'] if message['role'] == 'assistant')['references'] == []


def test_geosql_public_tool_projection_redacts_raw_geometry_coordinates() -> None:
    payload = public_event_payload("tool_started", {
        "tool_name": "query_geospatial_data",
        "arguments": {
            "operation": "nearest",
            "target_table": "spatial_regions",
            "select_fields": ["adcode", "geometry"],
            "filters": [{"field": "region_name", "operator": "contains", "value": "Chengdu", "secret": "hidden"}],
            "spatial": {"geometry": {"type": "Point", "coordinates": [104, 30]}, "distance_m": 1000},
            "limit": 5,
        },
    })
    args = payload["arguments"]
    assert args["spatial"] == {"distance_m": 1000, "geometry": {"type": "Point"}}
    assert args["filters"] == [{"field": "region_name", "operator": "contains", "value": "Chengdu"}]
    assert "coordinates" not in str(payload)
    assert "hidden" not in str(payload)
