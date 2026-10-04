from app.services.agent.region_scope import RegionScopeProjector


def test_active_region_projects_to_temporary_standard_scope() -> None:
    scope = RegionScopeProjector.from_request_context(
        {
            "browser_observations": {
                "map_context": {
                    "active_region": {"adcode": "510000", "name": "四川省"}
                }
            }
        }
    )

    assert scope is not None
    assert scope.adcode == "510000"
    assert scope.region_name == "四川省"
    assert scope.relation == "covers"


def test_missing_active_region_does_not_create_scope() -> None:
    assert RegionScopeProjector.from_request_context({}) is None
    assert RegionScopeProjector.from_map_context({"active_region": None}) is None
