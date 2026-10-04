from __future__ import annotations

from app.services.rag.contracts import StandardScopeConstraint
from app.services.rag.postgres_adapter import PostgresRetrievalAdapter


def test_standard_scope_predicate_is_pre_retrieval_and_precedence_aware() -> None:
    clause, params = PostgresRetrievalAdapter._standard_scope_predicate(
        alias="policy_chunks",
        scope=StandardScopeConstraint(adcode="510000", region_name="四川省"),
    )

    assert "standard_applicability" in clause
    assert "REGEXP_REPLACE(LOWER(COALESCE(policy_chunks.standard_code" in clause
    assert "NOT EXISTS" in clause
    assert "manual_verified" in clause
    assert "explicit_scope_clause" in clause
    assert "ST_Covers" in clause
    assert params == {"standard_scope_adcode": "510000"}


def test_intersects_scope_requires_positive_intersection_area() -> None:
    clause, params = PostgresRetrievalAdapter._standard_scope_predicate(
        alias="pc",
        scope=StandardScopeConstraint(
            adcode="510000",
            region_name="四川省",
            relation="intersects",
        ),
    )

    assert "ST_Intersects" in clause
    assert "ST_Area" in clause
    assert "> 0" in clause
    assert params["standard_scope_adcode"] == "510000"


def test_no_standard_scope_produces_no_sql_predicate() -> None:
    clause, params = PostgresRetrievalAdapter._standard_scope_predicate(
        alias="policy_chunks",
        scope=None,
    )

    assert clause == ""
    assert params == {}


def test_scoped_keyword_terms_do_not_reintroduce_region_prefix_bias() -> None:
    adapter = PostgresRetrievalAdapter()
    scope = StandardScopeConstraint(adcode="510000", region_name="四川省")

    terms = adapter._extract_keyword_terms(
        "四川地质灾害监测标准",
        standard_scope=scope,
    )

    assert "DB51" not in terms
    assert "四川" not in terms
    assert any("地质灾害" in term for term in terms)


def test_unscoped_keyword_terms_keep_legacy_region_discovery_behavior() -> None:
    adapter = PostgresRetrievalAdapter()

    terms = adapter._extract_keyword_terms("四川地质灾害监测标准")

    assert "DB51" in terms
