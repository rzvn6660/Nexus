"""API endpoints for Analysis Run History, Human Decisions (HITL), and Reports."""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.models.history import AnalysisRun, DecisionRecord
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
    response_model=List[AnalysisRunSummary],
    summary="List historical agent analysis runs",
    description="Retrieve paginated list of past analytical runs with execution telemetry and status.",
)
def list_analysis_runs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
) -> List[AnalysisRunSummary]:
    stmt = (
        select(AnalysisRun)
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
def get_analysis_run(
    run_id: int,
    db: Session = Depends(get_db_session),
) -> AnalysisRunDetail:
    run = db.get(AnalysisRun, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis run #{run_id} not found.",
        )
    return AnalysisRunDetail.model_validate(run)


@router.get(
    "/runs/{run_id}/report",
    response_model=ReportExportResponse,
    summary="Export analysis dossier report",
    description="Generates an exportable, audit-ready Markdown or JSON dossier of an analysis run.",
)
def export_analysis_report(
    run_id: int,
    format: str = Query("markdown", pattern="^(markdown|json)$"),
    db: Session = Depends(get_db_session),
) -> ReportExportResponse:
    run = db.get(AnalysisRun, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis run #{run_id} not found.",
        )

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
        generated_at=datetime.now(timezone.utc),
        content=content,
    )


# ---------------------------------------------------------------------------
# 2. HUMAN-IN-THE-LOOP DECISION ENDPOINTS
# ---------------------------------------------------------------------------

@router.get(
    "/decisions",
    response_model=List[DecisionRecordResponse],
    summary="List Human-in-the-Loop decision records",
    description="Retrieve decisions with optional filtering by status (PENDING, APPROVED, REJECTED, MODIFIED).",
)
def list_decisions(
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(PENDING|APPROVED|REJECTED|MODIFIED)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
) -> List[DecisionRecordResponse]:
    stmt = select(DecisionRecord)
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
    db: Session = Depends(get_db_session),
) -> DecisionRecordResponse:
    if payload.analysis_id:
        run = db.get(AnalysisRun, payload.analysis_id)
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Associated analysis run #{payload.analysis_id} does not exist.",
            )

    decision = DecisionRecord(
        analysis_id=payload.analysis_id,
        recommendation_text=payload.recommendation_text,
        status="PENDING",
        reviewer_notes=payload.reviewer_notes,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return DecisionRecordResponse.model_validate(decision)


@router.get(
    "/decisions/{decision_id}",
    response_model=DecisionRecordResponse,
    summary="Get single decision record",
)
def get_decision(
    decision_id: int,
    db: Session = Depends(get_db_session),
) -> DecisionRecordResponse:
    record = db.get(DecisionRecord, decision_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision record #{decision_id} not found.",
        )
    return DecisionRecordResponse.model_validate(record)


@router.patch(
    "/decisions/{decision_id}",
    response_model=DecisionRecordResponse,
    summary="Update decision disposition (Approve, Reject, Modify)",
    description="Commits human analyst review disposition to the audit ledger.",
)
def update_decision(
    decision_id: int,
    payload: DecisionUpdateRequest,
    db: Session = Depends(get_db_session),
) -> DecisionRecordResponse:
    record = db.get(DecisionRecord, decision_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision record #{decision_id} not found.",
        )

    valid_statuses = {"PENDING", "APPROVED", "REJECTED", "MODIFIED"}
    new_status = payload.status.upper().strip()
    if new_status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status '{payload.status}'. Must be one of: {sorted(valid_statuses)}",
        )

    record.status = new_status
    record.reviewer_notes = payload.reviewer_notes or record.reviewer_notes
    record.reviewed_by = payload.reviewed_by or record.reviewed_by or "analyst"
    record.reviewed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(record)
    return DecisionRecordResponse.model_validate(record)
