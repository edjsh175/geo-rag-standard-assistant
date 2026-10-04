"""Project authoritative browser region state into an ephemeral retrieval constraint."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.rag.contracts import StandardScopeConstraint


class RegionScopeProjector:
    @staticmethod
    def from_map_context(map_context: Mapping[str, Any] | None) -> StandardScopeConstraint | None:
        if not isinstance(map_context, Mapping):
            return None
        raw_region = map_context.get("active_region")
        if not isinstance(raw_region, Mapping):
            return None
        adcode = str(raw_region.get("adcode") or "").strip()
        name = str(raw_region.get("name") or raw_region.get("region_name") or "").strip()
        if not adcode or not name:
            return None
        return StandardScopeConstraint(adcode=adcode, region_name=name)

    @classmethod
    def from_request_context(cls, request_context: Mapping[str, Any] | None) -> StandardScopeConstraint | None:
        if not isinstance(request_context, Mapping):
            return None
        browser = request_context.get("browser_observations")
        if not isinstance(browser, Mapping):
            return None
        return cls.from_map_context(browser.get("map_context"))


__all__ = ["RegionScopeProjector"]
