from __future__ import annotations

from pathlib import Path

from app.services.document_asset_service import DocumentAssetService
from app.services.standard_applicability import StandardApplicabilityService


def test_standard_key_reuses_document_asset_normalization() -> None:
    raw = " DB 51/T 1234-2026 "

    assert StandardApplicabilityService.standard_key(raw) == DocumentAssetService.normalize_standard_code(raw)
    assert StandardApplicabilityService.standard_key(raw) == "db51t12342026"


def test_catalogue_query_drops_scope_only_list_intent() -> None:
    assert (
        StandardApplicabilityService.normalize_catalogue_query(
            "四川省适用标准清单",
            region_name="四川省",
        )
        is None
    )
    assert (
        StandardApplicabilityService.normalize_catalogue_query(
            "四川有哪些标准",
            region_name="四川省",
        )
        is None
    )


def test_catalogue_query_keeps_only_content_topic_after_scope_normalization() -> None:
    assert StandardApplicabilityService.normalize_catalogue_query(
        "四川省地质灾害相关标准",
        region_name="四川省",
    ) == "地质灾害"
    assert StandardApplicabilityService.normalize_catalogue_query(
        "DB51/T 3144-2023",
        region_name="四川省",
    ) == "DB51/T 3144-2023"


def test_bootstrap_national_and_industry_codes_default_to_nationwide() -> None:
    for code in ("GB/T 123-2026", "NB/T 42-2026", "QX/T 8-2026", "SL 100-2026"):
        fact = StandardApplicabilityService.derive_bootstrap_fact(
            raw_standard_code=code,
            known_adcodes={"510000"},
        )

        assert fact.scope_type == "nationwide"
        assert fact.scope_adcode is None
        assert fact.basis_type == "jurisdiction_default"
        assert fact.verification_status == "derived"


def test_bootstrap_province_local_standard_requires_verified_admin_region() -> None:
    fact = StandardApplicabilityService.derive_bootstrap_fact(
        raw_standard_code="DB51/T 1234-2026",
        known_adcodes={"510000"},
    )

    assert fact.scope_type == "admin_region"
    assert fact.scope_adcode == "510000"
    assert fact.basis_type == "standard_code_derived"
    assert fact.verification_status == "derived"


def test_bootstrap_city_local_standard_uses_verified_city_adcode() -> None:
    fact = StandardApplicabilityService.derive_bootstrap_fact(
        raw_standard_code="DB5101/T 99-2026",
        known_adcodes={"510000", "510100"},
    )

    assert fact.scope_type == "admin_region"
    assert fact.scope_adcode == "510100"


def test_bootstrap_unverified_specific_local_standard_fails_closed() -> None:
    fact = StandardApplicabilityService.derive_bootstrap_fact(
        raw_standard_code="DB5132/T 88-2026",
        known_adcodes={"510000"},
    )

    assert fact.scope_type == "unresolved"
    assert fact.scope_adcode is None
    assert fact.verification_status == "unresolved"


def test_bootstrap_unknown_standard_family_is_unresolved() -> None:
    fact = StandardApplicabilityService.derive_bootstrap_fact(
        raw_standard_code="T/ABC 123-2026",
        known_adcodes={"510000"},
    )

    assert fact.scope_type == "unresolved"
    assert fact.scope_adcode is None
    assert fact.verification_status == "unresolved"


def test_bootstrap_incomplete_standard_family_placeholder_is_unresolved() -> None:
    for code in ("GB_T", "DB13_T", "DB", "QX/T"):
        fact = StandardApplicabilityService.derive_bootstrap_fact(
            raw_standard_code=code,
            known_adcodes={"130000"},
        )

        assert fact.scope_type == "unresolved"
        assert fact.verification_status == "unresolved"


def test_phase0_migration_declares_auditable_standard_scope_contract() -> None:
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "20261002_standard_applicability.sql"
    ).read_text(encoding="utf-8")

    for required in (
        "standard_key TEXT NOT NULL",
        "raw_standard_code TEXT NOT NULL",
        "scope_type TEXT NOT NULL",
        "scope_adcode TEXT",
        "scope_geometry geometry(MultiPolygon, 4326)",
        "scope_text TEXT",
        "basis_type TEXT NOT NULL",
        "basis_chunk_id TEXT",
        "verification_status TEXT NOT NULL",
    ):
        assert required in migration


def test_bootstrap_summary_separates_resolved_and_unresolved_facts() -> None:
    facts = [
        StandardApplicabilityService.derive_bootstrap_fact(
            raw_standard_code="GB/T 1-2026",
            known_adcodes={"510000"},
        ),
        StandardApplicabilityService.derive_bootstrap_fact(
            raw_standard_code="DB51/T 2-2026",
            known_adcodes={"510000"},
        ),
        StandardApplicabilityService.derive_bootstrap_fact(
            raw_standard_code="T/ABC 3-2026",
            known_adcodes={"510000"},
        ),
    ]

    summary = StandardApplicabilityService.summarize_facts(facts)

    assert summary == {
        "total": 3,
        "nationwide": 1,
        "admin_region": 1,
        "custom_geometry": 0,
        "unresolved": 1,
        "verified": 0,
        "derived": 2,
        "unresolved_status": 1,
    }
