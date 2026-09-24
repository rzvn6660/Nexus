"""API endpoints for the NEXUS Semantic Layer and KPI Ontology."""


from fastapi import APIRouter, HTTPException, Query, status

from app.rag.semantic.models import BusinessDomain
from app.rag.semantic.ontology import kpi_ontology, semantic_resolver
from app.schemas.semantic import KPIResponse, SemanticResolveRequest, SemanticResolveResponse

router = APIRouter()


@router.post(
    "/resolve",
    response_model=SemanticResolveResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve natural language business terminology against KPI ontology",
    description=(
        "Deterministically maps user business terminology to approved NEXUS KPIs and analytics tools. "
        "Detects ambiguous business terms and explicitly unsupported metrics."
    ),
)
def resolve_terminology(payload: SemanticResolveRequest) -> SemanticResolveResponse:
    """Resolve a business term or user query to canonical KPI representation."""
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
        resolved_kpi=resolved_kpi_resp,
        canonical_name=result.canonical_name,
        analytics_tool=result.analytics_tool,
        metric_field=result.metric_field,
        is_ambiguous=result.is_ambiguous,
        candidate_kpis=candidates_resp,
        is_supported=result.is_supported,
        unsupported_message=result.unsupported_message,
        clarification_prompt=result.clarification_prompt,
        matched_synonym=result.matched_synonym,
    )


@router.get(
    "/kpis",
    response_model=list[KPIResponse],
    status_code=status.HTTP_200_OK,
    summary="List all approved KPIs in the ontology",
    description="Returns all registered and deterministically supported metrics, optionally filtered by business domain.",
)
def list_kpis(
    domain: str | None = Query(None, description="Optional domain filter: finance, customer, product, inventory, expenses, diagnostic, statistics")
) -> list[KPIResponse]:
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
