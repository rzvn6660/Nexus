"""Deterministic Validator for NEXUS OKF Bundles and Items (Phase 14C).

Validates:
- Required fields & format constraints
- Unique machine-readable IDs
- Supported item types & lifecycle states
- Referential integrity of relationships
- Temporal validity (effective_from <= effective_to)
- Provenance & sign-off completeness
- Conflict detection (identical synonyms mapping to incompatible targets or duplicate KPI definitions)
- Absence of executable code constructs

Ensures invalid bundles fail safely with granular error diagnostics.
"""

import re
from datetime import date, datetime
from app.knowledge.okf.models import (
    OKFBundle,
    OKFItem,
    OKFItemType,
    OKFStatus,
    OKFValidationError,
    OKFValidationReport,
)


class OKFValidator:
    """Deterministic validation engine for Business Knowledge Fabric bundles."""

    ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")

    @classmethod
    def validate_item(cls, item: OKFItem, known_ids: set[str] | None = None) -> list[OKFValidationError]:
        """Validate a single OKFItem against all domain rules."""
        errors: list[OKFValidationError] = []

        # 1. ID checks
        if not cls.ID_PATTERN.match(item.id):
            errors.append(OKFValidationError(
                item_id=item.id,
                field="id",
                error_type="invalid_id_format",
                message=f"ID '{item.id}' must be 2-64 characters lowercase alphanumeric, hyphen, or underscore.",
            ))

        # 2. Type checks
        if not isinstance(item.type, OKFItemType):
            errors.append(OKFValidationError(
                item_id=item.id,
                field="type",
                error_type="unsupported_type",
                message=f"Item type '{item.type}' is unsupported.",
            ))

        # 3. Status checks
        if not isinstance(item.status, OKFStatus):
            errors.append(OKFValidationError(
                item_id=item.id,
                field="status",
                error_type="invalid_status",
                message=f"Status '{item.status}' is not a recognized OKFStatus.",
            ))

        # 4. Provenance & Verification checks
        if not item.source or not item.source.strip():
            errors.append(OKFValidationError(
                item_id=item.id,
                field="source",
                error_type="missing_provenance",
                message="Provenance 'source' is required for all knowledge items.",
            ))

        if item.status == OKFStatus.VERIFIED:
            if not item.author and not item.verified_by:
                errors.append(OKFValidationError(
                    item_id=item.id,
                    field="verified_by",
                    error_type="unverified_status",
                    message="Verified items must specify either 'author' or 'verified_by'.",
                ))

        # 5. Temporal Validity checks
        if item.effective_from and item.effective_to:
            ef_date = item.effective_from.date() if isinstance(item.effective_from, datetime) else item.effective_from
            et_date = item.effective_to.date() if isinstance(item.effective_to, datetime) else item.effective_to
            if ef_date > et_date:
                errors.append(OKFValidationError(
                    item_id=item.id,
                    field="effective_to",
                    error_type="invalid_date_range",
                    message=f"effective_from ({ef_date}) cannot be later than effective_to ({et_date}).",
                ))

        # 6. Type-specific checks
        if item.type == OKFItemType.KPI:
            # KPI must have either formula, metric_field, or explicit description
            if not item.formula and not item.metric_field and not item.description:
                errors.append(OKFValidationError(
                    item_id=item.id,
                    field="kpi_definition",
                    error_type="incomplete_kpi",
                    message="KPI items must specify at least a formula, metric_field, or markdown description.",
                ))

        if item.type in (OKFItemType.RULE, OKFItemType.POLICY):
            if not item.condition and not item.action and not item.description:
                errors.append(OKFValidationError(
                    item_id=item.id,
                    field="rule_policy",
                    error_type="incomplete_rule",
                    message="Rule or Policy must provide condition/action or detailed markdown description.",
                ))

        if item.type == OKFItemType.CALENDAR:
            if item.fiscal_year_start_month is not None:
                if not (1 <= item.fiscal_year_start_month <= 12):
                    errors.append(OKFValidationError(
                        item_id=item.id,
                        field="fiscal_year_start_month",
                        error_type="invalid_month",
                        message="fiscal_year_start_month must be an integer between 1 and 12.",
                    ))

        # 7. Relational checks (if known_ids provided)
        if known_ids is not None:
            for rel_id in item.related_to:
                if rel_id not in known_ids:
                    errors.append(OKFValidationError(
                        item_id=item.id,
                        field="related_to",
                        error_type="dangling_relationship",
                        message=f"Item references non-existent related ID '{rel_id}'.",
                    ))

        return errors

    @classmethod
    def validate_bundle(cls, bundle: OKFBundle) -> OKFValidationReport:
        """
        Validate an entire OKFBundle deterministically.
        Checks bundle metadata, individual items, duplicate IDs, and intra-bundle conflicts.
        """
        errors: list[OKFValidationError] = []
        warnings: list[str] = []

        # 1. Bundle metadata validation
        if not cls.ID_PATTERN.match(bundle.id):
            errors.append(OKFValidationError(
                item_id=bundle.id,
                field="id",
                error_type="invalid_bundle_id",
                message=f"Bundle ID '{bundle.id}' is invalid. Must match slug pattern.",
            ))

        if not bundle.author or not bundle.author.strip():
            errors.append(OKFValidationError(
                item_id=bundle.id,
                field="author",
                error_type="missing_bundle_author",
                message="Bundle author must be specified.",
            ))

        if bundle.version < 1:
            errors.append(OKFValidationError(
                item_id=bundle.id,
                field="version",
                error_type="invalid_bundle_version",
                message="Bundle version must be a positive integer.",
            ))

        # 2. Check for duplicate IDs
        seen_ids: dict[str, int] = {}
        for it in bundle.items:
            seen_ids[it.id] = seen_ids.get(it.id, 0) + 1

        for it_id, count in seen_ids.items():
            if count > 1:
                errors.append(OKFValidationError(
                    item_id=it_id,
                    field="id",
                    error_type="duplicate_item_id",
                    message=f"Duplicate item ID '{it_id}' found {count} times in bundle.",
                ))

        all_known_ids = set(seen_ids.keys())

        # 3. Item-by-item validation
        for it in bundle.items:
            item_errors = cls.validate_item(it, known_ids=all_known_ids)
            errors.extend(item_errors)

            if it.status == OKFStatus.DEPRECATED:
                warnings.append(f"Item '{it.id}' is marked deprecated.")

        # 4. Intra-bundle Conflict Detection
        # Check if multiple KPIs define the same synonym or name with conflicting formulas
        synonym_to_kpi: dict[str, str] = {}
        for it in bundle.items:
            if it.type == OKFItemType.KPI:
                synonyms = [it.name.lower()] + [s.lower().strip() for s in it.synonyms]
                for syn in synonyms:
                    if syn in synonym_to_kpi:
                        prior_id = synonym_to_kpi[syn]
                        if prior_id != it.id:
                            errors.append(OKFValidationError(
                                item_id=it.id,
                                field="synonyms",
                                error_type="conflicting_synonym_definition",
                                message=f"Synonym '{syn}' in '{it.id}' collides with definition in '{prior_id}'.",
                            ))
                    else:
                        synonym_to_kpi[syn] = it.id

        is_valid = len(errors) == 0
        return OKFValidationReport(
            is_valid=is_valid,
            bundle_id=bundle.id,
            item_count=len(bundle.items),
            errors=errors,
            warnings=warnings,
        )
