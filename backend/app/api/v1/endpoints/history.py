"""API endpoints for Analysis Run History, Human Decisions (HITL), and Reports."""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.analytics.outcome.schemas import (
    AuditChainVerificationReport,
    BaselineMetricsSnapshot,
    DecisionAuditEventResponse,
    DecisionCreatePayload,
    DecisionRetrievalFilter,
    DecisionReviewPayload,
    EvidenceQualityGrade,
    HistoricalDecisionRetrievalResponse,
    OutcomeActionExecutionRequest,
    OutcomeEvaluationResponse,
    OutcomeMaturityStatus,
    OutcomeObservationCreateRequest,
    OutcomeObservationResponse,
    RecommendationSnapshot,
)
from app.analytics.outcome.service import DecisionMemoryService
from app.api.deps import get_db_session
from app.core.auth import (
    get_current_user,
    verify_user_analysis_access,
    verify_user_business_access,
    verify_user_decision_access,
)
from app.models.history import AnalysisRun, DecisionAuditEvent, DecisionRecord
from app.models.tenant import Business, OrganizationMembership, UserIdentity
from app.schemas.history import (
    AnalysisRunDetail,
    AnalysisRunSummary,
    DecisionCreateRequest,
    DecisionRecordResponse,
    DecisionUpdateRequest,
    ReportExportResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# 1. ANALYSIS RUN HISTORY ENDPOINTS
# ---------------------------------------------------------------------------

@router.get(
    "/runs",
    response_model=list[AnalysisRunSummary],
    summary="List historical agent analysis runs",
    description="Retrieve paginated list of past analytical runs with execution telemetry and status.",
)
@router.get(
    "/analyses",
    response_model=list[AnalysisRunSummary],
    include_in_schema=False,
)
def list_analysis_runs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[AnalysisRunSummary]:
    stmt = select(AnalysisRun)

    if x_business_id is not None:
        verify_user_business_access(db, current_user, x_business_id, action="view analysis runs of")
        stmt = stmt.where(AnalysisRun.business_id == x_business_id)
    else:
        user_org_ids = db.execute(
            select(OrganizationMembership.organization_id).where(
                OrganizationMembership.user_id == current_user.id
            )
        ).scalars().all()
        user_biz_ids = db.execute(
            select(Business.id).where(Business.organization_id.in_(user_org_ids))
        ).scalars().all()
        stmt = stmt.where(AnalysisRun.business_id.in_(user_biz_ids))

    stmt = (
        stmt
        .order_by(desc(AnalysisRun.created_at))
        .limit(limit)
        .offset(offset)
    )
    runs = db.execute(stmt).scalars().all()
    return [AnalysisRunSummary.model_validate(r) for r in runs]


@router.get(
    "/runs/{run_id}",
    response_model=AnalysisRunDetail,
    summary="Get detailed analysis run record",
    description="Retrieve full execution details, evidence proof packets, calculations, and decisions.",
)
@router.get(
    "/analyses/{run_id}",
    response_model=AnalysisRunDetail,
    include_in_schema=False,
)
def get_analysis_run(
    run_id: int,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> AnalysisRunDetail:
    run = db.get(AnalysisRun, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis run #{run_id} not found.",
        )

    # Multi-tenant IDOR defense: verify user and business workspace ownership
    verify_user_analysis_access(db, current_user, run.business_id, x_business_id)

    return AnalysisRunDetail.model_validate(run)


@router.get(
    "/runs/{run_id}/report",
    response_model=ReportExportResponse,
    summary="Export analysis dossier report",
    description="Generates an exportable, audit-ready Markdown or JSON dossier of an analysis run.",
)
@router.get(
    "/analyses/{run_id}/report",
    response_model=ReportExportResponse,
    include_in_schema=False,
)
def export_analysis_report(
    run_id: int,
    format: str = Query("markdown", pattern="^(markdown|json)$"),
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> ReportExportResponse:
    run = db.get(AnalysisRun, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis run #{run_id} not found.",
        )

    # Multi-tenant IDOR defense: verify user and business workspace ownership
    verify_user_analysis_access(db, current_user, run.business_id, x_business_id)

    report_id = f"RPT-{run.request_id[:8].upper()}"
    title = f"NEXUS Intelligence Dossier — Analysis #{run.id}"

    if format == "json":
        import json
        content = json.dumps(
            {
                "report_id": report_id,
                "analysis_id": run.id,
                "request_id": run.request_id,
                "query": run.query,
                "intent": run.intent,
                "status": run.status,
                "answer": run.answer,
                "execution_time_ms": run.execution_time_ms,
                "tools_used": run.tools_used or [],
                "calculations": run.calculations or [],
                "assumptions": run.assumptions or [],
                "limitations": run.limitations or [],
                "evidence_records": run.evidence_records or [],
                "rag_citations": run.rag_citations or [],
                "decisions": [
                    {
                        "id": d.id,
                        "recommendation": d.recommendation_text,
                        "status": d.status,
                        "reviewed_by": d.reviewed_by,
                        "reviewed_at": d.reviewed_at.isoformat() if d.reviewed_at else None,
                    }
                    for d in run.decisions
                ],
                "created_at": run.created_at.isoformat(),
            },
            indent=2,
        )
    else:
        # Markdown dossier
        lines = [
            f"# {title}",
            "",
            f"**Report ID**: `{report_id}`  ",
            f"**Execution Timestamp**: {run.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}  ",
            f"**Request ID**: `{run.request_id}`  ",
            f"**Resolved Intent**: `{run.intent or 'N/A'}`  ",
            f"**Execution Latency**: {run.execution_time_ms or 0:.1f}ms  ",
            "",
            "---",
            "",
            "## 1. Executive Question",
            f"> \"{run.query}\"",
            "",
            "## 2. Key Findings & Synthesis",
            run.answer,
            "",
        ]

        if run.tools_used:
            lines.extend([
                "## 3. Computational Tools Executed",
                "The following deterministic tools executed without LLM math:",
                "",
            ])
            for t in run.tools_used:
                lines.append(f"- `{t}`")
            lines.append("")

        if run.evidence_records:
            lines.extend([
                "## 4. Evidence & Provenance Audit",
                "",
            ])
            for idx, ev in enumerate(run.evidence_records, 1):
                metric = ev.get("metric", "Metric")
                tables = ", ".join(ev.get("source_tables", []))
                calc = ev.get("calculation", "N/A")
                lines.append(f"### Evidence #{idx}: {metric}")
                lines.append(f"- **Source Tables**: `{tables}`")
                lines.append(f"- **Computation / Method**: {calc}")
                if ev.get("assumptions"):
                    lines.append(f"- **Assumptions**: {'; '.join(ev.get('assumptions'))}")
                lines.append("")

        if run.rag_citations:
            lines.extend([
                "## 5. Organizational Context & Policy Grounding",
                "",
            ])
            for c in run.rag_citations:
                doc = c.get("document_name", "Document")
                sec = c.get("title", "Section")
                lines.append(f"- **{doc}** ({sec}): *\"{c.get('content_snippet', '')}\"*")
            lines.append("")

        if run.decisions:
            lines.extend([
                "## 6. Human-in-the-Loop Review Ledger",
                "",
                "| Decision ID | Recommendation | Review Status | Reviewer | Review Date |",
                "|---|---|---|---|---|",
            ])
            for d in run.decisions:
                date_str = d.reviewed_at.strftime('%Y-%m-%d %H:%M') if d.reviewed_at else "Pending"
                reviewer = d.reviewed_by or "—"
                lines.append(f"| #{d.id} | {d.recommendation_text} | **{d.status}** | {reviewer} | {date_str} |")
            lines.append("")

        lines.extend([
            "---",
            "*Generated deterministically by NEXUS — Agentic Business Intelligence Platform.*",
        ])
        content = "\n".join(lines)

    return ReportExportResponse(
        report_id=report_id,
        analysis_id=run.id,
        title=title,
        format=format,
        generated_at=datetime.now(UTC),
        content=content,
    )


# ---------------------------------------------------------------------------
# 2. HUMAN-IN-THE-LOOP DECISION ENDPOINTS
# ---------------------------------------------------------------------------

@router.get(
    "/decisions",
    response_model=list[DecisionRecordResponse],
    summary="List Human-in-the-Loop decision records",
    description="Retrieve decisions with optional filtering by status (PENDING, APPROVED, REJECTED, MODIFIED).",
)
def list_decisions(
    status_filter: str | None = Query(None, alias="status", pattern="^(PENDING|APPROVED|REJECTED|MODIFIED)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[DecisionRecordResponse]:
    stmt = select(DecisionRecord)

    if x_business_id is not None:
        verify_user_business_access(db, current_user, x_business_id, action="view decision records of")
        stmt = stmt.where(DecisionRecord.business_id == x_business_id)
    else:
        user_org_ids = db.execute(
            select(OrganizationMembership.organization_id).where(
                OrganizationMembership.user_id == current_user.id
            )
        ).scalars().all()
        user_biz_ids = db.execute(
            select(Business.id).where(Business.organization_id.in_(user_org_ids))
        ).scalars().all()
        stmt = stmt.where(DecisionRecord.business_id.in_(user_biz_ids))

    if status_filter:
        stmt = stmt.where(DecisionRecord.status == status_filter.upper())
    stmt = stmt.order_by(desc(DecisionRecord.created_at)).limit(limit).offset(offset)
    records = db.execute(stmt).scalars().all()
    return [DecisionRecordResponse.model_validate(r) for r in records]


@router.post(
    "/decisions",
    response_model=DecisionRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a decision record for human review",
    description="Registers a recommendation proposal into the Human Review Gate.",
)
def create_decision(
    payload: DecisionCreateRequest,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> DecisionRecordResponse:
    target_biz_id = x_business_id
    if target_biz_id:
        verify_user_business_access(db, current_user, target_biz_id, action="create decisions for")
    else:
        user_org_ids = db.execute(
            select(OrganizationMembership.organization_id).where(
                OrganizationMembership.user_id == current_user.id
            )
        ).scalars().all()
        biz = db.execute(
            select(Business).where(Business.organization_id.in_(user_org_ids))
        ).scalars().first()
        if biz:
            target_biz_id = biz.id

    if payload.analysis_id:
        run = db.get(AnalysisRun, payload.analysis_id)
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Associated analysis run #{payload.analysis_id} does not exist.",
            )
        # Verify access to the associated analysis run
        verify_user_analysis_access(db, current_user, run.business_id, target_biz_id)
        if not target_biz_id:
            target_biz_id = run.business_id

    if not target_biz_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Business workspace context could not be resolved for decision creation.",
        )

    idemp_key = payload.idempotency_key or f"dec_create_{uuid4().hex}"
    rec_snap = None
    if payload.recommendation_payload and payload.recommendation_type:
        rec_snap = RecommendationSnapshot(
            recommendation_type=payload.recommendation_type,
            action_target_type=payload.action_target_type or "SKU",
            action_target_id=payload.action_target_id or "UNKNOWN",
            point_recommendation=payload.recommendation_payload.get("point_recommendation", {}),
            observed_facts=payload.recommendation_payload.get("observed_facts", {}),
            forecast_outputs=payload.recommendation_payload.get("forecast_outputs", {}),
            assumptions=payload.recommendation_payload.get("assumptions", []),
            limitations=payload.recommendation_payload.get("limitations", []),
            engine_metadata=payload.recommendation_payload.get("engine_metadata", {}),
        )
    elif payload.recommendation_payload:
        rec_snap = RecommendationSnapshot(
            recommendation_type="GENERAL",
            action_target_type="SKU",
            action_target_id="UNKNOWN",
            point_recommendation=payload.recommendation_payload.get("point_recommendation", {}),
            observed_facts=payload.recommendation_payload.get("observed_facts", {}),
            forecast_outputs=payload.recommendation_payload.get("forecast_outputs", {}),
            assumptions=payload.recommendation_payload.get("assumptions", []),
            limitations=payload.recommendation_payload.get("limitations", []),
            engine_metadata=payload.recommendation_payload.get("engine_metadata", {}),
        )

    base_snap = None
    if payload.baseline_metrics_snapshot:
        base_snap = BaselineMetricsSnapshot(
            window_start=payload.baseline_metrics_snapshot.get("window_start", datetime.now(UTC).isoformat()),
            window_end=payload.baseline_metrics_snapshot.get("window_end", datetime.now(UTC).isoformat()),
            window_days=payload.baseline_metrics_snapshot.get("window_days", 30),
            metrics=payload.baseline_metrics_snapshot.get("metrics", {}),
            metric_definitions=payload.baseline_metrics_snapshot.get("metric_definitions", {}),
            provenance=payload.baseline_metrics_snapshot.get("provenance", {}),
        )

    create_payload = DecisionCreatePayload(
        recommendation_text=payload.recommendation_text,
        recommendation_snapshot=rec_snap,
        baseline_metrics_snapshot=base_snap,
        analysis_id=payload.analysis_id,
        reviewer_notes=payload.reviewer_notes,
    )

    decision = DecisionMemoryService.create_decision_record(
        db=db,
        current_user=current_user,
        business_id=target_biz_id,
        payload=create_payload,
        idempotency_key=idemp_key,
    )
    return DecisionRecordResponse.model_validate(decision)


# ---------------------------------------------------------------------------
# PHASE 28 STAGE 3: HISTORICAL DECISION MEMORY RETRIEVAL ENDPOINTS
# ---------------------------------------------------------------------------

@router.get(
    "/decisions/history-context",
    response_model=HistoricalDecisionRetrievalResponse,
    summary="Retrieve historical decision memory context with outcome evaluations and provenance",
    description="Deterministic, tenant-scoped retrieval of historical decisions, recommendations, human dispositions, and observed outcomes for planning and explanations.",
)
def get_historical_decision_context(
    recommendation_type: str | None = Query(None, description="Action category, e.g. INVENTORY_REORDER, PRICE_MARKDOWN"),
    action_target_type: str | None = Query(None, description="Target entity type, e.g. SKU, CATEGORY, STORE"),
    action_target_id: str | None = Query(None, description="Target identifier, e.g. SKU-PREM-101"),
    metric_name: str | None = Query(None, description="Canonical metric identifier, e.g. revenue, stockout_days, margin"),
    decision_status: Literal["PENDING", "APPROVED", "REJECTED", "MODIFIED", "DEFERRED"] | None = Query(None, alias="status", description="Human review disposition"),
    is_action_executed: bool | None = Query(None, description="Filter by downstream action execution"),
    maturity_status: OutcomeMaturityStatus | None = Query(None, description="Filter by outcome maturity status"),
    min_evidence_quality: EvidenceQualityGrade | None = Query(None, description="Minimum evidence quality threshold"),
    created_after: datetime | None = Query(None, description="Filter decisions created at or after UTC timestamp"),
    created_before: datetime | None = Query(None, description="Filter decisions created at or before UTC timestamp"),
    as_of: datetime | None = Query(None, description="Point-in-time evaluation timestamp"),
    limit: int = Query(5, ge=1, le=50),
    offset: int = Query(0, ge=0),
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> HistoricalDecisionRetrievalResponse:
    if not x_business_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Business-ID header is required for tenant-scoped decision retrieval.",
        )
    verify_user_business_access(db, current_user, x_business_id, action="retrieve historical decisions")

    query = DecisionRetrievalFilter(
        recommendation_type=recommendation_type,
        action_target_type=action_target_type,
        action_target_id=action_target_id,
        metric_name=metric_name,
        status=decision_status,
        is_action_executed=is_action_executed,
        maturity_status=maturity_status,
        min_evidence_quality=min_evidence_quality,
        created_after=created_after,
        created_before=created_before,
        limit=limit,
        offset=offset,
    )
    return DecisionMemoryService.retrieve_historical_decisions(
        db=db,
        current_user=current_user,
        business_id=x_business_id,
        query=query,
        as_of=as_of,
    )


@router.post(
    "/decisions/search-history",
    response_model=HistoricalDecisionRetrievalResponse,
    summary="Search historical decision memory context with structured filters",
    description="Deterministic, tenant-scoped search of historical decisions, recommendations, human dispositions, and observed outcomes.",
)
def search_historical_decision_context(
    query: DecisionRetrievalFilter,
    as_of: datetime | None = Query(None, description="Optional point-in-time evaluation timestamp"),
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> HistoricalDecisionRetrievalResponse:
    if not x_business_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Business-ID header is required for tenant-scoped decision retrieval.",
        )
    verify_user_business_access(db, current_user, x_business_id, action="retrieve historical decisions")

    return DecisionMemoryService.retrieve_historical_decisions(
        db=db,
        current_user=current_user,
        business_id=x_business_id,
        query=query,
        as_of=as_of,
    )


@router.get(
    "/decisions/{decision_id}",
    response_model=DecisionRecordResponse,
    summary="Get single decision record",
)
def get_decision(
    decision_id: int,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> DecisionRecordResponse:
    record = db.get(DecisionRecord, decision_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision record #{decision_id} not found.",
        )

    # Multi-tenant IDOR defense: verify user and workspace ownership
    verify_user_decision_access(db, current_user, record.business_id, x_business_id)

    return DecisionRecordResponse.model_validate(record)


@router.patch(
    "/decisions/{decision_id}",
    response_model=DecisionRecordResponse,
    summary="Update decision disposition (Approve, Reject, Modify, Defer)",
    description="Commits human analyst review disposition to the audit ledger.",
)
def update_decision(
    decision_id: int,
    payload: DecisionUpdateRequest,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> DecisionRecordResponse:
    record = db.get(DecisionRecord, decision_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision record #{decision_id} not found.",
        )

    # Multi-tenant IDOR defense: verify user and workspace ownership
    verify_user_decision_access(db, current_user, record.business_id, x_business_id)

    valid_statuses = {"PENDING", "APPROVED", "REJECTED", "MODIFIED", "DEFERRED"}
    new_status = payload.status.upper().strip()
    if new_status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status '{payload.status}'. Must be one of: {sorted(valid_statuses)}",
        )

    if new_status in {"APPROVED", "REJECTED", "MODIFIED", "DEFERRED"}:
        review_payload = DecisionReviewPayload(
            status=new_status,
            reviewer_notes=payload.reviewer_notes,
            reviewed_by=payload.reviewed_by or (current_user.email if current_user else None),
            modified_parameters=payload.modified_parameters,
        )
        idemp_key = payload.idempotency_key or f"dec_rev_{record.id}_{new_status}_{int(datetime.now(UTC).timestamp()*1000)}"
        record = DecisionMemoryService.record_human_review(
            db=db,
            current_user=current_user,
            business_id=record.business_id,
            decision_id=record.id,
            review_payload=review_payload,
            idempotency_key=idemp_key,
        )
    else:
        record.status = new_status
        record.reviewer_notes = payload.reviewer_notes or record.reviewer_notes
        db.commit()
        db.refresh(record)

    return DecisionRecordResponse.model_validate(record)


@router.get(
    "/decisions/{decision_id}/audit-events",
    response_model=list[DecisionAuditEventResponse],
    summary="List immutable audit events for a decision record",
)
def list_decision_audit_events(
    decision_id: int,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[DecisionAuditEventResponse]:
    record = db.get(DecisionRecord, decision_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Decision record #{decision_id} not found.")
    verify_user_decision_access(db, current_user, record.business_id, x_business_id)

    events = db.execute(
        select(DecisionAuditEvent)
        .where(DecisionAuditEvent.decision_id == decision_id)
        .order_by(DecisionAuditEvent.revision.asc())
    ).scalars().all()
    return [DecisionAuditEventResponse.model_validate(e) for e in events]


@router.get(
    "/decisions/{decision_id}/verify-audit-chain",
    response_model=AuditChainVerificationReport,
    summary="Verify cryptographic hash chain integrity for a decision record",
)
def verify_audit_chain(
    decision_id: int,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> AuditChainVerificationReport:
    record = db.get(DecisionRecord, decision_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Decision record #{decision_id} not found.")
    verify_user_decision_access(db, current_user, record.business_id, x_business_id)

    return DecisionMemoryService.verify_decision_audit_chain(
        db=db,
        current_user=current_user,
        business_id=record.business_id,
        decision_id=decision_id,
    )


# ---------------------------------------------------------------------------
# 3. PHASE 28 STAGE 2: OUTCOME RECORDING & MATURITY EVALUATION ENDPOINTS
# ---------------------------------------------------------------------------

@router.post(
    "/decisions/{decision_id}/outcomes",
    response_model=OutcomeObservationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record empirical outcome observation for a decision",
)
def record_outcome(
    decision_id: int,
    payload: OutcomeObservationCreateRequest,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> OutcomeObservationResponse:
    record = db.get(DecisionRecord, decision_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Decision record #{decision_id} not found.")
    verify_user_decision_access(db, current_user, record.business_id, x_business_id)

    obs = DecisionMemoryService.record_outcome_observation(
        db=db,
        current_user=current_user,
        business_id=record.business_id,
        decision_id=decision_id,
        payload=payload,
    )
    return OutcomeObservationResponse.model_validate(obs)


@router.get(
    "/decisions/{decision_id}/outcomes",
    response_model=list[OutcomeObservationResponse],
    summary="List recorded outcome observations for a decision",
)
def list_outcomes(
    decision_id: int,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[OutcomeObservationResponse]:
    record = db.get(DecisionRecord, decision_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Decision record #{decision_id} not found.")
    verify_user_decision_access(db, current_user, record.business_id, x_business_id)

    observations = DecisionMemoryService.list_outcome_observations(
        db=db,
        current_user=current_user,
        business_id=record.business_id,
        decision_id=decision_id,
    )
    return [OutcomeObservationResponse.model_validate(o) for o in observations]


@router.post(
    "/decisions/{decision_id}/action-execution",
    response_model=DecisionRecordResponse,
    summary="Record action execution or monitoring start (e.g. for deferred decisions)",
)
def record_action_execution(
    decision_id: int,
    payload: OutcomeActionExecutionRequest,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> DecisionRecordResponse:
    record = db.get(DecisionRecord, decision_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Decision record #{decision_id} not found.")
    verify_user_decision_access(db, current_user, record.business_id, x_business_id)

    updated_rec = DecisionMemoryService.record_action_execution(
        db=db,
        current_user=current_user,
        business_id=record.business_id,
        decision_id=decision_id,
        payload=payload,
    )
    return DecisionRecordResponse.model_validate(updated_rec)


@router.get(
    "/decisions/{decision_id}/evaluate-outcome",
    response_model=OutcomeEvaluationResponse,
    summary="Evaluate outcome maturity, empirical coverage, pre/post delta, and evidence quality",
)
def evaluate_outcome(
    decision_id: int,
    metric_name: str | None = Query(None, description="Optional metric to evaluate, e.g. revenue, stockout_days"),
    as_of: datetime | None = Query(None, description="Optional evaluation point-in-time timestamp"),
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> OutcomeEvaluationResponse:
    record = db.get(DecisionRecord, decision_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Decision record #{decision_id} not found.")
    verify_user_decision_access(db, current_user, record.business_id, x_business_id)

    return DecisionMemoryService.evaluate_decision_outcome(
        db=db,
        current_user=current_user,
        business_id=record.business_id,
        decision_id=decision_id,
        metric_name=metric_name,
        as_of=as_of,
    )



