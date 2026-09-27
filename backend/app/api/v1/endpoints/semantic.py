"""API endpoints for the NEXUS Semantic Layer, KPI Ontology, and Tenant Business Understanding (Phase 17)."""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_optional_current_user, verify_user_business_access
from app.core.database import get_db
from app.models.tenant import Business, OrganizationMembership, TenantSemanticModel, UserIdentity
from app.rag.semantic.models import BusinessDomain
from app.rag.semantic.ontology import kpi_ontology, semantic_resolver
from app.schemas.semantic import (
    BusinessDataSummary,
    BusinessUnderstandingResponse,
    KPIResponse,
    SemanticActivationRequest,
    SemanticActivationResponse,
    SemanticRevisionSummary,
    SemanticResolveRequest,
    SemanticResolveResponse,
)
from app.services.tenant_semantic_service import TenantSemanticService

router = APIRouter()


def _resolve_target_business(
    db: Session,
    user: UserIdentity,
    x_business_id: Optional[str] = None,
    business_id_query: Optional[str] = None,
    action: str = "access",
) -> Business:
    """Helper to resolve and verify access to the target business workspace."""
    target_biz_id = x_business_id or business_id_query
    if not target_biz_id:
        user_org_ids = db.execute(
            select(OrganizationMembership.organization_id).where(OrganizationMembership.user_id == user.id)
        ).scalars().all()
        biz = db.execute(select(Business).where(Business.organization_id.in_(user_org_ids))).scalars().first()
        if not biz:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No business workspace found for user. Please complete onboarding first.",
            )
        target_biz_id = biz.id

    return verify_user_business_access(db, user, target_biz_id, action=action)


