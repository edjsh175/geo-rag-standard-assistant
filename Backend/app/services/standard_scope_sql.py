"""Pure SQL-fragment builder for standard applicability qualification.

Kept outside the ``rag`` package so both catalogue and retrieval paths can reuse
the same rule without introducing service/package import cycles.
"""

from __future__ import annotations

import re
from typing import Any, Protocol


class _ScopeLike(Protocol):
    adcode: str
    relation: str


def standard_key_sql(alias: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
        raise ValueError("invalid SQL alias")
    return (
        f"REGEXP_REPLACE(LOWER(COALESCE({alias}.standard_code, '')), "
        "'[^a-z0-9]+', '', 'g')"
    )


def basis_precedence_sql(alias: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
        raise ValueError("invalid SQL alias")
    return f"""
        CASE {alias}.basis_type
            WHEN 'manual_verified' THEN 1
            WHEN 'explicit_scope_clause' THEN 2
            WHEN 'jurisdiction_default' THEN 3
            WHEN 'standard_code_derived' THEN 4
            ELSE 5
        END
    """


def effective_fact_clause(alias: str = "sa") -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
        raise ValueError("invalid SQL alias")
    return f"""
        NOT EXISTS (
            SELECT 1
            FROM standard_applicability higher
            WHERE higher.standard_key = {alias}.standard_key
              AND ({basis_precedence_sql('higher')}) < ({basis_precedence_sql(alias)})
        )
    """


def scope_match_sql(
    *,
    fact_alias: str,
    target_alias: str,
    relation: str,
) -> str:
    for alias in (fact_alias, target_alias):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
            raise ValueError("invalid SQL alias")
    if relation == "intersects":
        admin_relation = f"""
            ST_Intersects(scope_region.geometry, {target_alias}.geometry)
            AND ST_Area(
                ST_Intersection(scope_region.geometry, {target_alias}.geometry)::geography
            ) > 0
        """
        geometry_relation = f"""
            ST_Intersects({fact_alias}.scope_geometry, {target_alias}.geometry)
            AND ST_Area(
                ST_Intersection({fact_alias}.scope_geometry, {target_alias}.geometry)::geography
            ) > 0
        """
    else:
        admin_relation = f"ST_Covers(scope_region.geometry, {target_alias}.geometry)"
        geometry_relation = f"ST_Covers({fact_alias}.scope_geometry, {target_alias}.geometry)"

    return f"""
        (
            {fact_alias}.scope_type = 'nationwide'
            OR (
                {fact_alias}.scope_type = 'admin_region'
                AND EXISTS (
                    SELECT 1
                    FROM spatial_regions scope_region
                    WHERE scope_region.adcode = {fact_alias}.scope_adcode
                      AND {admin_relation}
                )
            )
            OR (
                {fact_alias}.scope_type = 'custom_geometry'
                AND {geometry_relation}
            )
        )
    """


def build_standard_scope_predicate(
    *,
    alias: str,
    scope: _ScopeLike | None,
) -> tuple[str, dict[str, Any]]:
    if scope is None:
        return "", {}
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
        raise ValueError("invalid SQL alias")

    normalized_code = standard_key_sql(alias)

    clause = f"""
        AND EXISTS (
            SELECT 1
            FROM standard_applicability sa
            WHERE sa.standard_key = {normalized_code}
              AND sa.verification_status IN ('verified', 'derived')
              AND {effective_fact_clause('sa')}
              AND EXISTS (
                  SELECT 1
                  FROM spatial_regions target_region
                  WHERE target_region.adcode = :standard_scope_adcode
                    AND {scope_match_sql(fact_alias='sa', target_alias='target_region', relation=scope.relation)}
              )
        )
    """
    return clause, {"standard_scope_adcode": scope.adcode}


__all__ = [
    "basis_precedence_sql",
    "build_standard_scope_predicate",
    "effective_fact_clause",
    "scope_match_sql",
    "standard_key_sql",
]
