from __future__ import annotations

from app.services.agent.contracts import MapAction
from app.services.map_action_adapter import LegacyMapActionAdapter


def test_legacy_map_action_adapter_extracts_one_structured_action() -> None:
    answer = '四川省相关要求。\n```json\n{"adcode":"510000","name":"四川省"}\n```'

    adapted = LegacyMapActionAdapter().adapt(answer)

    assert adapted.answer == "四川省相关要求。"
    assert adapted.map_action == MapAction(
        type="focus_region",
        target="region",
        adcode="510000",
        name="四川省",
    )


def test_legacy_map_action_adapter_leaves_plain_answer_unchanged() -> None:
    adapted = LegacyMapActionAdapter().adapt("没有地图动作。")

    assert adapted.answer == "没有地图动作。"
    assert adapted.map_action is None
