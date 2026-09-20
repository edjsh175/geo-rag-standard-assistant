"""Compatibility adapter for legacy Markdown-embedded map actions."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

from app.services.agent.contracts import MapAction


@dataclass(frozen=True, slots=True)
class AdaptedAnswer:
    answer: str
    map_action: MapAction | None


class LegacyMapActionAdapter:
    _JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)

    def adapt(self, answer: str) -> AdaptedAnswer:
        match = self._JSON_BLOCK.search(answer or "")
        if not match:
            return AdaptedAnswer(answer=(answer or "").strip(), map_action=None)

        purified = self._JSON_BLOCK.sub("", answer or "").strip()
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return AdaptedAnswer(answer=purified, map_action=None)
        if not isinstance(payload, dict):
            return AdaptedAnswer(answer=purified, map_action=None)

        adcode = payload.get("adcode") or payload.get("ADCODE")
        name = (
            payload.get("name")
            or payload.get("NAME")
            or payload.get("province")
            or payload.get("city")
            or payload.get("region_name")
        )
        if adcode is None or not re.fullmatch(r"\d{6}", str(adcode)):
            return AdaptedAnswer(answer=purified, map_action=None)
        return AdaptedAnswer(
            answer=purified,
            map_action=MapAction(
                type="focus_region",
                target="region",
                adcode=str(adcode),
                name=str(name) if name is not None else None,
            ),
        )