@router.post(
    "/resolve",
    response_model=SemanticResolveResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve natural language business terminology against KPI ontology",
    description=(
        "Deterministically maps user business terminology to approved NEXUS KPIs and analytics tools. "
        "Tenant-aware when business context is provided."
    ),
)
def resolve_terminology(
    payload: SemanticResolveRequest,
    x_business_id: Optional[str] = Header(None, alias="X-Business-ID"),
    business_id: Optional[str] = Query(None),
    current_user: Optional[UserIdentity] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> SemanticResolveResponse:
    """Resolve a business term or user query to canonical or tenant-specific KPI representation."""
    target_biz_id = x_business_id or business_id

    # If tenant context is present and user is authenticated, resolve with tenant understanding
    if target_biz_id and current_user:
        verify_user_business_access(db, current_user, target_biz_id, action="resolve query for")
        return TenantSemanticService.resolve_query_with_tenant_context(
            query=payload.query,
            business_id=target_biz_id,
            db=db,
        )

    # Fallback to canonical semantic resolver (backward compatible with Phase 4/5)
    result = semantic_resolver.resolve(payload.query)

    resolved_kpi_resp = None
    if result.resolved_kpi:
        k = result.resolved_kpi
        resolved_kpi_resp = KPIResponse(
            canonical_name=k.canonical_name,
            display_name=k.display_name,
            description=k.description,
            synonyms=k.synonyms,
            analytics_tool=k.analytics_tool,
            metric_field=k.metric_field,
            calculation_reference=k.calculation_reference,
            unit=k.unit.value,
            business_domain=k.business_domain.value,
            status=k.status,
        )

    candidates_resp = []
    for cand in result.candidate_kpis:
        candidates_resp.append(
            KPIResponse(
                canonical_name=cand.canonical_name,
                display_name=cand.display_name,
                description=cand.description,
                synonyms=cand.synonyms,
                analytics_tool=cand.analytics_tool,
                metric_field=cand.metric_field,
                calculation_reference=cand.calculation_reference,
                unit=cand.unit.value,
                business_domain=cand.business_domain.value,
                status=cand.status,
            )
        )

    return SemanticResolveResponse(
        query=result.query,
        canonical_name=result.canonical_name,
        canonical_kpi=result.canonical_name,
        analytics_tool=result.analytics_tool,
        metric_field=result.metric_field,
        resolved_kpi=resolved_kpi_resp,
        candidate_kpis=candidates_resp,
        is_ambiguous=result.is_ambiguous,
        is_supported=result.is_supported,
        unsupported_message=result.unsupported_message,
        clarification_prompt=result.clarification_prompt,
        matched_synonym=result.matched_synonym,
        availability_status="AVAILABLE",
    )


@router.get(
    "/understanding",
    response_model=BusinessUnderstandingResponse,
    status_code=status.HTTP_200_OK,
    summary="Get tenant-specific Business Understanding representation",
    description="Returns deterministic entity inventory, metric availability, date coverage, and warnings.",
)
def get_business_understanding(
    x_business_id: Optional[str] = Header(None, alias="X-Business-ID"),
    business_id: Optional[str] = Query(None),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BusinessUnderstandingResponse:
    """Retrieve active deterministic Business Understanding for current tenant business."""
    biz = _resolve_target_business(
        db, current_user, x_business_id, business_id, action="view business understanding"
    )

    model = TenantSemanticService.get_active_semantic_model(biz.id, db)
    if not model:
        # Generate initial model based on current database state
        model = TenantSemanticService.generate_business_understanding(
            business_id=biz.id,
            organization_id=biz.organization_id,
            db=db,
        )

    return TenantSemanticService.to_response(model)


@router.post(
    "/activate",
    response_model=SemanticActivationResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger explicit semantic activation and refresh business understanding",
    description="Refreshes entity inventory and metric availability, recording a new versioned revision.",
)
def activate_business_understanding(
    payload: SemanticActivationRequest,
    x_business_id: Optional[str] = Header(None, alias="X-Business-ID"),
    business_id: Optional[str] = Query(None),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SemanticActivationResponse:
    """Activate or refresh tenant semantic understanding."""
    biz = _resolve_target_business(
        db, current_user, x_business_id, business_id, action="activate semantic understanding"
    )

    model = TenantSemanticService.generate_business_understanding(
        business_id=biz.id,
        organization_id=biz.organization_id,
        db=db,
        custom_synonyms=payload.custom_synonyms,
    )

    msg = f"Business Understanding activated successfully (Version {model.version}, Status: {model.status})."
    if model.status == "REQUIRES_REVIEW":
        msg = f"Business Understanding activated with review required (Version {model.version}): conflicts detected with previous model."

    return SemanticActivationResponse(
        business_id=biz.id,
        version=model.version,
        status=model.status,
        message=msg,
        understanding=TenantSemanticService.to_response(model),
    )


@router.get(
    "/revisions",
    response_model=List[SemanticRevisionSummary],
    status_code=status.HTTP_200_OK,
    summary="List historical semantic revisions for tenant business",
)
def list_semantic_revisions(
    x_business_id: Optional[str] = Header(None, alias="X-Business-ID"),
    business_id: Optional[str] = Query(None),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[SemanticRevisionSummary]:
    """Retrieve revision audit trail of tenant semantic configurations."""
    biz = _resolve_target_business(
        db, current_user, x_business_id, business_id, action="view semantic revisions"
    )
    return TenantSemanticService.list_revisions(biz.id, db)


@router.get(
    "/conflicts",
    response_model=List[Dict[str, Any]],
    status_code=status.HTTP_200_OK,
    summary="List active semantic conflicts requiring human review",
)
def get_semantic_conflicts(
    x_business_id: Optional[str] = Header(None, alias="X-Business-ID"),
    business_id: Optional[str] = Query(None),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Retrieve any unresolved conflicts between semantic model revisions."""
    biz = _resolve_target_business(
        db, current_user, x_business_id, business_id, action="view semantic conflicts"
    )
    # Check for review-pending models first, then active model
    model = db.execute(
        select(TenantSemanticModel)
        .where(
            TenantSemanticModel.business_id == biz.id,
            TenantSemanticModel.status == "REQUIRES_REVIEW",
        )
        .order_by(desc(TenantSemanticModel.version))
    ).scalars().first()
    if not model:
        model = TenantSemanticService.get_active_semantic_model(biz.id, db)
    if not model or not model.conflicts_json:
        return []
    return model.conflicts_json.get("conflicts", [])


@router.get(
    "/kpis",
    response_model=List[KPIResponse],
    status_code=status.HTTP_200_OK,
    summary="List all approved KPIs in the canonical ontology",
    description="Returns all registered and deterministically supported metrics, optionally filtered by business domain.",
)
def list_kpis(
    domain: Optional[str] = Query(None, description="Optional domain filter: finance, customer, product, inventory, expenses, diagnostic, statistics")
) -> List[KPIResponse]:
    """Retrieve catalog of all supported business metrics."""
    domain_enum = None
    if domain:
        try:
            domain_enum = BusinessDomain(domain.lower())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid business domain '{domain}'. Allowed: {[e.value for e in BusinessDomain]}",
            )

    kpis = kpi_ontology.list_kpis(domain=domain_enum)
    return [
        KPIResponse(
            canonical_name=k.canonical_name,
            display_name=k.display_name,
            description=k.description,
            synonyms=k.synonyms,
            analytics_tool=k.analytics_tool,
            metric_field=k.metric_field,
            calculation_reference=k.calculation_reference,
            unit=k.unit.value,
            business_domain=k.business_domain.value,
            status=k.status,
        )
        for k in kpis
    ]


@router.get(
    "/kpis/{canonical_name}",
    response_model=KPIResponse,
    status_code=status.HTTP_200_OK,
    summary="Get details for a specific canonical KPI",
)
def get_kpi_by_name(canonical_name: str) -> KPIResponse:
    """Retrieve specific KPI definition and tool binding by canonical name."""
    kpi = kpi_ontology.get_kpi(canonical_name.lower().strip())
    if not kpi:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"KPI '{canonical_name}' not found in NEXUS metric catalog.",
        )

    return KPIResponse(
        canonical_name=kpi.canonical_name,
        display_name=kpi.display_name,
        description=kpi.description,
        synonyms=kpi.synonyms,
        analytics_tool=kpi.analytics_tool,
        metric_field=kpi.metric_field,
        calculation_reference=kpi.calculation_reference,
        unit=kpi.unit.value,
        business_domain=kpi.business_domain.value,
        status=kpi.status,
    )
