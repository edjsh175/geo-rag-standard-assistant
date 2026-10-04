"""Standard-level spatial applicability facts and deterministic bootstrap helpers.

This module deliberately does not perform RAG retrieval.  It owns the durable,
auditable fact that a standard is nationwide, tied to an administrative region,
custom geometry, or still unresolved.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from sqlalchemy import text

from app.core.database import db_manager
from app.services.document_asset_service import DocumentAssetService
from app.services.standard_scope_sql import (
    build_standard_scope_predicate,
    effective_fact_clause,
    scope_match_sql,
    standard_key_sql,
)

if TYPE_CHECKING:
    from app.services.rag.contracts import StandardScopeConstraint


_NATIONWIDE_STANDARD_RE = re.compile(r"^(?:gb|nb|qx|sl)[a-z]*\d+")
_LOCAL_JURISDICTION_RE = re.compile(r"^db(?P<digits>\d{2,6})[a-z]+\d+")
_ADMIN_REGION_SUFFIXES = (
    "特别行政区",
    "自治区",
    "自治州",
    "地区",
    "省",
    "市",
    "盟",
    "县",
    "区",
)
_CATALOGUE_QUERY_INTENT_TERMS = (
    "标准清单",
    "标准目录",
    "全部列出",
    "列出来",
    "有哪些",
    "有多少",
    "查一下",
    "适用",
    "相关",
    "当前",
    "查询",
    "列一下",
    "列出",
    "全部",
    "所有",
    "数量",
    "标准",
    "规范",
    "清单",
    "目录",
)


@dataclass(frozen=True, slots=True)
class StandardApplicabilityFact:
    standard_key: str
    raw_standard_code: str
    scope_type: str
    scope_adcode: str | None
    scope_text: str | None
    basis_type: str
    basis_chunk_id: str | None
    verification_status: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class StandardApplicabilityService:
    """Own standard applicability facts; keep retrieval/ranking outside this boundary."""

    @staticmethod
    def standard_key(raw_standard_code: str | None) -> str:
        """Return the one canonical standard identity used across the project."""
        return DocumentAssetService.normalize_standard_code(raw_standard_code)

    @staticmethod
    def normalize_catalogue_query(
        query: str | None,
        *,
        region_name: str,
    ) -> str | None:
        """Keep catalogue text filtering orthogonal to the active region scope.

        ``active_region`` already determines spatial eligibility.  The optional
        catalogue query therefore represents only a standard topic, title, or
        code.  Models may still restate the current region/list intent in that
        field (for example ``四川省适用标准清单``); strip those deterministic
        scope/list terms instead of accidentally using them as document-name
        filters.
        """
        value = str(query or "").strip()
        if not value:
            return None

        canonical_region = str(region_name or "").strip()
        region_aliases = {canonical_region} if canonical_region else set()
        for suffix in _ADMIN_REGION_SUFFIXES:
            if canonical_region.endswith(suffix) and len(canonical_region) > len(suffix):
                region_aliases.add(canonical_region[: -len(suffix)])
                break
        for alias in sorted((item for item in region_aliases if item), key=len, reverse=True):
            value = value.replace(alias, " ")

        for term in _CATALOGUE_QUERY_INTENT_TERMS:
            value = value.replace(term, " ")

        value = re.sub(r"\s+", " ", value).strip(" ，,。.;；:：、-—_")
        return value or None

    @classmethod
    def derive_bootstrap_fact(
        cls,
        *,
        raw_standard_code: str,
        known_adcodes: set[str] | frozenset[str],
        scope_text: str | None = None,
    ) -> StandardApplicabilityFact:
        """Derive only facts justified by deterministic jurisdiction rules.

        The method fails closed: an unverified local jurisdiction never silently
        falls back to a broader province.
        """
        standard_key = cls.standard_key(raw_standard_code)
        clean_scope_text = scope_text.strip() if isinstance(scope_text, str) and scope_text.strip() else None

        if _NATIONWIDE_STANDARD_RE.match(standard_key):
            return StandardApplicabilityFact(
                standard_key=standard_key,
                raw_standard_code=raw_standard_code.strip(),
                scope_type="nationwide",
                scope_adcode=None,
                scope_text=clean_scope_text,
                basis_type="jurisdiction_default",
                basis_chunk_id=None,
                verification_status="derived",
            )

        match = _LOCAL_JURISDICTION_RE.match(standard_key)
        if match:
            digits = match.group("digits")
            candidate_adcode = cls._candidate_adcode(digits)
            if candidate_adcode and candidate_adcode in known_adcodes:
                return StandardApplicabilityFact(
                    standard_key=standard_key,
                    raw_standard_code=raw_standard_code.strip(),
                    scope_type="admin_region",
                    scope_adcode=candidate_adcode,
                    scope_text=clean_scope_text,
                    basis_type="standard_code_derived",
                    basis_chunk_id=None,
                    verification_status="derived",
                )

        return StandardApplicabilityFact(
            standard_key=standard_key,
            raw_standard_code=raw_standard_code.strip(),
            scope_type="unresolved",
            scope_adcode=None,
            scope_text=clean_scope_text,
            basis_type="standard_code_derived",
            basis_chunk_id=None,
            verification_status="unresolved",
        )

    @staticmethod
    def _candidate_adcode(jurisdiction_digits: str) -> str | None:
        if len(jurisdiction_digits) == 2:
            return f"{jurisdiction_digits}0000"
        if len(jurisdiction_digits) == 4:
            return f"{jurisdiction_digits}00"
        if len(jurisdiction_digits) == 6:
            return jurisdiction_digits
        return None

    @staticmethod
    def summarize_facts(facts: Iterable[StandardApplicabilityFact]) -> dict[str, int]:
        materialized = list(facts)
        scope_counts = {key: 0 for key in ("nationwide", "admin_region", "custom_geometry", "unresolved")}
        status_counts = {key: 0 for key in ("verified", "derived", "unresolved")}
        for fact in materialized:
            if fact.scope_type in scope_counts:
                scope_counts[fact.scope_type] += 1
            if fact.verification_status in status_counts:
                status_counts[fact.verification_status] += 1
        return {
            "total": len(materialized),
            **scope_counts,
            "verified": status_counts["verified"],
            "derived": status_counts["derived"],
            "unresolved_status": status_counts["unresolved"],
        }

    @staticmethod
    def scope_eligibility_predicate(
        *,
        alias: str,
        scope: StandardScopeConstraint | None,
    ) -> tuple[str, dict[str, Any]]:
        """Build the canonical SQL eligibility predicate for a policy-chunk alias."""
        return build_standard_scope_predicate(alias=alias, scope=scope)

    async def list_applicable_standards(
        self,
        *,
        scope: StandardScopeConstraint,
        query: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Return a deterministic, paged catalogue for the active administrative scope."""
        if db_manager.postgres_sessionmaker is None:
            raise RuntimeError("PostgreSQL connection is not initialized")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")

        scope_clause, scope_params = self.scope_eligibility_predicate(alias="pc", scope=scope)
        effective_query = self.normalize_catalogue_query(
            query,
            region_name=scope.region_name,
        )
        normalized_expr = standard_key_sql("pc")
        filters = ["NULLIF(BTRIM(pc.standard_code), '') IS NOT NULL"]
        count_filters = ["NULLIF(BTRIM(pc.standard_code), '') IS NOT NULL"]
        params: dict[str, Any] = {**scope_params, "limit_plus_one": limit + 1}
        count_params: dict[str, Any] = dict(scope_params)
        if effective_query:
            params["catalogue_query"] = f"%{effective_query}%"
            count_params["catalogue_query"] = params["catalogue_query"]
            topic_filter = "(pc.standard_code ILIKE :catalogue_query OR pc.document_name ILIKE :catalogue_query)"
            filters.append(topic_filter)
            count_filters.append(topic_filter)
        if cursor and cursor.strip():
            params["cursor"] = cursor.strip()
            filters.append(f"{normalized_expr} > :cursor")

        rows_sql = text(
            f"""
            WITH eligible AS (
                SELECT DISTINCT ON ({normalized_expr})
                    {normalized_expr} AS standard_key,
                    pc.standard_code,
                    pc.document_name
                FROM policy_chunks pc
                WHERE {' AND '.join(filters)}
                  {scope_clause}
                ORDER BY {normalized_expr}, pc.document_name, pc.id
            )
            SELECT standard_key, standard_code, document_name
            FROM eligible
            ORDER BY standard_key
            LIMIT :limit_plus_one
            """
        )
        count_sql = text(
            f"""
            WITH all_standards AS (
                SELECT DISTINCT {normalized_expr} AS standard_key
                FROM policy_chunks pc
                WHERE NULLIF(BTRIM(pc.standard_code), '') IS NOT NULL
            ),
            eligible AS (
                SELECT DISTINCT {normalized_expr} AS standard_key
                FROM policy_chunks pc
                WHERE {' AND '.join(count_filters)}
                  {scope_clause}
            )
            SELECT
                (SELECT COUNT(*)::int FROM eligible) AS eligible_count,
                (
                    SELECT COUNT(*)::int
                    FROM all_standards s
                    WHERE NOT EXISTS (
                        SELECT 1 FROM standard_applicability sa
                        WHERE sa.standard_key = s.standard_key
                          AND sa.verification_status IN ('verified', 'derived')
                          AND {effective_fact_clause('sa')}
                    )
                ) AS unresolved_count
            """
        )

        async with db_manager.get_postgres_session() as session:
            rows = (await session.execute(rows_sql, params)).mappings().all()
            counts = (await session.execute(count_sql, count_params)).mappings().one()

        has_more = len(rows) > limit
        page = rows[:limit]
        fact_by_key: dict[str, dict[str, Any]] = {}
        page_keys = [str(row["standard_key"]) for row in page]
        if page_keys:
            fact_sql = text(
                f"""
                WITH target_region AS (
                    SELECT geometry
                    FROM spatial_regions
                    WHERE adcode = :standard_scope_adcode
                ),
                effective AS (
                    SELECT sa.*
                    FROM standard_applicability sa
                    WHERE sa.standard_key = ANY(:page_keys)
                      AND sa.verification_status IN ('verified', 'derived')
                      AND {effective_fact_clause('sa')}
                )
                SELECT DISTINCT ON (sa.standard_key)
                    sa.standard_key,
                    sa.scope_type,
                    sa.scope_adcode,
                    sa.scope_text,
                    sa.basis_type,
                    sa.basis_chunk_id,
                    sa.verification_status
                FROM effective sa
                CROSS JOIN target_region target
                WHERE {scope_match_sql(fact_alias='sa', target_alias='target', relation=scope.relation)}
                ORDER BY sa.standard_key, sa.updated_at DESC, sa.id DESC
                """
            )
            async with db_manager.get_postgres_session() as session:
                fact_rows = (
                    await session.execute(
                        fact_sql,
                        {"standard_scope_adcode": scope.adcode, "page_keys": page_keys},
                    )
                ).mappings().all()
            fact_by_key = {str(row["standard_key"]): dict(row) for row in fact_rows}
        items = [
            {
                "standard_key": str(row["standard_key"]),
                "standard_code": str(row["standard_code"]),
                "title": str(row["document_name"] or row["standard_code"]),
                "scope_type": fact_by_key.get(str(row["standard_key"]), {}).get("scope_type"),
                "scope_adcode": fact_by_key.get(str(row["standard_key"]), {}).get("scope_adcode"),
                "scope_text": fact_by_key.get(str(row["standard_key"]), {}).get("scope_text"),
                "basis_type": fact_by_key.get(str(row["standard_key"]), {}).get("basis_type"),
                "basis_chunk_id": fact_by_key.get(str(row["standard_key"]), {}).get("basis_chunk_id"),
                "verification_status": fact_by_key.get(str(row["standard_key"]), {}).get("verification_status"),
            }
            for row in page
        ]
        unresolved_count = int(counts["unresolved_count"])
        return {
            "region": {"adcode": scope.adcode, "name": scope.region_name},
            "items": items,
            "eligible_count": int(counts["eligible_count"]),
            "unresolved_count": unresolved_count,
            "next_cursor": str(page[-1]["standard_key"]) if has_more and page else None,
            "coverage_complete": unresolved_count == 0,
        }

    async def build_bootstrap_report(self) -> dict[str, Any]:
        """Build a reproducible dry-run report without mutating applicability facts."""
        if db_manager.postgres_sessionmaker is None:
            raise RuntimeError("PostgreSQL connection is not initialized")

        async with db_manager.get_postgres_session() as session:
            baseline = (
                await session.execute(
                    text(
                        """
                        SELECT
                            COUNT(*)::int AS policy_chunks,
                            COUNT(DISTINCT standard_code)::int AS distinct_raw_standard_codes,
                            COUNT(DISTINCT document_name)::int AS distinct_document_names
                        FROM policy_chunks
                        """
                    )
                )
            ).mappings().one()
            adcodes = {
                str(value)
                for value in (
                    await session.execute(text("SELECT adcode::text FROM spatial_regions"))
                ).scalars().all()
                if value is not None
            }
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT
                            standard_code,
                            MIN(NULLIF(BTRIM(application_scope), '')) AS application_scope
                        FROM policy_chunks
                        WHERE NULLIF(BTRIM(standard_code), '') IS NOT NULL
                        GROUP BY standard_code
                        ORDER BY standard_code
                        """
                    )
                )
            ).mappings().all()

        facts_by_key: dict[str, StandardApplicabilityFact] = {}
        raw_aliases: dict[str, set[str]] = {}
        for row in rows:
            raw_code = str(row["standard_code"])
            fact = self.derive_bootstrap_fact(
                raw_standard_code=raw_code,
                known_adcodes=adcodes,
                scope_text=row.get("application_scope"),
            )
            if not fact.standard_key:
                continue
            raw_aliases.setdefault(fact.standard_key, set()).add(raw_code)
            facts_by_key.setdefault(fact.standard_key, fact)

        facts = tuple(facts_by_key[key] for key in sorted(facts_by_key))
        return {
            "baseline": {
                "policy_chunks": int(baseline["policy_chunks"]),
                "distinct_raw_standard_codes": int(baseline["distinct_raw_standard_codes"]),
                "distinct_standard_keys": len(facts),
                "distinct_document_names": int(baseline["distinct_document_names"]),
            },
            "scope_coverage": self.summarize_facts(facts),
            "normalization_collisions": {
                key: sorted(values)
                for key, values in raw_aliases.items()
                if len(values) > 1
            },
            "facts": [fact.as_dict() for fact in facts],
        }

    async def apply_bootstrap(self, facts: Iterable[Mapping[str, Any] | StandardApplicabilityFact]) -> int:
        """Idempotently persist deterministic bootstrap facts.

        Explicit/manual facts use higher-precedence basis types and are not touched.
        """
        if db_manager.postgres_sessionmaker is None:
            raise RuntimeError("PostgreSQL connection is not initialized")

        rows: list[dict[str, Any]] = []
        for raw in facts:
            row = raw.as_dict() if isinstance(raw, StandardApplicabilityFact) else dict(raw)
            rows.append(row)
        if not rows:
            return 0

        statement = text(
            """
            INSERT INTO standard_applicability (
                standard_key,
                raw_standard_code,
                scope_type,
                scope_adcode,
                scope_text,
                basis_type,
                basis_chunk_id,
                verification_status
            ) VALUES (
                :standard_key,
                :raw_standard_code,
                :scope_type,
                :scope_adcode,
                :scope_text,
                :basis_type,
                :basis_chunk_id,
                :verification_status
            )
            ON CONFLICT (standard_key, basis_type)
            WHERE basis_type IN ('jurisdiction_default', 'standard_code_derived')
            DO UPDATE SET
                raw_standard_code = EXCLUDED.raw_standard_code,
                scope_type = EXCLUDED.scope_type,
                scope_adcode = EXCLUDED.scope_adcode,
                scope_text = EXCLUDED.scope_text,
                verification_status = EXCLUDED.verification_status,
                updated_at = NOW()
            """
        )
        async with db_manager.get_postgres_session() as session:
            await session.execute(statement, rows)
        return len(rows)

